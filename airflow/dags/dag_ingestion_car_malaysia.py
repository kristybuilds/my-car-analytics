import os
from airflow import DAG
from airflow.providers.google.cloud.operators.cloud_run import CloudRunExecuteJobOperator
from airflow.providers.google.cloud.operators.dataform import (
    DataformCreateCompilationResultOperator,
    DataformCreateWorkflowInvocationOperator,
)
from airflow.models import Variable
from datetime import datetime, timedelta

GCP_PROJECT_ID = os.environ.get("GCP_PROJECT_ID") or Variable.get("GCP_PROJECT_ID")
GCP_GCS_BUCKET = os.environ.get("GCP_GCS_BUCKET") or Variable.get("GCP_GCS_BUCKET")
DATAFORM_REGION = os.environ.get("DATAFORM_REGION") or Variable.get("DATAFORM_REGION")
DATAFORM_REPOSITORY_ID = os.environ.get("DATAFORM_REPOSITORY_ID") or Variable.get("DATAFORM_REPOSITORY_ID")

# 1. DEFAULT ARGUMENTS
# This defines how Airflow behaves if a task fails
default_args = {
    'owner': 'Kristy',
    'depends_on_past': False,
    'email_on_failure': False,
    'email_on_retry': False,
    'retries': 1,
    'retry_delay': timedelta(minutes=5),
}

# 2. THE DAG DEFINITION
with DAG(
    'ingestion_car_malaysia',
    default_args=default_args,
    max_active_runs=1,
    description='Triggers Ingestion Jobs in GCP for Cars and MEVnet',
    schedule='0 0 1 * *',  # Runs every first day of the month
    start_date=datetime(2026, 1, 1),
    catchup=False,
    tags=['ev_analysis', 'bronze', 'silver', 'gold'],
) as dag:

    # 3. TASK 1: RUN CAR INGESTION
    # This calls the Cloud Run Job we'll create from your Docker image
    run_car_job = CloudRunExecuteJobOperator(
        task_id='trigger_bronze_car',
        project_id=GCP_PROJECT_ID, # Replace with your ID
        region=DATAFORM_REGION,
        job_name='bronze-car-ingestion',
        gcp_conn_id='google_cloud_default',
        overrides={
            "container_overrides": [
                {
                    "args": ["bronze/bronze_cars_all.py"],
                    "env": [
                        {"name": "GCP_PROJECT_ID", "value": GCP_PROJECT_ID},
                        {"name": "GCP_GCS_BUCKET", "value": GCP_GCS_BUCKET},
                        {"name": "PYTHONUNBUFFERED", "value": "1"}
                    ]
                }
            ]
        },
        dag=dag,
    )

    # 4. TASK 2: RUN MEVNET INGESTION
    run_mevnet_job = CloudRunExecuteJobOperator(
        task_id='trigger_bronze_mevnet',
        project_id=GCP_PROJECT_ID, # Replace with your ID
        region=DATAFORM_REGION,
        job_name='bronze-mevnet-ingestion',
        gcp_conn_id='google_cloud_default',
        overrides={
            "container_overrides": [
                {
                    "args": ["bronze/bronze_mevnetchargers.py"],
                    "env": [
                        {"name": "GCP_PROJECT_ID", "value": GCP_PROJECT_ID},
                        {"name": "GCP_GCS_BUCKET", "value": GCP_GCS_BUCKET},
                        {"name": "PYTHONUNBUFFERED", "value": "1"}
                    ]
                }
            ]
        },
        dag=dag,
    )

    # --- SILVER & GOLD LAYER (Dataform Automation) ---
    
    # 5. Compile the Dataform code from your 'main' branch
    compile_dataform = DataformCreateCompilationResultOperator(
        task_id="compile_dataform",
        project_id=GCP_PROJECT_ID,
        region=DATAFORM_REGION,
        repository_id=DATAFORM_REPOSITORY_ID,
        compilation_result={"git_commitish": "main"},
    )

    # 6. Invoke the transformation (Runs Silver + Gold)
    execute_dataform = DataformCreateWorkflowInvocationOperator(
        task_id="execute_dataform_workflow",
        project_id=GCP_PROJECT_ID,
        region=DATAFORM_REGION,
        repository_id=DATAFORM_REPOSITORY_ID,
        workflow_invocation={
            "compilation_result": "{{ task_instance.xcom_pull(task_ids='compile_dataform')['name'] }}"
        },
    )

    # 7. THE WORKFLOW (THE "BITSHIFT")
    # Both can run at the same time (in parallel)
    [run_car_job, run_mevnet_job] >> compile_dataform >> execute_dataform