mock_provider "google" {}
variables {
  project_id              = "unit-test-project"
  runtime_service_account = "runtime@unit-test-project.iam.gserviceaccount.com"
  policy_uri              = "gs://unit-policy/policy.yml"
  secret_name             = "projects/unit-test-project/secrets/g-utils-mcp"
  temporary_bucket        = "unit-test-project-g-utils-mcp-temporary"
  image                   = "europe-west3-docker.pkg.dev/unit-test-project/mcp/server@sha256:0000000000000000000000000000000000000000000000000000000000000000"
}
run "public_transport_private_application" {
  command = plan
  assert {
    condition     = google_cloud_run_v2_service_iam_member.public_transport.role == "roles/run.invoker" && google_cloud_run_v2_service_iam_member.public_transport.member == "allUsers"
    error_message = "Claude must reach transport without Google IAM authentication. Application authentication remains mandatory."
  }
  assert {
    condition     = google_cloud_run_v2_service.runtime.template[0].service_account == var.runtime_service_account
    error_message = "Runtime must use the dedicated identity."
  }
}
