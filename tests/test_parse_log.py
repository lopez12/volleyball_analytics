import pytest

from analytics import (
    _parse_date_token,
    _parse_outcome_token,
    _parse_timestamp_token,
    parse_log,
)


@pytest.mark.parametrize('text', ['', ' \t\r\n', '\n---\n \n---\n'])
def test_empty_log_shape(text):
    assert parse_log(text) == {
        'players': {},
        'team': {
            'total': 0,
            'score_sum': 0.0,
            'grades': dict.fromkeys('#+!-', 0),
            'actions': {a: {'tot': 0, 'good': 0} for a in 'SREADB'},
            'grade_count': {g: dict.fromkeys('SREADB', 0) for g in '#+!-'},
        },
        'rallies': [],
        'rally_outcomes': [],
        'rally_timestamps': [],
        'points': {'won': 0, 'won_kill': 0, 'won_rival_error': 0, 'won_serve_error': 0, 'lost': 0},
        'youtube_urls': [],
        'set_scores': [],
        'match_date': None,
    }


@pytest.mark.parametrize('action', 'SREADB')
@pytest.mark.parametrize(
    'grade,weight,good', [('#', 1.0, 1), ('+', 0.4, 1), ('!', -0.3, 0), ('-', -1.0, 0)]
)
def test_player_and_team_tokens(action, grade, weight, good):
    parsed = parse_log(f'7{action}{grade} {action}{grade}')
    player, team = parsed['players']['7'], parsed['team']
    assert list(parsed['players']) == ['7']
    assert parsed['rallies'] == [[f'7{action}{grade}', f'{action}{grade}']]
    for stats, count in [(player, 1), (team, 2)]:
        assert stats['total'] == count
        assert stats['score_sum'] == pytest.approx(weight * count)
        assert stats['grades'] == {g: count if g == grade else 0 for g in '#+!-'}
        assert stats['actions'] == {
            a: {'tot': count if a == action else 0, 'good': good * count if a == action else 0}
            for a in 'SREADB'
        }
        assert stats['grade_count'] == {
            g: {a: count if (a, g) == (action, grade) else 0 for a in 'SREADB'} for g in '#+!-'
        }


def test_multiple_players_order_whitespace_and_legacy_metadata():
    parsed = parse_log(' \t7R+\t12E#  7A#\r\n\n---\n S- 12D! \n')
    assert parsed['rallies'] == [['7R+', '12E#', '7A#'], ['S-', '12D!']]
    assert {n: s['total'] for n, s in parsed['players'].items()} == {'7': 2, '12': 2}
    assert parsed['team']['total'] == 5
    assert parsed['rally_outcomes'] == [{'result': None, 'cause': None}] * 2
    assert parsed['rally_timestamps'] == [None, None]
    assert parsed['points'] == {
        'won': 0,
        'won_kill': 0,
        'won_rival_error': 0,
        'won_serve_error': 0,
        'lost': 0,
    }


@pytest.mark.parametrize('token', ['7X#', '7a#', '7A', '7A++', '-7A#', 'junk', '@won:no', '@t:bad'])
def test_invalid_tokens_and_invalid_only_lines_are_ignored(token):
    assert parse_log(token)['rallies'] == []
    assert parse_log(f'7S+ {token} A#')['rallies'] == [['7S+', 'A#']]


@pytest.mark.parametrize(
    'token,result,cause',
    [
        ('@won', 'won', None),
        ('@LOST', 'lost', None),
        ('@WoN:RE', 'won', 're'),
        ('@won:se', 'won', 'se'),
        ('@lost:re', 'lost', None),
        ('@LOST:SE', 'lost', None),
    ],
)
def test_outcome_tokens_and_first_outcome_wins(token, result, cause):
    expected = {'result': result, 'cause': cause}
    assert _parse_outcome_token(token) == expected
    parsed = parse_log(f'7A+ {token} @lost @won:se')
    assert parsed['rallies'] == [['7A+']]
    assert parsed['rally_outcomes'] == [expected]


@pytest.mark.parametrize('token', ['', 'won', '@won:bad', '@won:re:se', '@lose', '@won!'])
def test_invalid_outcome_helper(token):
    assert _parse_outcome_token(token) is None


