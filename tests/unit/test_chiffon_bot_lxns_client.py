from __future__ import annotations


def test_lxns_client_wires_single_data_client(loaded_chiffon_bot):
    from src.plugins.chiffon_bot.integrations.lxns.client import lxns_client

    assert lxns_client.data.auth.lxns_oauth is lxns_client.oauth
    assert lxns_client.data.accounts is lxns_client.accounts
    assert lxns_client.catalog.songs is lxns_client.songs


def test_lxns_client_exposes_player_service(loaded_chiffon_bot):
    from src.plugins.chiffon_bot.integrations.lxns.client import lxns_client

    assert lxns_client.data.players.maimai.service is lxns_client.data.players

