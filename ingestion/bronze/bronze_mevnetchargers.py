import os
import requests
import pandas as pd
import io
from google.cloud import bigquery, storage
from datetime import datetime, timezone

# --- CONFIGURATION ---
GCP_PROJECT_ID = os.environ.get('GCP_PROJECT_ID')
MEVNET_URL = os.environ.get('MEVNET_API_URL')
GCP_GCS_BUCKET = os.environ.get('GCP_GCS_BUCKET')
DESTINATION_TABLE = f"{GCP_PROJECT_ID}.bronze.mevnet_chargers"

def delete_current_sync_data(bq_client, run_date):
    """Idempotency: Cleans up records from the current day."""
    day_str = run_date.strftime('%Y-%m-%d')
    print(f"🧹 Cleaning up existing records for {day_str}...")
    query = f"DELETE FROM `{DESTINATION_TABLE}` WHERE DATE(bronze_ingested_at) = '{day_str}'"
    try:
        bq_client.query(query).result()
    except Exception as e:
        print(f"Note: Cleanup skipped (table may be new): {e}")

def fetch_mevnet_data():
    """Fetches records from API with pagination."""
    all_rows = []
    offset = 0
    batch_size = 1000
    while True:
        params = {
            "where": "1=1", "outFields": "*", "f": "json",
            "resultOffset": offset, "resultRecordCount": batch_size,
            "orderByFields": "objectid ASC"
        }
        try:
            response = requests.get(MEVNET_URL, params=params, timeout=60)
            response.raise_for_status()
            features = response.json().get('features', [])
            if not features: break
            all_rows.extend([f['attributes'] for f in features])
            if len(features) < batch_size: break
            offset += batch_size
        except Exception as e:
            print(f"API Request Failed: {e}")
            return None
    return pd.DataFrame(all_rows)

def run():
    if not all([GCP_PROJECT_ID, MEVNET_URL, GCP_GCS_BUCKET]):
        print("ERROR: Missing environment variables.")
        return

    bq_client = bigquery.Client(project=GCP_PROJECT_ID)
    storage_client = storage.Client(project=GCP_PROJECT_ID)
    bucket = storage_client.bucket(GCP_GCS_BUCKET)
    run_time = datetime.now(timezone.utc)
    
    df = fetch_mevnet_data()
    
    if df is not None and not df.empty:
        # --- TRANSFORM ---
        df.columns = [c.lower() for c in df.columns]
        df['bronze_ingested_at'] = run_time
        
        # Standardize state names for clustering
        state_col = 'negeri' if 'negeri' in df.columns else 'state'
        if state_col in df.columns:
            df[state_col] = df[state_col].astype(str).str.title()
        
        # --- STAGE 1: SAVE TO DATA LAKE ---
        # Path: raw/mevnet/2026-04-15/chargers.parquet
        date_folder = run_time.strftime('%Y-%m-%d')
        file_path = f"raw/mevnet/{date_folder}/chargers_{run_time.strftime('%H%M')}.parquet"
        blob = bucket.blob(file_path)
        
        buffer = io.BytesIO()
        df.to_parquet(buffer, index=False)
        buffer.seek(0)
        
        print(f"💾 Saving to Lake: gs://{GCP_GCS_BUCKET}/{file_path}")
        blob.upload_from_file(buffer, content_type='application/octet-stream')

        # --- STAGE 2: LOAD TO BIGQUERY ---
        # Cleanup today's run to avoid duplicates
        delete_current_sync_data(bq_client, run_time)

        job_config = bigquery.LoadJobConfig(
            source_format=bigquery.SourceFormat.PARQUET,
            write_disposition="WRITE_APPEND",
            autodetect=True,
            # Daily partitioning based on ingestion time
            time_partitioning=bigquery.TimePartitioning(
                type_=bigquery.TimePartitioningType.DAY,
                field="bronze_ingested_at"
            ),
            # Cluster by state/negeri for faster geographic queries
            clustering_fields=[state_col]
        )
        
        uri = f"gs://{GCP_GCS_BUCKET}/{file_path}"
        print(f"Loading MEVnet data into BQ via Lake...")
        load_job = bq_client.load_table_from_uri(uri, DESTINATION_TABLE, job_config=job_config)
        load_job.result()
        
        print("Success! MEVnet Medallion layer updated.")

if __name__ == "__main__":
    run()