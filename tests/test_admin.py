import hashlib
import importlib.util
import json
import subprocess
import sys
from pathlib import Path

import pytest
import yaml

from g_utils_mcp import policy as pol
from g_utils_mcp.app import KNOWN

spec = importlib.util.spec_from_file_location("admin", "scripts/admin.py")
assert spec and spec.loader
admin = importlib.util.module_from_spec(spec)
spec.loader.exec_module(admin)
DIGEST = hashlib.sha256(b"claude-cloud." + b"x" * 43).hexdigest()


def v1() -> dict:
    data = yaml.safe_load(Path("tests/policy_v1.yml").read_text())
    for account in data["accounts"].values():
        account["enabled"], account["google_subject"] = True, "123"
    return data


def fake_read(ref: str) -> bytes:
    if "digest" in ref:
        return DIGEST.encode() + b"\n"
    if "client-secret" in ref:
        return b"client-secret-value"
    return json.dumps({"refresh_token": "r", "account_alias": "mailbox"}).encode()


def test_migration_keeps_effective_permissions():
    old = v1()
    new, notes = admin.migrate_policy(old, fake_read)
    pol.parse(admin.dump(new), KNOWN)
    assert new["principals"] == {"claude-cloud": {"token_sha256": [DIGEST]}}
    mailbox = new["grants"]["claude-cloud"]["mailbox"]
    assert "gmail_users_messages_list" in mailbox["allow"]
    assert {"gmail_draft_compose", "gmail_attachment_download"} <= set(mailbox["allow"])
    assert "gmail_users_messages_send" in mailbox["deny"]
    drive = new["grants"]["claude-cloud"]["drive-agent"]
    assert {"drive_upload", "drive_download", "drive_files_export"} <= set(drive["allow"])
    # Every effective v1 method is still effective in v2, and nothing denied became allowed.
    for account, grant in old["contexts"]["private"]["grants"]["claude-cloud"].items():
        caller = pol.Caller("claude-cloud", new, 1)
        for method in set(grant["allow"]) - set(grant["deny"]):
            pol.check(caller, account, pol.tool_name(method))
        for method in grant["deny"]:
            assert not pol.allowed(new, "claude-cloud", account, pol.tool_name(method))


def test_migration_skips_disabled_accounts_and_principals():
    old = v1()
    old["accounts"]["mailbox"]["enabled"] = False
    old["principals"]["claude-cloud"]["enabled"] = False
    new, notes = admin.migrate_policy(old, fake_read)
    assert new["principals"] == {} and new["grants"] == {} and "mailbox" not in new["accounts"]
    assert any("disabled" in n for n in notes)


def test_migrated_secret_is_authorized_user_json_and_keeps_v1_keys():
    payload = json.loads(admin.migrate_secret(v1(), "mailbox", fake_read))
    assert payload["account"] == "mailbox" and payload["account_alias"] == "mailbox"
    assert payload["client_secret"] == "client-secret-value" and payload["refresh_token"] == "r"


def test_token_new_writes_private_file_and_digest(tmp_path):
    policy_file = tmp_path / "policy.yml"
    policy_file.write_bytes(Path("examples/policy.deny-all.yml").read_bytes())
    out = tmp_path / "token"
    admin.token_new("agent", policy_file, out)
    token = out.read_bytes()
    assert oct(out.stat().st_mode & 0o777) == "0o600"
    digest = hashlib.sha256(token).hexdigest()
    assert admin.load(policy_file)["principals"]["agent"]["token_sha256"] == [digest]
    with pytest.raises(FileExistsError):
        admin.token_new("agent", policy_file, out)


def test_admin_entrypoint_runs_offline():
    for args in (["--help"], ["policy", "validate", "examples/policy.example.yml"]):
        result = subprocess.run(
            [sys.executable, "scripts/admin.py", *args], capture_output=True, text=True
        )
        assert result.returncode == 0, result.stdout + result.stderr
