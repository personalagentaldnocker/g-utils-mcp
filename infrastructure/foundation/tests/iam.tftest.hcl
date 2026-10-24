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
    condition     = length(google_secret_manager_secret_iam_member.token_writer) == 1 && contains(keys(google_secret_manager_secret_iam_member.token_writer), "test-refresh")
    error_message = "Only account refresh-token secrets permit new runtime versions."
  }
  assert {
    condition     = google_storage_bucket.policy.public_access_prevention == "enforced" && google_storage_bucket.temporary.public_access_prevention == "enforced"
    error_message = "Policy and artifact buckets must prevent public access."
  }
}
