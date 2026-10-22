from copy import deepcopy

import pytest

from analytics import _scale_rating, calculate_action_stats, calculate_rating


@pytest.mark.parametrize(
    'action,ratings',
    [
        ('S', [10.0, 7.8, 4.7, 1.6]),
        ('R', [10.0, 7.6, 4.8, 2.0]),
        ('E', [8.6, 7.0, 5.2, 3.4]),
        ('A', [10.0, 8.1, 4.4, 1.0]),
        ('D', [10.0, 7.6, 4.8, 2.0]),
        ('B', [10.0, 7.9, 4.6, 1.2]),
    ],
)
@pytest.mark.parametrize('grade,index', [('#', 0), ('+', 1), ('!', 2), ('-', 3)])
def test_rating_leverage_by_action_and_grade(stats_factory, action, ratings, grade, index):
    assert calculate_rating(stats_factory(action + grade)) == ratings[index]


@pytest.mark.parametrize(
    'touches,expected',
    [
        ('', 0.0),
        ('A# E+', 9.1),
        ('A# A# A#', 10.0),
        ('A- A- A-', 1.0),
        ('R# R- R+', 6.5),
    ],
)
def test_rating_mixed_raw_touch_denominator_and_empty(stats_factory, touches, expected):
    assert calculate_rating(stats_factory(touches)) == expected


@pytest.mark.parametrize(
    'weighted,total,expected',
    [
        (-3, 1, 1.0),
        (-1.25, 1, 1.0),
        (-1.2, 1, 1.2),
        (0, 2, 6.0),
        (1, 1, 10.0),
        (2, 1, 10.0),
        (0.26, 1, 7.0),
        (0.4, 3, 6.5),
        (0.3, 1, 7.2),
    ],
)
def test_scale_rating_boundaries_and_rounding(weighted, total, expected):
    assert _scale_rating(weighted, total) == expected


@pytest.mark.parametrize('action', 'SREADB')
@pytest.mark.parametrize(
    'grade,rating,good', [('#', 10.0, 1), ('+', 7.6, 1), ('!', 4.8, 0), ('-', 2.0, 0)]
)
def test_action_stats_grade_has_no_leverage(stats_factory, action, grade, rating, good):
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


def test_action_stats_empty_and_unrounded_fraction(stats_factory):
    assert calculate_action_stats(stats_factory()) == {
        a: {'tot': 0, 'good': 0, 'pos_pct': None, 'rating': None} for a in 'SREADB'
    }
    attack = calculate_action_stats(stats_factory('A# A! A-'))['A']
    assert set(attack) == {'tot', 'good', 'pos_pct', 'rating'}
    assert attack['tot'] == 3
    assert attack['good'] == 1
    assert attack['pos_pct'] == pytest.approx(1 / 3)
    assert attack['rating'] == 5.6


@pytest.mark.parametrize('calculator', [calculate_rating, calculate_action_stats])
def test_rating_calculators_do_not_mutate(stats_factory, calculator):
    data = stats_factory('A# A- E+ R! B# S-')
    before = deepcopy(data)
    calculator(data)
    assert data == before
