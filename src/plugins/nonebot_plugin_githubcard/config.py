import nonebot
from pydantic import BaseModel


class Config(BaseModel, extra='allow'):
    github_token : str | None = None
    github_type: int | None = 0
    

global_config = nonebot.get_driver().config
githubcard_config = Config(**global_config.model_dump())