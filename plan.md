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