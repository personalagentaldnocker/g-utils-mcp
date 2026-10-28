terraform {
  required_version = "= 1.13.5"
  required_providers {
    google = {
      source  = "hashicorp/google"
      version = "= 7.8.0"
    }
  }
}
variable "project_id" { type = string }
variable "region" {
  type    = string
  default = "europe-west3"
}
provider "google" { project = var.project_id }
resource "google_storage_bucket" "state" {
  name                        = "${var.project_id}-workspace-utils-tfstate"
  location                    = var.region
  uniform_bucket_level_access = true
  public_access_prevention    = "enforced"
  force_destroy               = false
  versioning { enabled = true }
  lifecycle { prevent_destroy = true }
}
output "state_bucket" { value = google_storage_bucket.state.name }
