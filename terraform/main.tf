terraform {
  required_providers {
    google = {
      source  = "hashicorp/google"
      version = "5.25.0"
    }
  }
}

provider "google" {
  project = var.project_id
  region  = var.region
  # Credentials removed: Terraform will use 'gcloud auth application-default login'
}

data "google_project" "project" {}

# --- 1. SERVICE ACCOUNT & IAM ---

resource "google_service_account" "airflow_orchestrator" {
  account_id   = "airflow-orchestrator"
  display_name = "Airflow Orchestrator Service Account"
}

# Grant Storage Admin (For the Data Lake)
resource "google_project_iam_member" "storage_admin" {
  project = var.project_id
  role    = "roles/storage.objectAdmin"
  member  = "serviceAccount:${google_service_account.airflow_orchestrator.email}"
}

# Grant BigQuery Admin (For the Warehouse)
resource "google_project_iam_member" "bq_admin" {
  project = var.project_id
  role    = "roles/bigquery.admin"
  member  = "serviceAccount:${google_service_account.airflow_orchestrator.email}"
}

# Grant Cloud Run Developer (To manage job settings)
resource "google_project_iam_member" "run_developer" {
  project = var.project_id
  role    = "roles/run.developer"
  member  = "serviceAccount:${google_service_account.airflow_orchestrator.email}"
}

# Grant Cloud Run Invoker (To trigger jobs from Airflow)
resource "google_project_iam_member" "run_invoker" {
  project = var.project_id
  role    = "roles/run.invoker"
  member  = "serviceAccount:${google_service_account.airflow_orchestrator.email}"
}

# Grant Service Account User (Required for Cloud Run to assume this identity)
resource "google_project_iam_member" "sa_user" {
  project = var.project_id
  role    = "roles/iam.serviceAccountUser"
  member  = "serviceAccount:${google_service_account.airflow_orchestrator.email}"
}

# Grant Artifact Registry Reader (To pull the Docker image)
resource "google_project_iam_member" "gcr_reader" {
  project = var.project_id
  role    = "roles/artifactregistry.reader"
  member  = "serviceAccount:${google_service_account.airflow_orchestrator.email}"
}

# --- 2. STORAGE BUCKET (THE DATA LAKE) ---

resource "google_storage_bucket" "malaysia_ev_data_lake" {
  name          = var.bucket_name
  location      = var.region
  force_destroy = true
}

# --- 3. BIGQUERY DATASETS (THE WAREHOUSE) ---

resource "google_bigquery_dataset" "bronze" {
  dataset_id = "bronze"
  location   = var.region
}

resource "google_bigquery_dataset" "silver" {
  dataset_id = "silver"
  location   = var.region
}

resource "google_bigquery_dataset" "gold" {
  dataset_id = "gold"
  location   = var.region
}

# --- 4. CLOUD RUN JOBS ---

# Car Ingestion Job
resource "google_cloud_run_v2_job" "bronze_car_ingestion" {
  name     = "bronze-car-ingestion"
  location = var.region

  template {
    template {
      containers {
        image = "gcr.io/${var.project_id}/ingestion-car-malaysia:latest"
        
        env {
          name  = "GCP_PROJECT_ID"
          value = var.project_id
        }
        env {
          name  = "GCP_GCS_BUCKET"
          value = google_storage_bucket.malaysia_ev_data_lake.name
        }
        env {
          name  = "URL_DATA"
          value = var.car_api_url
        }
      }
      service_account = google_service_account.airflow_orchestrator.email
    }
  }

  lifecycle {
    ignore_changes = [template[0].template[0].containers[0].image]
  }
}

# MEVnet Ingestion Job
resource "google_cloud_run_v2_job" "bronze_mevnet_ingestion" {
  name     = "bronze-mevnet-ingestion"
  location = var.region

  template {
    template {
      containers {
        image = "gcr.io/${var.project_id}/ingestion-car-malaysia:latest"
        
        env {
          name  = "GCP_PROJECT_ID"
          value = var.project_id
        }
        env {
          name  = "GCP_GCS_BUCKET"
          value = google_storage_bucket.malaysia_ev_data_lake.name
        }
        env {
          name  = "MEVNET_API_URL"
          value = var.mevnet_api_url
        }
      }
      service_account = google_service_account.airflow_orchestrator.email
    }
  }

  lifecycle {
    ignore_changes = [template[0].template[0].containers[0].image]
  }
}

# --- 5. DATAFORM INFRASTRUCTURE ---

# Enable Dataform API
resource "google_project_service" "dataform_api" {
  project = var.project_id
  service = "dataform.googleapis.com"
  disable_on_redeploy = false
}

# The Repository linked to GitHub
resource "google_dataform_repository" "ev_analysis_repo" {
  name     = "malaysia-ev-analysis"
  region   = var.region
  project  = var.project_id

  git_remote_settings {
    url               = var.github_repo_url
    default_branch    = "main"
    # This refers to the secret created below
    authentication_token_secret_version = google_secret_manager_secret_version.github_token_version.id
  }

  workspace_compilation_overrides {
    default_database = var.project_id
  }

  service_account = google_service_account.dataform_executor.email
  depends_on      = [
    google_secret_manager_secret_version.github_token_version,
    google_project_service.dataform_api
    ]
}

# --- 6. GITHUB AUTHENTICATION (SECRET MANAGER) ---

resource "google_secret_manager_secret" "github_token" {
  secret_id = "github-token"
  replication {
    auto {}
  }
}

resource "google_secret_manager_secret_version" "github_token_version" {
  secret      = google_secret_manager_secret.github_token.id
  secret_data = var.github_pat # Peer provides this in their terraform.tfvars
}

# --- 7. DATAFORM PERMISSIONS ---

resource "google_service_account" "dataform_executor" {
  account_id   = "dataform-executor"
  display_name = "Dataform Executor Service Account"
}

resource "google_project_iam_member" "dataform_bq_admin" {
  project = var.project_id
  role    = "roles/bigquery.admin"
  member  = "serviceAccount:${google_service_account.dataform_executor.email}"
}

# Critical: Allow the Google-managed Dataform service agent to read the secret
resource "google_secret_manager_secret_iam_member" "dataform_secret_accessor" {
  secret_id = google_secret_manager_secret.github_token.id
  role      = "roles/secretmanager.secretAccessor"
  member    = "serviceAccount:service-${data.google_project.project.number}@gcp-sa-dataform.iam.gserviceaccount.com"
}