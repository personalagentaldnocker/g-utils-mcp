mock_provider "google" {}
variables {
  project_id = "unit-test-project"
}
run "least_privilege_plan" {
  command = plan
  assert {
    condition     = google_storage_bucket_iam_member.policy_reader.role == "roles/storage.objectViewer"
    error_message = "Runtime must have read-only access to the policy bucket."
  }
  assert {
    condition     = google_secret_manager_secret_iam_member.runtime_reader.role == "roles/secretmanager.secretAccessor"
    error_message = "Runtime may only read the secret, never add versions."
  }
  assert {
    condition     = google_storage_bucket.policy.public_access_prevention == "enforced"
    error_message = "The policy bucket must prevent public access."
  }
}
