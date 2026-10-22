from copy import deepcopy

import pytest

from analytics import calculate_efficiency


def test_efficiency_empty_shape(stats_factory):
    assert calculate_efficiency(stats_factory()) == {
        'attack_eff': None,
        'reception_pos': None,
        'serve_ace_pct': None,
        'serve_err_pct': None,
        'set_pos': None,
        'block_kills': 0,
    }


def test_efficiency_mixed_anchor(stats_factory):
    stats = stats_factory('A# A# A- A+ R# R+ R! S# S- S+ S! E# E! B# B+')
    before = deepcopy(stats)
    actual = calculate_efficiency(stats)
    assert actual == pytest.approx(
        {
            'attack_eff': 1 / 4,
            'reception_pos': 2 / 3,
            'serve_ace_pct': 1 / 4,
            'serve_err_pct': 1 / 4,
            'set_pos': 1 / 2,
            'block_kills': 1,
        }
    )
    assert type(actual['block_kills']) is int
    assert stats == before


@pytest.mark.parametrize(
    'touches,expected',
    [
        ('A-', -1.0),
        ('A# A-', 0.0),
        ('A+', 0.0),
        ('A#', 1.0),
    ],
)
def test_attack_efficiency_negative_zero_positive(stats_factory, touches, expected):
    assert calculate_efficiency(stats_factory(touches))['attack_eff'] == pytest.approx(expected)


def test_measured_zero_is_not_missing(stats_factory):
    assert calculate_efficiency(stats_factory('A+ R- E! S+ B+')) == {
        'attack_eff': 0.0,
        'reception_pos': 0.0,
        'serve_ace_pct': 0.0,
        'serve_err_pct': 0.0,
        'set_pos': 0.0,
        'block_kills': 0,
    }


@pytest.mark.parametrize(
    'touches,ace,error', [('S#', 1.0, 0.0), ('S-', 0.0, 1.0), ('S# S# S-', 2 / 3, 1 / 3)]
)
def test_serve_ace_and_error_have_separate_numerators(stats_factory, touches, ace, error):
    result = calculate_efficiency(stats_factory(touches))
    assert result['serve_ace_pct'] == pytest.approx(ace)
    assert result['serve_err_pct'] == pytest.approx(error)
    assert result['attack_eff'] is None
    assert result['reception_pos'] is None
    assert result['set_pos'] is None
