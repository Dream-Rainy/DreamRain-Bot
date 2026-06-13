"""Context objects for external data fetching.

The data package does not keep global bot state. Callers pass a context to
catalog/client entry points so HTTP, config, and logging stay injectable.
"""

from __future__ import annotations

import logging
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from typing import Any

HttpGetJson = Callable[..., Awaitable[Any]]


@dataclass
class CatalogContext:
    http_get_json: HttpGetJson
    ingame_data_base_dir: str = ""
    headers: dict[str, str] = field(default_factory=dict)
    logger: Any = field(default_factory=lambda: logging.getLogger(__name__))

    async def get_json(self, url: str, **kwargs: Any) -> Any:
        return await self.http_get_json(url, **kwargs)

    def ingame_path(self, game: str, sub_dir: str) -> str:
        return f"{self.ingame_data_base_dir}/{game}/{sub_dir}"

__all__ = ["CatalogContext", "HttpGetJson"]
