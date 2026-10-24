import io

from googleapiclient.http import MediaIoBaseDownload

from ..errors import AppError


class BoundedBuffer(io.BytesIO):
    def __init__(self, limit: int):
        super().__init__()
        self.limit = limit

    def write(self, data):
        if self.tell() + len(data) > self.limit:
            raise AppError("too_large", "File exceeds transfer limit", 413)
        return super().write(data)


def download(request, limit: int) -> bytes:
    buffer = BoundedBuffer(limit)
    downloader = MediaIoBaseDownload(buffer, request, chunksize=256 * 1024)
    done = False
    while not done:
        _, done = downloader.next_chunk(num_retries=0)
    return buffer.getvalue()
