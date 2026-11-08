"""Drive and Docs tools. Everything not listed here goes through the generic dispatcher."""

import io

from googleapiclient.http import MediaIoBaseUpload

from . import policy, utils
from .policy import Caller
from .utils import AppError

METHODS = [
    "drive.files.list",
    "drive.files.get",
    "drive.files.create",
    "drive.files.update",
    "docs.documents.get",
    "docs.documents.create",
    "docs.documents.batchUpdate",
]
# Grantable but not exposed as its own tool: drive_download needs it for Google-native files.
PERMISSIONS = {"drive_files_export"}
GOOGLE_NATIVE = "application/vnd.google-apps."


def upload(caller: Caller, account: str, params: dict) -> dict:
    """Upload a temporary file to a new Drive file, or as new content of an existing one."""
    tool = "drive_upload"
    policy.check(caller, account, tool)
    meta, data = policy.get_file(caller, params["file_ref"], tool)
    method = "drive.files.update" if params.get("file_id") else "drive.files.create"
    args: dict = {
        "body": params.get("metadata", {"name": meta["filename"]}),
        "fields": "id,name,mimeType,version",
        "supportsAllDrives": True,
    }
    if params.get("file_id"):
        args["fileId"] = params["file_id"]
    media = MediaIoBaseUpload(
        io.BytesIO(data), mimetype=meta["mime_type"], chunksize=256 * 1024, resumable=True
    )
    return policy.run(caller, account, method, args, media=media)


def download(caller: Caller, account: str, params: dict) -> dict:
    """Save a Drive file (following shortcuts) or a Google Doc export as a temporary file."""
    tool = "drive_download"
    policy.check(caller, account, tool)
    file_id, seen = params["file_id"], set()
    fields = "id,name,mimeType,shortcutDetails"
    for _ in range(8):
        if file_id in seen:
            raise AppError("invalid_input", "Drive shortcut cycle", 400)
        seen.add(file_id)
        args = {"fileId": file_id, "fields": fields, "supportsAllDrives": True}
        meta = policy.run(caller, account, "drive.files.get", args)
        if meta["mimeType"] != GOOGLE_NATIVE + "shortcut":
            break
        file_id = meta["shortcutDetails"]["targetId"]
    else:
        raise AppError("invalid_input", "Drive shortcut chain is too deep", 400)
    if meta["mimeType"] == GOOGLE_NATIVE + "folder":
        raise AppError("invalid_input", "List a folder rather than downloading it", 400)
    if meta["mimeType"].startswith(GOOGLE_NATIVE):
        mime = params.get("export_mime_type", "application/pdf")
        method, args = "drive.files.export", {"fileId": file_id, "mimeType": mime}
    else:
        mime = meta["mimeType"]
        method, args = "drive.files.get", {"fileId": file_id, "supportsAllDrives": True}
    data = policy.run(caller, account, method, args, download=True)
    requires = (tool, "drive_files_get", policy.tool_name(method))
    return utils.put_file(caller.principal, account, data, meta["name"], mime, tool, requires)


UPLOAD_METADATA = {
    "type": "object",
    "properties": {
        "name": {"type": "string"},
        "description": {"type": "string"},
        "mimeType": {"type": "string"},
        "parents": {"type": "array", "items": {"type": "string"}},
    },
    "additionalProperties": False,
}

# name -> (description, params properties, required params, function)
HELPERS = {
    "drive_upload": (
        "Upload a temporary file_ref to a new Drive file, or to file_id as new content.",
        {
            "file_ref": {"type": "string"},
            "file_id": {"type": "string"},
            "metadata": UPLOAD_METADATA,
        },
        ["file_ref"],
        upload,
    ),
    "drive_download": (
        "Save a Drive file, or an export of a Google Doc/Sheet/Slides, as a temporary file_ref.",
        {"file_id": {"type": "string"}, "export_mime_type": {"type": "string"}},
        ["file_id"],
        download,
    ),
}
