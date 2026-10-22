from copy import deepcopy

import pytest

from analytics import (
    _determine_win,
    calculate_earned_points,
    calculate_phase_stats,
    calculate_point_stats,
    parse_log,
)


@pytest.mark.parametrize('prefix', ['', '7'])
@pytest.mark.parametrize(
    'trigger,phase',
    [
        ('R#', 'so_good'),
        ('R+', 'so_good'),
        ('R!', 'so_bad'),
        ('D#', 'trans'),
        ('D+', 'trans'),
        ('D!', 'trans'),
        ('D-', 'trans'),
    ],
)
def test_phase_triggers(prefix, trigger, phase):
    assert calculate_phase_stats([[prefix + trigger, '12E+', 'A#']]) == {
        key: {'attempts': int(key == phase), 'kills': int(key == phase)}
        for key in ('so_good', 'so_bad', 'trans')
    }


@pytest.mark.parametrize(
    'tokens,attempts,kills',
    [
        ('R+ E+ A#', 1, 1),
        ('R+ A#', 1, 0),
        ('R+ E+ A+', 1, 0),
        ('R+ E+ A!', 1, 0),
        ('R+ E+ A-', 1, 0),
        ('R+ E+ B# A#', 1, 0),
        ('R+ E+ S+ A#', 1, 0),
        ('R+ E+ R- E+ A#', 1, 0),
        ('R-', 0, 0),
        ('R- E+ A#', 0, 0),
        ('E+ A#', 0, 0),
        ('R+', 1, 0),
        ('R+ E+ invalid A#', 1, 1),
        ('R+ R# E+ A#', 2, 1),
        ('R+ E+ A# A#', 1, 1),
    ],
)
def test_phase_sequence_completion_and_interruption(tokens, attempts, kills):
    assert calculate_phase_stats([tokens.split()]) == {
        'so_good': {'attempts': attempts, 'kills': kills},
        'so_bad': {'attempts': 0, 'kills': 0},
        'trans': {'attempts': 0, 'kills': 0},
    }


def test_phase_trigger_replacement_multiple_phases_and_rally_reset():
    assert calculate_phase_stats(
        [
            ['R+', 'E+', 'D+', 'E!', 'A#', 'R!', 'E+', 'A#'],
            ['R+', 'E+'],
            ['A#'],
            ['R!', 'E+'],
            ['D+', 'A#'],
        ]
    ) == {
        'so_good': {'attempts': 2, 'kills': 0},
        'so_bad': {'attempts': 2, 'kills': 1},
        'trans': {'attempts': 2, 'kills': 1},
    }


