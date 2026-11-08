"""Drive and Docs: the generic method list plus file upload and download."""

import io

from ..config import MAX_FILE_BYTES
from ..utils.helpers import AppError, User, file_in, file_out

METHODS = [
    "drive.files.list",
    "drive.files.get",
    "drive.files.create",
    "drive.files.update",
    "docs.documents.get",
    "docs.documents.create",
    "docs.documents.batchUpdate",
]
INTERNAL = ["drive.files.export"]  # grantable, used by drive_download only


def upload(run, params: dict, user: User) -> dict:
    from googleapiclient.http import MediaIoBaseUpload

    data, name, mime_type = file_in(user, params)
    metadata = params.get("metadata", {})
    media = MediaIoBaseUpload(
        io.BytesIO(data), mimetype=metadata.get("mimeType", mime_type), resumable=True
    )
    args = {"fields": "id,name,mimeType,version", "supportsAllDrives": True}
    if params.get("file_id"):
        return run(
            "drive.files.update", {**args, "fileId": params["file_id"], "body": metadata}, media
        )
    body = {"name": name, **metadata}
    return run("drive.files.create", {**args, "body": body}, media)


def download(run, params: dict, user: User) -> dict:
    file_id, seen = params["file_id"], set[str]()
    while True:  # follow shortcuts to their target
        if file_id in seen or len(seen) >= 8:
            raise AppError("invalid_input", "Drive shortcut chain is cyclic or too deep", 400)
        seen.add(file_id)
        meta = run(
            "drive.files.get",
            {
                "fileId": file_id,
                "fields": "id,name,mimeType,size,shortcutDetails",
                "supportsAllDrives": True,
            },
        )
        if meta["mimeType"] != "application/vnd.google-apps.shortcut":
            break
        file_id = meta["shortcutDetails"]["targetId"]
    if meta["mimeType"] == "application/vnd.google-apps.folder":
        raise AppError("invalid_input", "List a folder instead of downloading it", 400)
    if int(meta.get("size", 0)) > MAX_FILE_BYTES:
        raise AppError("too_large", "File exceeds the size limit", 413)
    if meta["mimeType"].startswith("application/vnd.google-apps."):
        mime = params.get("export_mime_type", "application/pdf")
        data = run("drive.files.export", {"fileId": file_id, "mimeType": mime}, media="download")
    else:
        mime = meta["mimeType"]
        data = run("drive.files.get", {"fileId": file_id, "supportsAllDrives": True}, "download")
    if len(data) > MAX_FILE_BYTES:
        raise AppError("too_large", "File exceeds the size limit", 413)
    return file_out(user, data, meta["name"], mime)


TOOLS = {
    "drive_upload": (
        "Upload a file as a new Drive file, or as new content of file_id. Give data_base64 "
        "(up to 5 MB) or a file_ref from POST /files.",
        {
            "data_base64": {"type": "string"},
            "file_ref": {"type": "string"},
            "filename": {"type": "string"},
            "mime_type": {"type": "string"},
            "file_id": {"type": "string"},
            "metadata": {
                "type": "object",
                "properties": {
                    "name": {"type": "string"},
                    "description": {"type": "string"},
                    "mimeType": {"type": "string"},
                    "parents": {"type": "array", "items": {"type": "string"}},
                },
                "additionalProperties": False,
            },
        },
        [],
        ["drive.files.create", "drive.files.update"],
        upload,
    ),
    "drive_download": (
        "Return a Drive file (base64 up to 5 MB, otherwise a file_ref for GET /files/<ref>). "
        "Google Docs/Sheets/Slides are exported, PDF by default.",
        {"file_id": {"type": "string"}, "export_mime_type": {"type": "string"}},
        ["file_id"],
        ["drive.files.get"],
        download,
    ),
}