def test_touchless_and_timestamp_only_alignment_and_points():
    parsed = parse_log(
        '@won:se @t:0-1\n@won:re\n@won\n@lost\n@t:8.5\n7R+\nignored\n7A# @won @t:10-12\n'
    )
    assert parsed['rallies'] == [[], [], [], [], [], ['7R+'], ['7A#']]
    assert parsed['rally_outcomes'] == [
        {'result': 'won', 'cause': 'se'},
        {'result': 'won', 'cause': 're'},
        {'result': 'won', 'cause': None},
        {'result': 'lost', 'cause': None},
        {'result': None, 'cause': None},
        {'result': None, 'cause': None},
        {'result': 'won', 'cause': None},
    ]
    assert parsed['rally_timestamps'] == [
        {'start': 0.0, 'end': 1.0},
        None,
        None,
        None,
        {'start': 8.5, 'end': None},
        None,
        {'start': 10.0, 'end': 12.0},
    ]
    assert (
        len(parsed['rallies']) == len(parsed['rally_outcomes']) == len(parsed['rally_timestamps'])
    )
    assert parsed['team']['total'] == parsed['players']['7']['total'] == 2
    assert list(parsed['players']) == ['7']
    assert parsed['points'] == {
        'won': 4,
        'won_kill': 2,
        'won_rival_error': 2,
        'won_serve_error': 1,
        'lost': 1,
    }
    assert parse_log('@won:se\n@t:5')['players'] == {}
    assert parse_log('@won:se\n@t:5')['team']['total'] == 0


def test_set_scores_order_and_malformed_lines():
    parsed = parse_log('@set: 25-18\n---\n@SET:0-25\n@set: 1:2\n@set: -1-2\n@set: 2-3 extra')
    assert parsed['set_scores'] == [(25, 18), (0, 25)]
    assert parsed['rallies'] == []


@pytest.mark.parametrize(
    'url',
    [
        'https://youtube.com/watch?v=example',
        'http://www.youtube.com/watch?v=x',
        'https://youtu.be/short',
        'http://youtu.be/x',
    ],
)
def test_youtube_prefix_acceptance(url):
    parsed = parse_log(f'@YOUTUBE: {url}\n@youtube: https://youtu.be/second')
    assert parsed['youtube_urls'] == [url, 'https://youtu.be/second']
    assert parsed['rallies'] == []


@pytest.mark.parametrize(
    'url',
    [
        'ftp://youtube.com/x',
        'https://example.com/x',
        'https://youtube.com.evil/x',
        'https://notyoutube.com/x',
        'https://youtu.be.evil/x',
        '',
    ],
)
def test_youtube_rejected_prefixes(url):
    parsed = parse_log(f'@youtube: {url}')
    assert parsed['youtube_urls'] == []
    assert parsed['rallies'] == []


@pytest.mark.parametrize(
    'token,expected',
    [
        ('@t:0', {'start': 0.0, 'end': None}),
        ('@T:12.5-14.25', {'start': 12.5, 'end': 14.25}),
        ('@t:3-3', {'start': 3.0, 'end': 3.0}),
        # Parsing checks syntax only, not interval chronology.
        ('@t:9-2', {'start': 9.0, 'end': 2.0}),
        ('@t:-1', None),
        ('@t:1-', None),
        ('@t:.5', None),
        ('@t:nan', None),
        ('@t:1:2', None),
        ('t:3', None),
    ],
)
def test_timestamp_helper(token, expected):
    assert _parse_timestamp_token(token) == expected


def test_timestamp_first_valid_wins_and_metadata_is_not_a_touch():
    parsed = parse_log('7S+ @t:bad @t:2.5-4 @t:9-10\n@t:bad\n@t:9-2')
    assert parsed['rallies'] == [['7S+'], []]
    assert parsed['rally_timestamps'] == [
        {'start': 2.5, 'end': 4.0},
        {'start': 9.0, 'end': 2.0},
    ]
    assert parsed['team']['total'] == 1


@pytest.mark.parametrize(
    'token,expected',
    [
        ('@date: 2024-02-29', '2024-02-29'),
        ('@DATE:2026-10-22', '2026-10-22'),
        ('@date: 2025-02-29', None),
        ('@date: 2026-13-01', None),
        ('@date: 2026-04-31', None),
        ('@date: 2026-00-01', None),
        ('@date: 0000-01-01', None),
        ('@date: 2026-1-01', None),
        ('2026-10-22', None),
        ('@date: 2026-10-22 extra', None),
    ],
)
def test_date_helper(token, expected):
    assert _parse_date_token(token) == expected


def test_first_valid_date_wins_and_invalid_dates_are_not_rallies():
    parsed = parse_log('@date: 2025-02-29\n@date: 2024-02-29\n@date: 2026-10-22')
    assert parsed['match_date'] == '2024-02-29'
    assert parsed['rallies'] == []
    assert parse_log('@date: invalid')['match_date'] is None
