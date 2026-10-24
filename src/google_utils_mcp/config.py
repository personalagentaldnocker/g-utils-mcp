from typing import Self
from urllib.parse import urlsplit

from pydantic import Field, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="", extra="ignore")
    google_cloud_project: str = ""
    policy_uri: str = ""
    temp_bucket: str = ""
    public_base_url: str = ""
    allowed_secret_projects: list[str] = Field(default_factory=list)
    port: int = 8080
    max_transfer_bytes: int = Field(default=20_000_000, ge=1, le=25_000_000)
    max_result_bytes: int = Field(default=1_000_000, ge=1024, le=5_000_000)
    artifact_ttl_seconds: int = Field(default=1800, ge=60, le=3600)

    @model_validator(mode="after")
    def check_urls(self) -> Self:
        if self.policy_uri and not self.policy_uri.startswith("gs://"):
            raise ValueError("POLICY_URI must be gs://bucket/object")
        if self.public_base_url:
            url = urlsplit(self.public_base_url)
            if url.scheme != "https" or not url.hostname or url.path not in ("", "/"):
                raise ValueError("PUBLIC_BASE_URL must be an HTTPS origin")
            self.public_base_url = self.public_base_url.rstrip("/")
        return self

    def require_cloud(self) -> None:
        if not all((self.policy_uri, self.temp_bucket, self.public_base_url,
                    self.allowed_secret_projects)):
            raise ValueError("Set POLICY_URI, TEMP_BUCKET, PUBLIC_BASE_URL, ALLOWED_SECRET_PROJECTS")
