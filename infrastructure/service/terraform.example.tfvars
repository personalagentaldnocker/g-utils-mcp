project_id              = "your-project-id"
runtime_service_account = "google-utils-mcp@your-project-id.iam.gserviceaccount.com"
policy_uri              = "gs://your-project-id-google-utils-mcp-policy/policies/google-utils-mcp.yml"
temporary_bucket        = "your-project-id-google-utils-mcp-temporary"
image                   = "europe-west3-docker.pkg.dev/your-project-id/google-utils-mcp/server@sha256:REPLACE_WITH_64_HEX_DIGEST"
# First apply may leave public_base_url empty. Then use the actual service_url output.
public_base_url = ""
