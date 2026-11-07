# Refactor
people using this will create their own gcp project. they will sign in from their computer after setting up their gcp project. the sign in is triggered by a script. that script then deposits the credentials in gcp's secret manager. 
i prefer function-based programming before OOP. classes only if they are significantly better for the job at hand. also: less is more 

## Setup
one command script. i think it is not possible to set up oauth via api. if i am wrong then we do that automatically as well. if not the steps go into the reqdme and the user has to do it manually.
this will populate an .env file as it goes with the outputs from the steps.
contents:
1. foundation: if a new project neesd to be created, use gcloud to do that. ask the user for the projects name, etc. set up tf gcs bucket, initialize terraform. with option to skip project creation ie user can select between existing and new gcp project. user is expected to know gcloud cli so they are just asked if the enabled config is the one they want to use. 
2. terraform: enable required services. import gcs bucket. create runtime sa. that needs secret access scoped to the secret (only one, see below in function, i want to have only one per policy) that contains the credentials. possibly create secret. i am unsure if tf should manage the cloud run endpoint. it feels unnecessary, as we're building that with the deploy script using gcloud run deploy for simplicity. 
this also deploys the cloud run instance and writes the outputs in the .env. possibly keep the mcp token in the secret. the setup.py or something should have a function that extracts the mcp token from the secret and the mcp url for easier setup for the agent of choice. 
3. login: the setup for the user. a script that logs in the services atm only gmail and drive for the accounts the user specified. then manifests all relevant info in the secret. 

## Function
there should only be one secret value containing all the secrets for a given policy. a policy is the file in gcs that contains the user's allowed methods, utils and accounts that are allowed to use everything respectively. 
files i think make sense, open for debate:
src/app.py
- main: contains the logic. 
- healthz enpdoint
- mcp endpoint: the mcp server
src/utils/auth.py
- manages the access token retrieval from the secret
- compares the allowed methods against the policy
src/utils/helpers.py
- gcs api for the policiy upload and retrieval
- secret manager api for the actions required, setting and retrieval
src/services/gmail.py (if that works in terms of name conflict with the gmail api)
- wrapper around python api client commands into mcp cli commands
src/services/drive.py (same as above)
- wrapper around python api client commands into mcp cli commands
honorable mentions: config.py: whatever should be manifested but shold not go into the function's emvorpm,emt, mcp-whatever-is-necessary: probably mcp servers should have a file and functions dedicated to it.
## Decisions (agreed)
- Terraform stays (teardown with `terraform destroy`). It also owns Cloud Run, so nothing is left behind.
- Sign-in runs on the operator's laptop with a **Desktop app** OAuth client (`InstalledAppFlow`). No sign-in routes on the server, no callback URL, no `PUBLIC_BASE_URL`, one deploy.
- The OAuth consent screen must be **In production**; in Testing, refresh tokens expire after 7 days.
- Wrong-account protection: login compares the signed-in email with `expected_email` from the policy and refuses to store a mismatching token.
- Policy stays in GCS (a frontend can edit it later without Secret Manager access). Existing format, minus the fields made obsolete by the single secret (`owners`, `oauth_clients`, `*_secret_ref(s)`, `google_subject`).
- Policy freshness: every request checks the object's generation (metadata only) and re-downloads only when it changed.
- One agent (principal) for now; the format allows more.
- One secret holds everything: OAuth client id/secret, one refresh token per account, the MCP token(s). Runtime reads it, never writes it.
- Files go through the conversation as base64 (cap 5 MB per file). The temporary bucket and the artifact endpoints are gone. Google page tokens are passed through unchanged.
- Package stays `src/g_utils_mcp/` (imports and the `g-utils-mcp` command work in the container, on the laptop and in tests).
- Generic tools come from a method list in gmail.py / drive.py; only drafts with attachments, attachment download and Drive upload/download are hand-written.
- Tests kept: policy filter, MCP authentication, tool calls against a fake Google client.
- No migration: the current deployment may break; the policy and secret are recreated.
- Admin commands (login, token, policy) live in `scripts/admin.py`, outside the runtime image.

## Status
- [x] Code refactor (src, tests, admin script)
- [x] Terraform: single secret, no temporary bucket, image passed to deploy without overwriting tfvars, apply asks first
- [ ] One-command setup script (next step)
