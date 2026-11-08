variable "project_id" { type = string }
variable "region" {
  type    = string
  default = "europe-west3"
}
variable "name" {
  type    = string
  default = "g-utils-mcp"
}

locals {
  apis = toset(["run.googleapis.com", "artifactregistry.googleapis.com",
    "secretmanager.googleapis.com", "storage.googleapis.com", "iam.googleapis.com",
  "gmail.googleapis.com", "drive.googleapis.com", "docs.googleapis.com"])
}

resource "google_project_service" "required" {
  for_each           = local.apis
  project            = var.project_id
  service            = each.value
  disable_on_destroy = false
}

resource "google_service_account" "runtime" {
  account_id   = var.name
  display_name = "g-utils-mcp runtime (no administrative permissions)"
  depends_on   = [google_project_service.required]
}

resource "google_artifact_registry_repository" "runtime" {
  location      = var.region
  repository_id = var.name
  format        = "DOCKER"
  depends_on    = [google_project_service.required]
}

resource "google_storage_bucket" "policy" {
  name                        = "${var.project_id}-${var.name}-policy"
  location                    = var.region
  uniform_bucket_level_access = true
  public_access_prevention    = "enforced"
  force_destroy               = true # `terraform destroy` removes the policy with it
  versioning { enabled = true }
  soft_delete_policy { retention_duration_seconds = 604800 }
  depends_on = [google_project_service.required]
}

# File contents above 5 MB on their way between the agent and Google. Never credentials.
resource "google_storage_bucket" "temporary" {
  name                        = "${var.project_id}-${var.name}-temporary"
  location                    = var.region
  uniform_bucket_level_access = true
  public_access_prevention    = "enforced"
  force_destroy               = true
  soft_delete_policy { retention_duration_seconds = 0 }
  lifecycle_rule {
    condition { age = 1 }
    action { type = "Delete" }
  }
  depends_on = [google_project_service.required]
}

resource "google_storage_bucket_iam_member" "temporary_writer" {
  bucket = google_storage_bucket.temporary.name
  role   = "roles/storage.objectCreator"
  member = "serviceAccount:${google_service_account.runtime.email}"
}

resource "google_storage_bucket_iam_member" "temporary_reader" {
  bucket = google_storage_bucket.temporary.name
  role   = "roles/storage.objectViewer"
  member = "serviceAccount:${google_service_account.runtime.email}"
}

resource "google_storage_bucket_iam_member" "policy_reader" {
  bucket = google_storage_bucket.policy.name
  role   = "roles/storage.objectViewer"
  member = "serviceAccount:${google_service_account.runtime.email}"
}

# The single secret: OAuth client, refresh tokens and MCP token(s). Values are written
# by scripts/admin.py, never by Terraform. The runtime may only read it.
resource "google_secret_manager_secret" "runtime" {
  secret_id = var.name
  replication {
    auto {}
  }
  depends_on = [google_project_service.required]
}

resource "google_secret_manager_secret_iam_member" "runtime_reader" {
  secret_id = google_secret_manager_secret.runtime.id
  role      = "roles/secretmanager.secretAccessor"
  member    = "serviceAccount:${google_service_account.runtime.email}"
}

output "runtime_service_account" { value = google_service_account.runtime.email }
output "policy_uri" { value = "gs://${google_storage_bucket.policy.name}/policies/${var.name}.yml" }
output "temporary_bucket" { value = google_storage_bucket.temporary.name }
output "image_repository" { value = "${var.region}-docker.pkg.dev/${var.project_id}/${google_artifact_registry_repository.runtime.repository_id}/server" }
output "secret_name" { value = google_secret_manager_secret.runtime.id }
