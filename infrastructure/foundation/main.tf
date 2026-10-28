variable "project_id" { type = string }
variable "region" {
  type    = string
  default = "europe-west3"
}
variable "name" {
  type    = string
  default = "workspace-utils-mcp"
}
variable "oauth_client_secrets" {
  type    = set(string)
  default = ["oauth-workspace-client-secret"]
}
variable "refresh_token_secrets" {
  type    = set(string)
  default = []
}
variable "principal_digest_secrets" {
  type    = set(string)
  default = []
}

locals {
  apis = toset(["run.googleapis.com", "artifactregistry.googleapis.com",
    "secretmanager.googleapis.com", "storage.googleapis.com", "iam.googleapis.com",
  "gmail.googleapis.com", "drive.googleapis.com", "docs.googleapis.com"])
  all_secrets = setunion(var.oauth_client_secrets, var.refresh_token_secrets, var.principal_digest_secrets)
}

resource "google_project_service" "required" {
  for_each           = local.apis
  project            = var.project_id
  service            = each.value
  disable_on_destroy = false
}

resource "google_service_account" "runtime" {
  account_id   = var.name
  display_name = "Workspace utilities MCP runtime (no administrative permissions)"
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
  force_destroy               = false
  versioning { enabled = true }
  soft_delete_policy { retention_duration_seconds = 604800 }
  lifecycle { prevent_destroy = true }
  depends_on = [google_project_service.required]
}

resource "google_storage_bucket" "temporary" {
  name                        = "${var.project_id}-${var.name}-temporary"
  location                    = var.region
  uniform_bucket_level_access = true
  public_access_prevention    = "enforced"
  force_destroy               = false
  soft_delete_policy { retention_duration_seconds = 0 }
  lifecycle_rule {
    condition { age = 1 }
    action { type = "Delete" }
  }
  depends_on = [google_project_service.required]
}

resource "google_storage_bucket_iam_member" "policy_reader" {
  bucket = google_storage_bucket.policy.name
  role   = "roles/storage.objectViewer"
  member = "serviceAccount:${google_service_account.runtime.email}"
}

resource "google_storage_bucket_iam_member" "temporary_objects" {
  bucket = google_storage_bucket.temporary.name
  role   = "roles/storage.objectUser"
  member = "serviceAccount:${google_service_account.runtime.email}"
}

resource "google_secret_manager_secret" "managed" {
  for_each  = local.all_secrets
  secret_id = each.value
  replication {
    auto {}
  }
  lifecycle { prevent_destroy = true }
  depends_on = [google_project_service.required]
}

resource "google_secret_manager_secret_iam_member" "reader" {
  for_each  = local.all_secrets
  secret_id = google_secret_manager_secret.managed[each.value].id
  role      = "roles/secretmanager.secretAccessor"
  member    = "serviceAccount:${google_service_account.runtime.email}"
}

resource "google_secret_manager_secret_iam_member" "token_writer" {
  for_each  = var.refresh_token_secrets
  secret_id = google_secret_manager_secret.managed[each.value].id
  role      = "roles/secretmanager.secretVersionAdder"
  member    = "serviceAccount:${google_service_account.runtime.email}"
}

output "runtime_service_account" { value = google_service_account.runtime.email }
output "policy_uri" { value = "gs://${google_storage_bucket.policy.name}/policies/${var.name}.yml" }
output "temporary_bucket" { value = google_storage_bucket.temporary.name }
output "image_repository" { value = "${var.region}-docker.pkg.dev/${var.project_id}/${google_artifact_registry_repository.runtime.repository_id}/server" }
output "secret_refs" { value = { for name, secret in google_secret_manager_secret.managed : name => "${secret.id}/versions/latest" } }
