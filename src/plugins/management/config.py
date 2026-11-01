from pydantic import BaseModel


class Config(BaseModel):
    management_web_enabled: bool = False
    management_web_relay_url: str = ""
    management_web_relay_token: str = ""
