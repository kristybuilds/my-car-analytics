import os
import pandas as pd
import io
from google.cloud import bigquery, storage
from datetime import datetime, timezone

# --- CONFIGURATION ---
GCP_PROJECT_ID = os.environ.get('GCP_PROJECT_ID')
URL_DATA = os.environ.get('URL_DATA') 
GCP_GCS_BUCKET = os.environ.get('GCP_GCS_BUCKET')
# Ensuring dataset is 'bronze' as requested
DESTINATION_TABLE = f"{GCP_PROJECT_ID}.bronze.cars_all"

def get_existing_years(bq_client):
    """Checks BigQuery for years already ingested."""
    query = f"SELECT DISTINCT EXTRACT(YEAR FROM date_reg) as year FROM `{DESTINATION_TABLE}`"
    try:
        query_job = bq_client.query(query)
        results = query_job.result()
        return [row.year for row in results]
    except Exception:
        return []

def run_ingestion_pipeline():
    if not all([GCP_PROJECT_ID, URL_DATA, GCP_GCS_BUCKET]):
        print("ERROR: Missing environment variables.")
        return

    bq_client = bigquery.Client(project=GCP_PROJECT_ID)
    storage_client = storage.Client(project=GCP_PROJECT_ID)
    bucket = storage_client.bucket(GCP_GCS_BUCKET)
    
    run_time = datetime.now(timezone.utc)
    current_year = run_time.year
    
    # Check what we already have
    existing_years = get_existing_years(bq_client)
    
    # Dynamic Range: 2000 to Current Year
    full_range = list(range(2000, current_year + 1))
    
    for year in full_range:
        # Skip historical years that are already done. Always refresh the current year.
        if year in existing_years and year != current_year:
            print(f"⏩ Skipping {year}: Already exists in BigQuery.")
            continue

        url = URL_DATA.format(year)
        try:
            print(f"--- Processing Year: {year} ---")
            df = pd.read_parquet(url)
            
            if df.empty:
                continue

            # Metadata & Data Cleaning
            df['date_reg'] = pd.to_datetime(df['date_reg'])
            df['bronze_ingested_at'] = run_time

            # --- STAGE 1: SAVE TO DATA LAKE (Bronze Lake) ---
            file_path = f"raw/cars/year={year}/data_{run_time.strftime('%Y%m%d_%H%M')}.parquet"
            blob = bucket.blob(file_path)
            
            buffer = io.BytesIO()
            df.to_parquet(buffer, index=False)
            buffer.seek(0)
            
            print(f"💾 Saving to Lake: gs://{GCP_GCS_BUCKET}/{file_path}")
            blob.upload_from_file(buffer, content_type='application/octet-stream')

            # --- STAGE 2: LOAD TO BIGQUERY (Partitioned & Clustered) ---
            # If the table exists, BigQuery handles the insert. 
            # If it's the first run, it creates it with these settings:
            job_config = bigquery.LoadJobConfig(
                source_format=bigquery.SourceFormat.PARQUET,
                write_disposition="WRITE_TRUNCATE",
                autodetect=True,
                time_partitioning=bigquery.TimePartitioning(
                    type_=bigquery.TimePartitioningType.YEAR,
                    field="date_reg"
                ),
                clustering_fields=["state"]
            )
            
            uri = f"gs://{GCP_GCS_BUCKET}/{file_path}"
            print(f"Loading {year} into BigQuery Warehouse...")
            load_job = bq_client.load_table_from_uri(uri, DESTINATION_TABLE, job_config=job_config)
            load_job.result() 
            
            print(f"Successfully processed {year}.")
            
        except Exception as e:
            print(f"Could not process {year}: {e}")

if __name__ == "__main__":
    run_ingestion_pipeline()