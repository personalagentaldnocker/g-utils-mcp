import subprocess
import sys


def test_offline_admin_entrypoints():
    commands = [
        ["scripts/gcs_policy.py", "validate", "--file", "examples/policy.deny-all.yml"],
        ["scripts/doctor.py", "--local"],
        *[
            ["scripts/" + name + ".py", "--help"]
            for name in ("auth", "accounts", "clients", "secret_cli", "gcs_policy")
        ],
    ]
    for command in commands:
        result = subprocess.run([sys.executable, *command], capture_output=True, text=True)
        assert result.returncode == 0, result.stdout + result.stderr
