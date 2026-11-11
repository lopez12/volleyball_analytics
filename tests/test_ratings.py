from copy import deepcopy

import pytest

from analytics import (
    ACTION_NOTA_CENTER,
    ACTION_NOTA_SCALE,
    RATING_CENTER,
    TEAM_RATING_RAW_MEAN,
    TEAM_RATING_SCALE,
    calculate_action_stats,
    calculate_rating,
)


def test_frozen_team_and_action_rating_constants():
    assert RATING_CENTER == 7.0
    assert TEAM_RATING_RAW_MEAN == 0.114
    assert TEAM_RATING_SCALE == 17.6
    assert ACTION_NOTA_CENTER == {
        'S': 0.206,
        'R': 0.023,
        'E': 0.071,
        'A': 0.1,
        'D': 0.069,
        'B': 0.155,
    }
    assert ACTION_NOTA_SCALE == {'S': 4.8, 'R': 5.3, 'E': 7.3, 'A': 4.3, 'D': 5.8, 'B': 4.0}


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


@pytest.mark.parametrize(
    'action,ratings',
    [
        ('S', [10.0, 6.5, 5.1, 1.2]),
        ('R', [9.5, 8.2, 5.8, 1.6]),
        ('E', [9.4, 7.9, 3.6, 1.0]),
        ('A', [10.0, 6.6, 5.7, 2.3]),
        ('D', [9.5, 8.0, 6.6, 2.0]),
        ('B', [10.0, 7.2, 5.2, 3.2]),
    ],
)
@pytest.mark.parametrize('grade,index,good', [('#', 0, 1), ('+', 1, 1), ('!', 2, 0), ('-', 3, 0)])
def test_action_stats_single_touch_nota(stats_factory, action, ratings, grade, index, good):
    result = calculate_action_stats(stats_factory(action + grade))
    assert list(result) == list('SREADB')
    assert result == {
        a: (
            {'tot': 1, 'good': good, 'pos_pct': float(good), 'rating': ratings[index]}
            if a == action
            else {'tot': 0, 'good': 0, 'pos_pct': None, 'rating': None}
        )
        for a in 'SREADB'
    }


@pytest.mark.parametrize(
    'action,expected', [('S', 5.7), ('R', 5.6), ('E', 4.0), ('A', 6.3), ('D', 6.0), ('B', 6.2)]
)
def test_action_stats_mixed_grade_nota(stats_factory, action, expected):
    touches = f'{action}# {action}! {action}-'
    assert calculate_action_stats(stats_factory(touches))[action]['rating'] == expected


def test_action_stats_empty_and_unrounded_fraction(stats_factory):
    assert calculate_action_stats(stats_factory()) == {
        a: {'tot': 0, 'good': 0, 'pos_pct': None, 'rating': None} for a in 'SREADB'
    }
    attack = calculate_action_stats(stats_factory('A# A! A-'))['A']
    assert set(attack) == {'tot', 'good', 'pos_pct', 'rating'}
    assert attack['tot'] == 3
    assert attack['good'] == 1
    assert attack['pos_pct'] == pytest.approx(1 / 3)
    assert attack['rating'] == 6.3


@pytest.mark.parametrize('calculator', [calculate_rating, calculate_action_stats])
def test_rating_calculators_do_not_mutate(stats_factory, calculator):
    data = stats_factory('A# A- E+ R! B# S-')
    before = deepcopy(data)
    calculator(data)
    assert data == before
