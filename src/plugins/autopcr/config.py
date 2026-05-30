from __future__ import annotations

from pydantic import BaseModel, field_validator


class Config(BaseModel):
    """autopcr NoneBot adapter config."""

    autopcr_prefix: str = "#"
    autopcr_api_base_url: str = "http://127.0.0.1/daily/api/"
    autopcr_public_base_url: str = "http://127.0.0.1/daily/"
    autopcr_bot_token: str = ""
    autopcr_request_timeout: float = 300.0
    autopcr_startup_healthcheck: bool = False
    autopcr_enable_crons: bool = False

    @field_validator("autopcr_prefix")
    @classmethod
    def _validate_prefix(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("autopcr_prefix cannot be empty")
        return value

    @field_validator("autopcr_api_base_url")
    @classmethod
    def _normalize_api_base_url(cls, value: str) -> str:
        value = value.strip()
        if not value:
            return "http://127.0.0.1/daily/api/"
        return value.rstrip("/") + "/"

    @field_validator("autopcr_public_base_url")
    @classmethod
    def _normalize_public_base_url(cls, value: str) -> str:
        value = value.strip()
        if not value:
            return "http://127.0.0.1/daily/"
        value = value.rstrip("/")
        if value.endswith("/login"):
            value = value[: -len("/login")]
        return value.rstrip("/") + "/"

    @field_validator("autopcr_request_timeout")
    @classmethod
    def _validate_timeout(cls, value: float) -> float:
        if value <= 0:
            raise ValueError("autopcr_request_timeout must be positive")
        return value
