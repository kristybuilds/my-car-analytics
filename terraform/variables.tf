variable "project_id" {
  description = "The GCP Project ID"
  default     = "malaysia-ev-analysis"
}

variable "bucket_name" {
  description = "The name of the GCS bucket"
  default     = "malaysia-ev-analysis-data-lake" 
}

variable "region" {
  description = "The region for all resources"
  default     = "asia-southeast1"
}

variable "car_api_url" {
  description = "The raw data source for car registration data"
  default     = "https://storage.data.gov.my/transportation/cars_{}.parquet"
}

variable "mevnet_api_url" {
  description = "The API endpoint for MEVnet charger data"
  default     = "https://gisdev.planmalaysia.gov.my/server/rest/services/Hosted/MEVnet_EVCB/FeatureServer/0/query"
}

variable "github_repo_url" {
  description = "The URL of the GitHub repository containing Dataform scripts"
  type        = string
}

variable "github_pat" {
  description = "Personal Access Token for GitHub authentication"
  type        = string
  sensitive   = true   # Added: Prevents the token from being printed in the console
}
