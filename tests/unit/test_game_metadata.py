from __future__ import annotations

from pathlib import Path


def test_game_metadata_registered_on_domain_adapters(loaded_chiffon_bot):
    from src.plugins.chiffon_bot.shared.game import iter_searchable_adapters

    adapters = iter_searchable_adapters()
    codes = {adapter.game_code for adapter in adapters}

    assert codes == {"maimai", "chunithm"}
    for adapter in adapters:
        assert adapter.command_prefix
        assert adapter.display_name
        assert adapter.select_aliases
        assert adapter.natural_random_patterns


def test_resolve_adapter_choice_by_index_and_alias(loaded_chiffon_bot):
    from src.plugins.chiffon_bot.app.commands.natural_language import (
        _SearchHit,
        _resolve_adapter_choice,
    )
    from src.plugins.chiffon_bot.shared.game import get_domain_adapter
    from src.plugins.chiffon_bot.shared.search.song_query import (
        MatchType,
        SongQueryResult,
    )
    from src.plugins.chiffon_bot.shared.song_data import SongData

    mai = get_domain_adapter("maimai")
    chuni = get_domain_adapter("chunithm")
    result = SongQueryResult(
        song_id=1,
        title="Song",
        match_type=MatchType.EXACT_TITLE,
        match_score=100.0,
        matched_text="Song",
        song_data=SongData(id=1, title="Song"),
    )
    hits = [
        _SearchHit(adapter=mai, results=[result], priority=1),
        _SearchHit(adapter=chuni, results=[result], priority=1),
    ]

    assert _resolve_adapter_choice("1", hits) is hits[0]
    assert _resolve_adapter_choice("2", hits) is hits[1]
    assert _resolve_adapter_choice("mai", hits) is hits[0]
    assert _resolve_adapter_choice("舞萌", hits) is hits[0]
    assert _resolve_adapter_choice("CHUNI", hits) is hits[1]
    assert _resolve_adapter_choice("中二", hits) is hits[1]
    assert _resolve_adapter_choice("3", hits) is None
    assert _resolve_adapter_choice("unknown", hits) is None


def test_natural_language_command_does_not_import_specific_game_adapters():
    source = Path("src/plugins/chiffon_bot/app/commands/natural_language.py").read_text(
        encoding="utf-8"
    )

    assert "domains.maimai" not in source
    assert "domains.chunithm" not in source
    assert 'game_code="maimai"' not in source
    assert 'game_code="chunithm"' not in source
