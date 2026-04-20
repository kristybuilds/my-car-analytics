import os
import pandas as pd
import io
from google.cloud import bigquery, storage
from datetime import datetime, timezone

# --- CONFIGURATION ---
GCP_PROJECT_ID = os.environ.get('GCP_PROJECT_ID')
URL_DATA = os.environ.get('URL_DATA') 
GCP_GCS_BUCKET = os.environ.get('GCP_GCS_BUCKET')
DESTINATION_TABLE = f"{GCP_PROJECT_ID}.bronze.cars_all"

def get_missing_years(bq_client, full_range):
    """Returns existing years and missing years compared to full_range."""
    query = f"SELECT DISTINCT EXTRACT(YEAR FROM date_reg) AS year FROM `{DESTINATION_TABLE}`"
    try:
        results = bq_client.query(query).result()
        existing = {int(row.year) for row in results}
        missing = [y for y in full_range if y not in existing]
        return existing, missing
    except Exception:
        return set(), list(full_range)

def run_ingestion_pipeline():
    if not all([GCP_PROJECT_ID, URL_DATA, GCP_GCS_BUCKET]):
        print("❌ ERROR: Missing environment variables:")
        print(f"  GCP_PROJECT_ID: {GCP_PROJECT_ID}")
        print(f"  URL_DATA: {URL_DATA}")
        print(f"  GCP_GCS_BUCKET: {GCP_GCS_BUCKET}")
        return

    if '{}' not in URL_DATA:
        print("❌ ERROR: URL_DATA missing '{}' placeholder.")
        print(f"  URL_DATA value: {URL_DATA}")
        return

    bq_client = bigquery.Client(project=GCP_PROJECT_ID)
    storage_client = storage.Client(project=GCP_PROJECT_ID)
    bucket = storage_client.bucket(GCP_GCS_BUCKET)

    run_time = datetime.now(timezone.utc)
    current_year = run_time.year
    full_range = list(range(2000, current_year + 1))

    # --- Determine what needs to be loaded ---
    existing_years, missing_years = get_missing_years(bq_client, full_range)

    if missing_years:
        years_to_load = sorted(set(missing_years + [current_year]))
        print(f"📭 Missing years detected: {missing_years}")
        print(f"  Will load: {years_to_load}")
    else:
        years_to_load = [current_year]
        print(f"✅ All historical years present — refreshing {current_year} only.")

    print(f"\n📋 Pipeline config:")
    print(f"  Project:       {GCP_PROJECT_ID}")
    print(f"  Destination:   {DESTINATION_TABLE}")
    print(f"  Bucket:        {GCP_GCS_BUCKET}")
    print(f"  Year range:    2000 → {current_year} ({len(full_range)} years)")
    print(f"  Existing:      {sorted(existing_years) if existing_years else 'none (first run)'}")
    print(f"  To load:       {years_to_load}\n")

    total_rows = 0
    years_skipped = []
    years_failed = []

    for year in full_range:
        if year not in years_to_load:
            print(f"⏩ {year}: Already loaded — skipping.")
            years_skipped.append(year)
            continue

        url = URL_DATA.format(year)
        label = "🔄 REFRESH" if year == current_year and year in existing_years else "🆕 NEW"
        print(f"\n--- Year {year} {label} ---")
        print(f"  Fetching: {url}")

        try:
            df = pd.read_parquet(url)
            row_count = len(df)
            print(f"  Rows fetched: {row_count:,}")

            if df.empty:
                print(f"  ⚠️  Empty — skipping.")
                years_skipped.append(year)
                continue

            if 'date_reg' in df.columns:
                df['date_reg'] = pd.to_datetime(df['date_reg'])
            else:
                print(f"  ⚠️  WARNING: 'date_reg' not found. Columns: {df.columns.tolist()}")

            df['bronze_ingested_at'] = run_time

            # Upload to GCS
            file_path = f"raw/cars/year={year}/data_{run_time.strftime('%Y%m%d_%H%M')}.parquet"
            blob = bucket.blob(file_path)
            buffer = io.BytesIO()
            df.to_parquet(buffer, index=False)
            buffer.seek(0)
            blob.upload_from_file(buffer, content_type='application/octet-stream')
            print(f"  ✅ GCS: gs://{GCP_GCS_BUCKET}/{file_path}")

            # Target specific year partition using $year decorator
            # WRITE_TRUNCATE only affects this partition, not the whole table
            partition_table = f"{DESTINATION_TABLE}${year}"

            job_config = bigquery.LoadJobConfig(
                source_format=bigquery.SourceFormat.PARQUET,
                write_disposition=bigquery.WriteDisposition.WRITE_TRUNCATE,
                autodetect=True,
                time_partitioning=bigquery.TimePartitioning(
                    type_=bigquery.TimePartitioningType.YEAR,
                    field="date_reg"
                ),
                clustering_fields=["state"]
            )

            load_job = bq_client.load_table_from_uri(
                f"gs://{GCP_GCS_BUCKET}/{file_path}",
                partition_table,
                job_config=job_config
            )
            load_job.result()

            total_rows += row_count
            print(f"  ✅ BQ loaded. Running total: {total_rows:,}")

        except Exception as e:
            print(f"  ❌ Failed for {year}: {e}")
            years_failed.append(year)

    print("\n" + "="*50)
    print("📊 PIPELINE SUMMARY")
    print("="*50)
    print(f"  Total rows loaded:  {total_rows:,}")
    print(f"  Years loaded:       {len(years_to_load) - len(years_failed)}")
    print(f"  Years skipped:      {len(years_skipped)} → {years_skipped if years_skipped else 'none'}")
    print(f"  Years failed:       {len(years_failed)} → {years_failed if years_failed else 'none'}")
    print("="*50)

if __name__ == "__main__":
    run_ingestion_pipeline()