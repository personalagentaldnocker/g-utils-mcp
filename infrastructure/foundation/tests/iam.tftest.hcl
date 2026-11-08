mock_provider "google" {}
variables {
  project_id               = "unit-test-project"
  refresh_token_secrets    = ["test-refresh"]
  principal_digest_secrets = ["test-digest"]
}
run "least_privilege_plan" {
  command = plan
  assert {
    condition     = google_storage_bucket_iam_member.policy_reader.role == "roles/storage.objectViewer"
    error_message = "Runtime must have read-only access to the policy bucket."
  }
  assert {
    condition     = length(google_secret_manager_secret_iam_member.reader) == 1 && contains(keys(google_secret_manager_secret_iam_member.reader), "test-refresh")
    error_message = "The runtime may read account token secrets only, not digest or OAuth client secrets."
  }
  assert {
    condition     = alltrue([for m in google_secret_manager_secret_iam_member.reader : m.role == "roles/secretmanager.secretAccessor"])
    error_message = "The runtime must not add secret versions."
  }
  assert {
    condition     = google_storage_bucket.policy.public_access_prevention == "enforced" && google_storage_bucket.temporary.public_access_prevention == "enforced"
    error_message = "Policy and artifact buckets must prevent public access."
  }
}
