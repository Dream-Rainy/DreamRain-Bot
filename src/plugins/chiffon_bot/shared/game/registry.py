"""Registry for game-domain adapters."""

from __future__ import annotations

from .adapter import DomainAdapter, SongQueryAdapter

_adapters: dict[str, SongQueryAdapter] = {}


def _normalize_game_code(game_code: str) -> str:
    return str(game_code).strip().lower()


def register_game_adapter(game_code: str, adapter: SongQueryAdapter) -> None:
    """Register or replace a game adapter."""

    _adapters[_normalize_game_code(game_code)] = adapter


def get_game_adapter(game_code: str) -> SongQueryAdapter:
    """Return a registered query adapter."""

    gc = _normalize_game_code(game_code)
    adapter = _adapters.get(gc)
    if adapter is None:
        available = ", ".join(sorted(_adapters.keys())) or "-"
        raise KeyError(f"No song_query adapter for game_code={gc!r}. available={available}")
    return adapter


def get_domain_adapter(game_code: str) -> DomainAdapter:
    """Return a registered full domain adapter."""

    adapter = get_game_adapter(game_code)
    if not isinstance(adapter, DomainAdapter):
        raise TypeError(
            f"Adapter for {game_code!r} is not a DomainAdapter "
            f"(got {type(adapter).__name__})"
        )
    return adapter


def iter_game_adapters() -> tuple[SongQueryAdapter, ...]:
    """Return all registered query adapters in registration order."""

    return tuple(_adapters.values())


def iter_domain_adapters() -> tuple[DomainAdapter, ...]:
    """Return all registered full domain adapters in registration order."""

    adapters: list[DomainAdapter] = []
    for adapter in _adapters.values():
        if isinstance(adapter, DomainAdapter):
            adapters.append(adapter)
    return tuple(adapters)


def iter_searchable_adapters() -> tuple[DomainAdapter, ...]:
    """Return domain adapters that participate in cross-game natural search."""

    return tuple(
        adapter
        for adapter in iter_domain_adapters()
        if adapter.enable_cross_game_search
    )


def invalidate_adapters() -> None:
    """Clear registered adapters. Intended for tests and hot reload only."""

    _adapters.clear()
