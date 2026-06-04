"""Compatibility exports for game-domain adapters.

New code should import from ``src.plugins.chiffon_bot.shared.game``.
"""

from .game.adapter import DomainAdapter
from .game.registry import get_domain_adapter

__all__ = ["DomainAdapter", "get_domain_adapter"]
