from __future__ import annotations

from pydantic import BaseModel, field_validator


class Config(BaseModel):
    """autopcr NoneBot adapter config."""

    autopcr_prefix: str = "#"
    autopcr_public_base_url: str = "http://127.0.0.1/daily/"
    autopcr_enable_crons: bool = True

    @field_validator("autopcr_prefix")
    @classmethod
    def _validate_prefix(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("autopcr_prefix cannot be empty")
        return value

    @field_validator("autopcr_public_base_url")
    @classmethod
    def _normalize_public_base_url(cls, value: str) -> str:
        value = value.strip()
        if not value:
            return "http://127.0.0.1/daily/"
        return value.rstrip("/") + "/"
