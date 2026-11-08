# Copy to terraform.tfvars and fill in once; no script writes this file.
# Values: terraform -chdir=infrastructure/foundation output
# The image is passed by scripts/deploy.sh from local/image-digest.
project_id              = "your-project-id"
region                  = "europe-west3"
runtime_service_account = "g-utils-mcp@your-project-id.iam.gserviceaccount.com"
policy_uri              = "gs://your-project-id-g-utils-mcp-policy/policies/g-utils-mcp.yml"
secret_name             = "projects/your-project-id/secrets/g-utils-mcp"
temporary_bucket        = "your-project-id-g-utils-mcp-temporary"
