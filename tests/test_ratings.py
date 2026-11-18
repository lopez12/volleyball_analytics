from copy import deepcopy
from pathlib import Path

import pytest

from analytics import (
    ACTION_NOTA_BASE,
    ACTION_NOTA_GRADE_VALUES,
    ACTION_NOTA_SHRINK,
    ACTION_NOTA_SPAN,
    ACTIONS,
    PLAYER_GRADE_VALUES,
    POSITION_LABELS,
    RATING_CENTER,
    RATING_SHRINK,
    ROLE_ACTION_WEIGHTS,
    TEAM_RATING_RAW_MEAN,
    TEAM_RATING_SCALE,
    WEIGHTS,
    calculate_action_stats,
    calculate_efficiency,
    calculate_player_rating,
    calculate_rating,
    parse_log,
)

OMEGA_LOG = Path(__file__).parents[1] / 'teams/nova/atlas-chapalita-cup-2026/matches/07_omega.txt'


def test_frozen_team_and_action_rating_constants():
    assert RATING_CENTER == 7.0
    assert RATING_SHRINK == 3
    assert TEAM_RATING_RAW_MEAN == 0.114
    assert TEAM_RATING_SCALE == 17.6
    assert ACTION_NOTA_GRADE_VALUES == {'#': 1.0, '+': 0.4, '!': -0.3, '-': -1.0}
    assert ACTION_NOTA_BASE == 6.0
    assert ACTION_NOTA_SPAN == 4.0
    assert ACTION_NOTA_SHRINK == 3
    # Independent tables: same values as WEIGHTS, but never the same object.
    assert ACTION_NOTA_GRADE_VALUES is not WEIGHTS
    assert all(ACTION_NOTA_GRADE_VALUES is not v for v in PLAYER_GRADE_VALUES.values())


@pytest.mark.parametrize(
    'touches,expected',
    [
        ('', 0.0),
        ('A#', 10.0),
        ('E+', 8.5),
        ('A# E+', 10.0),
        ('R# R- R+', 3.5),
        ('A- A- A-', 1.0),
        ('S+ S+ A+ E+ D+ R+', 7.6),
    ],
)
def test_team_rating_shared_values_and_plain_touch_average(stats_factory, touches, expected):
    assert calculate_rating(stats_factory(touches)) == expected


@pytest.mark.parametrize('action', list('SREADB'))
@pytest.mark.parametrize(
    'grade,rating,good', [('#', 7.0, 1), ('+', 6.4, 1), ('!', 5.7, 0), ('-', 5.0, 0)]
)
def test_action_stats_single_touch_nota(stats_factory, action, grade, rating, good):
    result = calculate_action_stats(stats_factory(action + grade))
    assert list(result) == list('SREADB')
    assert result == {
        a: (
            {'tot': 1, 'good': good, 'pos_pct': float(good), 'rating': rating}
            if a == action
            else {'tot': 0, 'good': 0, 'pos_pct': None, 'rating': None}
        )
        for a in 'SREADB'
    }


@pytest.mark.parametrize('action', list('SREADB'))
def test_action_stats_mixed_grade_nota(stats_factory, action):
    # (1.0 - 0.3 - 1.0) / (3 + 3) = -0.05 -> 6.0 - 0.2 = 5.8, the same for every action.
    touches = f'{action}# {action}! {action}-'
    assert calculate_action_stats(stats_factory(touches))[action]['rating'] == 5.8


@pytest.mark.parametrize('count,expected', [(1, 6.4), (4, 6.9), (6, 7.1), (50, 7.5)])
def test_action_stats_shrinkage_volume_series(stats_factory, count, expected):
    serve = calculate_action_stats(stats_factory(' '.join(['S+'] * count)))['S']
    assert serve['rating'] == expected
    assert serve['pos_pct'] == 1.0
    assert serve['good'] == count


def test_action_stats_repeated_grade_never_exceeds_its_limit(stats_factory):
    limits = {'#': 10.0, '+': 7.6, '!': 4.8, '-': 2.0}
    for grade, limit in limits.items():
        ratings = [
            calculate_action_stats(stats_factory(' '.join(['S' + grade] * n)))['S']['rating']
            for n in (1, 10, 100, 1000)
        ]
        if grade in '#+':
            assert ratings == sorted(ratings)
            assert ratings[-1] <= limit
        else:
            assert ratings == sorted(ratings, reverse=True)
            assert ratings[-1] >= limit