@pytest.mark.parametrize(
    'outcomes,kills',
    [
        (None, 2),
        ([], 2),
        ([None], 2),
        ([{}], 2),
        ([{'result': None}], 2),
        ([{'result': 'won'}], 2),
        ([{'result': 'unknown'}], 2),
        ([{'result': 'lost'}], 0),
    ],
)
def test_phase_outcomes_apply_to_all_attacks_in_rally(outcomes, kills):
    result = calculate_phase_stats([['R+', 'E+', 'A#', 'D+', 'E+', 'A#']], outcomes)
    assert result == {
        'so_good': {'attempts': 1, 'kills': kills // 2},
        'so_bad': {'attempts': 0, 'kills': 0},
        'trans': {'attempts': 1, 'kills': kills // 2},
    }


def test_phase_short_outcome_list_falls_back_for_remaining_rallies():
    assert calculate_phase_stats(
        [['R+', 'E+', 'A#'], ['D+', 'E+', 'A#']],
        [{'result': 'lost'}],
    ) == {
        'so_good': {'attempts': 1, 'kills': 0},
        'so_bad': {'attempts': 0, 'kills': 0},
        'trans': {'attempts': 1, 'kills': 1},
    }


@pytest.mark.parametrize(
    'rallies,outcomes,expected',
    [
        ([['S-'], ['R+']], [{'result': 'won'}], True),
        ([['A#'], ['S+']], [{'result': 'lost'}], False),
        ([['A#']], [{'result': 'lost'}], False),
        ([['A-']], [{'result': 'won'}], True),
        ([[]], [{'result': 'won', 'cause': 'se'}], True),
    ],
)
def test_determine_win_explicit_overrides_context(rallies, outcomes, expected):
    assert _determine_win(0, rallies, outcomes) is expected


@pytest.mark.parametrize('outcomes', [None, [], [None], [{}], [{'result': None, 'cause': None}]])
@pytest.mark.parametrize(
    'next_rally,expected',
    [
        (['7S+'], True),
        (['S-'], True),
        (['junk', 'S+'], True),
        (['7R#'], False),
        (['D#', 'S+'], False),
        ([], False),
        (['junk'], False),
    ],
)
def test_determine_win_next_first_valid_action(outcomes, next_rally, expected):
    assert _determine_win(0, [['A#'], next_rally], outcomes) is expected


def test_determine_win_does_not_look_past_empty_next_rally():
    assert _determine_win(0, [['A#'], [], ['S+']]) is False
    assert _determine_win(1, [['S+'], ['R+'], ['S+']], [{'result': 'lost'}]) is True


@pytest.mark.parametrize(
    'last,expected',
    [
        (['A#'], True),
        (['7E#'], True),
        (['R#'], True),
        (['S#'], True),
        (['B#'], True),
        (['A+'], False),
        (['A!'], False),
        (['A-'], False),
        (['A#', 'invalid'], False),
        ([], False),
    ],
)
def test_determine_win_final_rally_uses_last_grade(last, expected):
    assert _determine_win(0, [last]) is expected


@pytest.mark.parametrize('prefix', ['', '7'])
@pytest.mark.parametrize(
    'outcomes,expected',
    [
        (None, {'bp': {'total': 2, 'won': 1}, 'so': {'total': 2, 'won': 1}}),
        (
            [{'result': 'lost'}, {'result': 'won'}, {'result': 'won'}, {'result': 'lost'}],
            {'bp': {'total': 2, 'won': 2}, 'so': {'total': 2, 'won': 0}},
        ),
        ([{'result': 'lost'}], {'bp': {'total': 2, 'won': 1}, 'so': {'total': 2, 'won': 0}}),
    ],
)
def test_point_stats_explicit_legacy_and_partial(prefix, outcomes, expected):
    rallies = [[prefix + token] for token in ['R+', 'S+', 'S-', 'R!']]
    assert calculate_point_stats(rallies, outcomes) == expected


@pytest.mark.parametrize(
    'rally,expected',
    [
        (['invalid', 'S#'], {'bp': {'total': 1, 'won': 1}, 'so': {'total': 0, 'won': 0}}),
        (['invalid', 'R#'], {'bp': {'total': 0, 'won': 0}, 'so': {'total': 1, 'won': 1}}),
        (['D+', 'S#'], {'bp': {'total': 0, 'won': 0}, 'so': {'total': 0, 'won': 0}}),
        (['A+', 'R#'], {'bp': {'total': 0, 'won': 0}, 'so': {'total': 0, 'won': 0}}),
        (['invalid'], {'bp': {'total': 0, 'won': 0}, 'so': {'total': 0, 'won': 0}}),
    ],
)
def test_point_stats_classifies_only_first_valid_action(rally, expected):
    assert calculate_point_stats([rally]) == expected


@pytest.mark.parametrize(
    'outcome,won',
    [
        ({'result': 'won', 'cause': 'se'}, 1),
        ({'result': 'won', 'cause': 're'}, 0),
        ({'result': 'won', 'cause': None}, 0),
        ({'result': 'lost', 'cause': None}, 0),
        ({'result': None, 'cause': None}, 0),
        (None, 0),
    ],
)
def test_point_stats_touchless_serve_error_only(outcome, won):
    assert calculate_point_stats([[]], [outcome]) == {
        'bp': {'total': 0, 'won': 0},
        'so': {'total': won, 'won': won},
    }


@pytest.mark.parametrize('outcomes', [[], [None, {}, {'result': None}, {'result': 'unknown'}]])
def test_earned_points_empty_and_unknown(outcomes):
    assert calculate_earned_points(outcomes) == {
        'won': 0,
        'won_kill': 0,
        'won_rival_error': 0,
        'won_serve_error': 0,
        'lost': 0,
    }


def test_earned_points_exact_attribution_and_subsets():
    outcomes = [
        {'result': 'won', 'cause': None},
        {'result': 'won'},
        {'result': 'won', 'cause': 're'},
        {'result': 'won', 'cause': 'se'},
        {'result': 'lost'},
        {'result': 'lost'},
        {},
        None,
        {'result': None},
    ]
    before = deepcopy(outcomes)
    points = calculate_earned_points(outcomes)
    assert points == {
        'won': 4,
        'won_kill': 2,
        'won_rival_error': 2,
        'won_serve_error': 1,
        'lost': 2,
    }
    assert points['won_serve_error'] <= points['won_rival_error'] <= points['won']
    assert points['won'] == points['won_kill'] + points['won_rival_error']
    assert outcomes == before


def test_empty_rally_calculations():
    assert calculate_phase_stats([]) == {
        'so_good': {'attempts': 0, 'kills': 0},
        'so_bad': {'attempts': 0, 'kills': 0},
        'trans': {'attempts': 0, 'kills': 0},
    }
    assert calculate_point_stats([]) == {
        'bp': {'total': 0, 'won': 0},
        'so': {'total': 0, 'won': 0},
    }


@pytest.mark.parametrize('explicit', [False, True])
def test_mixed_log_integration(explicit):
    lines = ['7R+ 12E+ 7A#', 'S+ D+ E+ A#', 'R! E+ A+']
    if explicit:
        lines = [
            f'{line} {outcome}'
            for line, outcome in zip(lines, ['@lost', '@won', '@won:re'], strict=True)
        ]
        lines.append('@won:se @t:20-21')
    parsed = parse_log('\n'.join(lines))
    outcomes = parsed['rally_outcomes'] if explicit else None
    assert calculate_phase_stats(parsed['rallies'], outcomes) == {
        'so_good': {'attempts': 1, 'kills': 0 if explicit else 1},
        'so_bad': {'attempts': 1, 'kills': 0},
        'trans': {'attempts': 1, 'kills': 1},
    }
    assert calculate_point_stats(parsed['rallies'], outcomes) == (
        {'bp': {'total': 1, 'won': 1}, 'so': {'total': 3, 'won': 2}}
        if explicit
        else {'bp': {'total': 1, 'won': 0}, 'so': {'total': 2, 'won': 1}}
    )


@pytest.mark.parametrize('calculator', [calculate_phase_stats, calculate_point_stats])
def test_rally_calculators_do_not_mutate(calculator):
    rallies = [['7R+', '12E+', '7A#'], [], ['S-', 'D+', 'E+', 'A#']]
    outcomes = [
        {'result': 'lost', 'cause': None},
        {'result': 'won', 'cause': 'se'},
        {'result': None, 'cause': None},
    ]
    before = deepcopy((rallies, outcomes))
    calculator(rallies, outcomes)
    assert (rallies, outcomes) == before
    for index in range(len(rallies)):
        _determine_win(index, rallies, outcomes)
    assert (rallies, outcomes) == before
