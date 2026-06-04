"""Game-domain metadata used by app-level command wiring."""

from __future__ import annotations

from dataclasses import dataclass
from re import Match


@dataclass(frozen=True)
class NaturalRandomPattern:
    """A natural-language random-song pattern for one game.

    ``range_group_count`` controls how to convert regex capture groups:
    - 0: no difficulty range
    - 1: group 1 is the range string
    - 2: groups 1 and 2 are joined as ``start-end``
    """

    regex: str
    range_group_count: int = 0

    def extract_range(self, match: Match[str]) -> str | None:
        if self.range_group_count == 0:
            return None
        if self.range_group_count == 1:
            return match.group(1)
        if self.range_group_count == 2:
            return f"{match.group(1)}-{match.group(2)}"
        raise ValueError(f"Unsupported range_group_count={self.range_group_count}")
