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

provider "google-beta" {
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

# --- ARTIFACT REGISTRY ---

resource "google_artifact_registry_repository" "ingestion_repo" {
  location      = var.region
  repository_id = "ev-ingestion-images"
  description   = "Docker repository for EV ingestion microservices"
  format        = "DOCKER"
}

resource "null_resource" "docker_push" {
  # Trigger this whenever the project ID or region changes
  triggers = {
    project_id = var.project_id
    region     = var.region
    # This ensures it reruns if you change your Python code
    code_hash  = base64sha256("${path.module}/ingestion/bronze_cars_all.py") 
  }

  depends_on = [google_artifact_registry_repository.ingestion_repo]

  provisioner "local-exec" {
    command = <<EOT
      gcloud auth configure-docker ${var.region}-docker.pkg.dev --quiet
      docker build -t ${var.region}-docker.pkg.dev/${var.project_id}/${google_artifact_registry_repository.ingestion_repo.repository_id}/ingestion-car-malaysia:latest ${path.module}/../ingestion
      docker push ${var.region}-docker.pkg.dev/${var.project_id}/${google_artifact_registry_repository.ingestion_repo.repository_id}/ingestion-car-malaysia:latest
    EOT
  }
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

  # CRITICAL: Wait for the image to be pushed before creating the job
  depends_on = [null_resource.docker_push]

  template {
    template {
      containers {
        image = "${var.region}-docker.pkg.dev/${var.project_id}/${google_artifact_registry_repository.ingestion_repo.repository_id}/ingestion-car-malaysia:latest"
        
        # OVERRIDE: Run the Car Script
        command = ["python"]
        args    = ["bronze_cars_all.py"]

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

  # CRITICAL: Wait for the image to be pushed before creating the job
  depends_on = [null_resource.docker_push]

  template {
    template {
      containers {
        image = "${var.region}-docker.pkg.dev/${var.project_id}/${google_artifact_registry_repository.ingestion_repo.repository_id}/ingestion-car-malaysia:latest"
        
        # OVERRIDE: Run the MEVnet Script
        command = ["python"]
        args    = ["bronze_mevnetchargers.py"]

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
  disable_on_destroy = false
}

# The Repository linked to GitHub
resource "google_dataform_repository" "ev_analysis_repo" {
  provider = google-beta
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

resource "google_project_service" "secretmanager_api" {
  service            = "secretmanager.googleapis.com"
  disable_on_destroy = false
}

resource "google_secret_manager_secret" "github_token" {
  secret_id = "github-token"
  depends_on = [google_project_service.secretmanager_api]
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

resource "google_project_service_identity" "dataform_sa" {
  provider = google-beta
  project  = var.project_id
  service  = "dataform.googleapis.com"
}

# Critical: Allow the Google-managed Dataform service agent to read the secret
resource "google_secret_manager_secret_iam_member" "dataform_secret_accessor" {
  depends_on = [google_project_service_identity.dataform_sa]
  secret_id = google_secret_manager_secret.github_token.id
  role      = "roles/secretmanager.secretAccessor"
  member    = "serviceAccount:service-${data.google_project.project.number}@gcp-sa-dataform.iam.gserviceaccount.com"
}

# The "Handshake": Allow Dataform to impersonate your executor account
resource "google_service_account_iam_member" "dataform_impersonation" {
  service_account_id = google_service_account.dataform_executor.name
  role               = "roles/iam.serviceAccountUser"
  # This is the Google-managed "Service Agent" for Dataform
  member             = "serviceAccount:service-${data.google_project.project.number}@gcp-sa-dataform.iam.gserviceaccount.com"
}

resource "google_service_account_iam_member" "dataform_token_creator" {
  service_account_id = google_service_account.dataform_executor.name
  role               = "roles/iam.serviceAccountTokenCreator"
  member             = "serviceAccount:service-${data.google_project.project.number}@gcp-sa-dataform.iam.gserviceaccount.com"
}

# Grant BigQuery Job User at the Project Level
resource "google_project_iam_member" "dataform_job_user" {
  project = var.project_id
  role    = "roles/bigquery.jobUser"
  member  = "serviceAccount:${google_service_account.dataform_executor.email}"
}

# Grant Data Editor on each specific dataset
# You can use a loop to make this cleaner
resource "google_bigquery_dataset_iam_member" "dataform_dataset_editor" {
  for_each   = toset(["bronze", "silver", "gold", "dataform_assertions"])
  project    = var.project_id
  dataset_id = each.key
  role       = "roles/bigquery.dataEditor"
  member     = "serviceAccount:${google_service_account.dataform_executor.email}"

  # Add this to prevent the 404 errors
  depends_on = [
    google_bigquery_dataset.bronze,
    google_bigquery_dataset.silver,
    google_bigquery_dataset.gold
  ]
}