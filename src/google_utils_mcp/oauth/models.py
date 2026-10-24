from typing import Literal

from pydantic import Field

from ..policy.models import StrictModel


class EnrollmentIntent(StrictModel):
    account: str
    service: Literal["gmail", "drive"]
    expected_email: str
    oauth_client: str
    target_secret: str
    scopes: list[str] = Field(min_length=1)
    expires: float
