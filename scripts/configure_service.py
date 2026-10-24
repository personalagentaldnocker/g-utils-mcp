"""Create non-secret service tfvars from the applied foundation outputs."""

import argparse
import json
import os
import subprocess
from pathlib import Path

from admin_common import protected_write


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--image", required=True)
    parser.add_argument("--public-base-url", default="")
    args = parser.parse_args()
    outputs = json.loads(
        subprocess.check_output(
            ["terraform", "-chdir=infrastructure/foundation", "output", "-json"], text=True
        )
    )
    values = {
        "project_id": os.environ["GCP_PROJECT_ID"],
        "region": os.environ.get("GCP_REGION", "europe-west3"),
        "image": args.image,
        "public_base_url": args.public_base_url,
        **{
            key: outputs[key]["value"]
            for key in ("runtime_service_account", "policy_uri", "temporary_bucket")
        },
    }
    path = Path("infrastructure/service/terraform.tfvars.json")
    protected_write(path, json.dumps(values, indent=2).encode(), replace=True)
    print("Non-secret service inputs saved. Review terraform plan before applying.")


if __name__ == "__main__":
    main()
