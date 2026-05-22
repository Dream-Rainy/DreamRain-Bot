"""CHUNITHM 命令注册 — 所有通用命令由工厂自动生成。"""

from __future__ import annotations

from ...domains.chunithm.chunithm_adapter import get_chunithm_adapter
from .game_command_factory import register_game_commands


def register_chunithm_commands(chuni_group):
    register_game_commands(chuni_group, get_chunithm_adapter())
