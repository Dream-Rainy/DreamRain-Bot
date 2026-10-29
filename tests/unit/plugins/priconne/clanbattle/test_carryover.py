import pytest


@pytest.fixture
def carryover(app):
    from src.plugins.priconne.clanbattle import carryover
    return carryover


def hit(log, *, start=90, killed=False, manual=None, seconds=None, unit=None, owner=1):
    meta = {}
    if manual is not None:
        meta['manual_flag'] = manual
    if unit is not None:
        meta['unit_owners'] = [dict(unit_id=unit, viewer_id=owner)]
        meta['owners_complete'] = owner is not None
    return dict(pcrid=1, battle_log_id=log, remain_time=start, killed=killed,
                tail_seconds=seconds, settlement=meta)


def test_full_carry_is_not_assigned_to_the_next_ninety_second_attack(carryover):
    result = carryover.analyse_day([hit(1, killed=True, manual=1, seconds=90), hit(2)], complete=True)
    assert result['records'][1]['flag'] is None
    assert result['inventory']['seconds'] == {90: (0, 1)}
    assert result['inventory']['total'] == (0, 1)


def test_parked_carry_can_be_used_after_another_full_attack_and_kill_early(carryover):
    records = [hit(1, killed=True, manual=1, seconds=90, unit=101), hit(2, unit=102),
               hit(3, killed=True, seconds=90, unit=101)]
    result = carryover.analyse_day(records, complete=True)
    assert [r['flag'] for r in result['records']] == [1, 0, .5]
    assert result['records'][2]['carry_source'] == 1
    assert result['records'][2]['extended_seconds'] == 0
    assert result['inventory']['total'] == (0, 0)


def test_borrowed_character_reuse_does_not_force_compensation(carryover):
    result = carryover.analyse_day([hit(1, unit=101, owner=2), hit(2, unit=101, owner=2)], complete=True)
    assert [r['flag'] for r in result['records']] == [0, 0]
    assert result['inventory']['total'] == (0, 0)
    conflict = carryover.analyse_day([hit(1, unit=101), hit(2, unit=101)], complete=True)
    assert conflict['inventory']['status'] == 'conflict'


def test_multiple_sources_do_not_hide_a_certain_remaining_quantity(carryover):
    records = [hit(1, killed=True, manual=1, seconds=90),
               hit(2, killed=True, manual=1, seconds=90), hit(3, manual=.5)]
    result = carryover.analyse_day(records, complete=True)
    assert result['records'][2]['flag'] == .5
    assert result['records'][2]['carry_source'] is None
    assert result['records'][2]['carry_sources'] == (1, 2)
    assert result['inventory']['seconds'] == {90: (1, 1)}
    assert result['inventory']['total'] == (1, 1)


def test_mutually_exclusive_lengths_do_not_add_up_to_two_carries(carryover):
    records = [hit(1, killed=True, manual=1, seconds=90), hit(2, manual=0),
               hit(3, killed=True, seconds=28), hit(4, killed=True, seconds=90)]
    result = carryover.analyse_day(records, complete=True)
    assert result['inventory']['seconds'] == {90: (0, 1), 28: (0, 1)}
    assert result['inventory']['total'] == (1, 1)


def test_unknown_length_is_not_zero_and_partial_ownership_does_not_reject_it(carryover):
    first = hit(1, killed=True, manual=1, unit=101, owner=None)
    remaining = carryover.analyse_day([first], complete=True)
    assert remaining['inventory']['seconds'] == {None: (1, 1)}
    assert remaining['records'][0]['extended_seconds'] is None
    consumed = carryover.analyse_day([first, hit(2, start=28, killed=True, unit=101)], complete=True)
    assert consumed['records'][1]['flag'] == .5
    assert consumed['records'][1]['extended_seconds'] == 0
    assert consumed['inventory']['total'] == (0, 0)


@pytest.mark.parametrize('ordered', [True, False])
def test_missing_coverage_or_order_does_not_produce_an_empty_balance(carryover, ordered):
    result = carryover.analyse_day([hit(1), hit(2, start=28)], complete=False, ordered=ordered)
    assert result['records'][0]['flag'] is None
    assert result['records'][1]['flag'] == .5
    assert result['inventory']['status'] != 'ok' and result['inventory']['total'] is None


def test_conflicting_manual_records_remain_manual_but_inventory_is_unknown(carryover):
    result = carryover.analyse_day([hit(i, manual=0) for i in range(4)], complete=True)
    assert all(r['flag'] == 0 and r['kind_status'] == 'manual' for r in result['records'])
    assert result['inventory']['status'] == 'conflict' and result['inventory']['total'] is None
