project_id              = "your-project-id"
runtime_service_account = "g-utils-mcp@your-project-id.iam.gserviceaccount.com"
policy_uri              = "gs://your-project-id-g-utils-mcp-policy/policies/g-utils-mcp.yml"
temporary_bucket        = "your-project-id-g-utils-mcp-temporary"
image                   = "europe-west3-docker.pkg.dev/your-project-id/g-utils-mcp/server@sha256:REPLACE_WITH_64_HEX_DIGEST"
# First apply may leave public_base_url empty. Then use the actual service_url output.
public_base_url = ""