def test_action_stats_equal_positive_rate_differs_by_grade(stats_factory):
    plus = calculate_action_stats(stats_factory('A+ A+ A+ A+ A+ A! A-'))['A']
    kill = calculate_action_stats(stats_factory('A# A# A# A# A# A! A-'))['A']
    assert plus['good'] == kill['good'] == 5
    assert plus['pos_pct'] == kill['pos_pct'] == pytest.approx(5 / 7)
    assert plus['rating'] == 6.3
    assert kill['rating'] == 7.5


def test_action_stats_error_instead_of_regular_lowers_nota(stats_factory):
    # (0.4 - 0.3) / 5 = 0.02 -> 6.1; (0.4 - 1.0) / 5 = -0.12 -> 5.5
    assert calculate_action_stats(stats_factory('R+ R!'))['R']['rating'] == 6.1
    assert calculate_action_stats(stats_factory('R+ R-'))['R']['rating'] == 5.5


def test_action_stats_empty_and_unrounded_fraction(stats_factory):
    assert calculate_action_stats(stats_factory()) == {
        a: {'tot': 0, 'good': 0, 'pos_pct': None, 'rating': None} for a in 'SREADB'
    }
    attack = calculate_action_stats(stats_factory('A# A! A-'))['A']
    assert set(attack) == {'tot', 'good', 'pos_pct', 'rating'}
    assert attack['tot'] == 3
    assert attack['good'] == 1
    assert attack['pos_pct'] == pytest.approx(1 / 3)
    assert attack['rating'] == 5.8


def test_omega_source_log_action_notas():
    """Keep the documented Omega examples tied to their source match log."""
    parsed = parse_log(OMEGA_LOG.read_text(encoding='utf-8'))
    seven = calculate_action_stats(parsed['players']['7'])
    twelve = calculate_action_stats(parsed['players']['12'])

    attack = seven['A']
    assert attack['good'] == 5
    assert attack['tot'] == 7
    assert attack['pos_pct'] == pytest.approx(5 / 7)
    assert attack['rating'] == 6.3
    assert calculate_efficiency(parsed['players']['7'])['attack_eff'] == pytest.approx(-1 / 7)

    assert (seven['S']['good'], seven['S']['tot'], seven['S']['rating']) == (4, 4, 6.9)
    assert (twelve['S']['good'], twelve['S']['tot'], twelve['S']['rating']) == (6, 6, 7.1)


@pytest.mark.parametrize('calculator', [calculate_rating, calculate_action_stats])
def test_rating_calculators_do_not_mutate(stats_factory, calculator):
    data = stats_factory('A# A- E+ R! B# S-')
    before = deepcopy(data)
    calculator(data)
    assert data == before


def test_role_action_weights_sum_to_one_and_have_no_zero_weights():
    assert set(ROLE_ACTION_WEIGHTS) == set(POSITION_LABELS)
    for role, weights in ROLE_ACTION_WEIGHTS.items():
        assert set(weights) == set(ACTIONS), f'{role} missing actions'
        assert sum(weights.values()) == pytest.approx(1.0), f'{role} weights do not sum to 1.0'
        for action, weight in weights.items():
            assert weight > 0.0, f'{role} has non-positive weight for {action}'


def test_mb_reception_and_opp_defense_affect_player_rating(stats_factory):
    # MB reception touches are counted (non-zero R weight)
    mb_good_r = calculate_player_rating(stats_factory('A# A+ R# R# R#'), 'MB')
    mb_bad_r = calculate_player_rating(stats_factory('A# A+ R- R- R-'), 'MB')
    assert mb_good_r > mb_bad_r

    # OPP weights defense higher than attack while still caring about attack
    assert ROLE_ACTION_WEIGHTS['OPP']['D'] > ROLE_ACTION_WEIGHTS['OPP']['A'] > 0.0
    opp_good_a = calculate_player_rating(stats_factory('D# D+ A# A#'), 'OPP')
    opp_bad_a = calculate_player_rating(stats_factory('D# D+ A- A-'), 'OPP')
    assert opp_good_a > opp_bad_a
