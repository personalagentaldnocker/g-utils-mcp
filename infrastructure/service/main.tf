variable "project_id" { type = string }
variable "region" {
  type    = string
  default = "europe-west3"
}
variable "name" {
  type    = string
  default = "g-utils-mcp"
}
variable "runtime_service_account" { type = string }
variable "image" {
  type = string
  validation {
    condition     = can(regex("@sha256:[0-9a-f]{64}$", var.image))
    error_message = "Use an immutable image digest, not a tag."
  }
}
variable "policy_uri" { type = string }
variable "secret_name" { type = string }
variable "temporary_bucket" { type = string }
variable "max_instances" {
  type    = number
  default = 3
}

resource "google_cloud_run_v2_service" "runtime" {
  name                = var.name
  location            = var.region
  ingress             = "INGRESS_TRAFFIC_ALL"
  deletion_protection = false # teardown is `terraform destroy`
  scaling {
    min_instance_count = 0
    max_instance_count = var.max_instances
  }
  template {
    service_account                  = var.runtime_service_account
    timeout                          = "120s"
    max_instance_request_concurrency = 2
    scaling {
      min_instance_count = 0
      max_instance_count = var.max_instances
    }
    containers {
      image = var.image
      ports { container_port = 8080 }
      resources {
        limits = { cpu = "1", memory = "512Mi" }
      }
      env {
        name  = "POLICY_URI"
        value = var.policy_uri
      }
      env {
        name  = "SECRET_NAME"
        value = var.secret_name
      }
      env {
        name  = "TEMP_BUCKET"
        value = var.temporary_bucket
      }
      startup_probe {
        http_get { path = "/health" }
        period_seconds    = 3
        failure_threshold = 20
      }
    }
  }
}

resource "google_cloud_run_v2_service_iam_member" "public_transport" {
  project  = var.project_id
  location = var.region
  name     = google_cloud_run_v2_service.runtime.name
  role     = "roles/run.invoker"
  member   = "allUsers"
}

output "service_url" { value = google_cloud_run_v2_service.runtime.uri }
