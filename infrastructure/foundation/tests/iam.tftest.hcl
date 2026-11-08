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
    condition     = google_storage_bucket.policy.public_access_prevention == "enforced" && google_storage_bucket.temporary.public_access_prevention == "enforced"
    error_message = "Policy and temporary buckets must prevent public access."
  }
  assert {
    condition     = google_storage_bucket_iam_member.temporary_writer.role == "roles/storage.objectCreator" && google_storage_bucket_iam_member.temporary_reader.role == "roles/storage.objectViewer"
    error_message = "Runtime may create and read temporary files, never delete or overwrite them."
  }
}
