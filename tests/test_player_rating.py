import copy
import sqlite3
from pathlib import Path

import pytest

from analytics import (
    POSITION_LABELS,
    ROLE_ACTION_WEIGHTS,
    WEIGHTS,
    _parse_role_line,
    calculate_player_rating,
    calculate_rating,
    parse_log,
)
from db import get_match, get_player_season_stats, init_db, upsert_match
from validate_logs import validate_file

AST = {'#': 2, '+': 0, '!': 0, '-': 1}
VIDEO = '@youtube: https://youtu.be/abcdefghijk\n'


def blk(touches, sets, role):
    return {'touches': touches, 'sets': sets, 'role': role}


@pytest.fixture
def player(stats_factory):
    def make(touches, blocks=None, assists=None):
        stats = stats_factory(touches)
        del stats['role_blocks'], stats['assists']
        if blocks is not None:
            stats['role_blocks'] = blocks
        if assists is not None:
            stats['assists'] = dict(assists)
        return stats

    return make


def test_constants():
    assert set(ROLE_ACTION_WEIGHTS) == set(POSITION_LABELS)
    assert WEIGHTS == {'#': 1.0, '+': 0.4, '!': -0.3, '-': -1.0}


@pytest.mark.parametrize(
    'touches,position,blocks,assists,expected',
    [
        ('', 'S', None, None, 0.0),
        ('E#', 'S', None, None, 7.4),
        ('E# E# E+ E+ S#', 'S', None, None, 8.4),
        ('E# E+ E!', 'S', None, AST, 7.2),
        ('E# E+ E!', 'OH', None, AST, 7.2),
        ('A# A# A-', 'OH', None, AST, 8.2),
        ('R# R+ D-', 'L', None, None, 6.1),
        ('A# A#', 'L', None, None, 10.0),
        ('A# R+ S-', 'U', None, None, 6.5),
        ('A# R+ S-', 'XX', None, None, 6.5),
        ('A# A# A- R+ E+ E+', 'OH', None, None, 7.4),
        ('A# A# A- R+', 'OH', None, None, 7.7),
        ('A# A# A- R+', 'OH', [blk(4, 0, 'S')], None, 7.4),
        ('E# E# S# S-', 'S', None, None, 7.6),
        ('E# E# S# S-', 'S', [blk(4, 2, 'MB')], None, 6.6),
        ('A# A# B+ E!', 'S', None, None, 7.0),
        ('E# E+ E!', 'S', [blk(3, 3, 'OPP')], AST, 6.6),
        ('A# A# A- R+ E# E# E+ E+', 'OH', None, None, 8.0),
        ('A# A# A- R+ E# E# E+ E+', 'OH', [blk(4, 0, None), blk(4, 4, None)], None, 7.9),
        ('A# A# A- R+ E# E# E+ E+', 'OH', [blk(4, 0, None), blk(4, 4, 'S')], None, 7.9),
    ],
)
def test_player_rating_table(player, touches, position, blocks, assists, expected):
    assert calculate_player_rating(player(touches, blocks, assists), position) == expected


def test_player_rating_does_not_mutate_and_empty_blocks(player):
    data = player('A# A# A- R+ E# E+', [blk(6, 2, 'S')], AST)
    before = copy.deepcopy(data)
    calculate_player_rating(data, 'OH')
    assert data == before
    absent = player('A# A# A- R+ E+ E+')
    assert calculate_player_rating(player('A# A# A- R+ E+ E+', []), 'OH') == (
        calculate_player_rating(absent, 'OH')
    )


def test_role_line_parsing():
    assert _parse_role_line('@ROLE: 2=s, 25=mb') == [('2', 'S'), ('25', 'MB')]
    assert _parse_role_line('@role:2=S,25=OPP') == [('2', 'S'), ('25', 'OPP')]
    for bad in ('@role: 2=XX', '@role: 2S', '@role:', '@role: 2=S,', '@role: =S'):
        assert _parse_role_line(bad) is None


def test_role_blocks_single_and_per_block():
    assert parse_log('@role: 2=S\n2E#')['players']['2']['role_blocks'] == [blk(1, 1, 'S')]
    parsed = parse_log('2A# 2E+\n---\n@role: 2=S\n2E# 7A#\n2R+')
    assert parsed['players']['2']['role_blocks'] == [blk(2, 1, None), blk(2, 1, 'S')]
    assert parsed['players']['7']['role_blocks'] == [blk(1, 0, None)]
    assert parsed['team']['role_blocks'] == []
    for stats in parsed['players'].values():
        assert sum(b['touches'] for b in stats['role_blocks']) == stats['total']


def test_role_first_entry_wins_and_placement_is_irrelevant():
    blocks = parse_log('@role: 2=S\n2E#\n@role: 2=MB, 7=L')['players']['2']['role_blocks']
    assert blocks == [blk(1, 1, 'S')]
    assert parse_log('@role: 2=OH, 2=S\n2E#')['players']['2']['role_blocks'] == [blk(1, 1, 'OH')]


@pytest.mark.parametrize('line', ['@role: 2=XX', '@role: 2S'])
def test_malformed_role_is_ignored(line):
    assert parse_log(f'{line}\n2E#')['players']['2']['role_blocks'] == [blk(1, 1, None)]


def _without_roles(text):
    return '\n'.join(line for line in text.splitlines() if not line.startswith('@role:'))


@pytest.mark.parametrize(
    'text',
    [
        VIDEO
        + '@role: 7=S\n7E# 8A# @won @t:1-2\n@set: 1-0\n---\n@role: 8=MB\n---\n'
        + VIDEO
        + '@role: 7=OPP\n7A- @lost @t:3-4',
        (
            Path('teams/nova/atlas-chapalita-cup-2026/matches/05_atlas_b.txt').read_text(
                encoding='utf-8'
            )
        ),
    ],
)
def test_roles_do_not_affect_rallies_or_replay(text):
    assert '@role:' in text
    with_roles, without = parse_log(text), parse_log(_without_roles(text))
    for key in ('rallies', 'rally_outcomes', 'rally_timestamps', 'team'):
        assert with_roles[key] == without[key]
    sets, plain = with_roles['replay']['sets'], without['replay']['sets']
    assert len(sets) == len(plain)
    assert [s['eligible'] for s in sets] == [s['eligible'] for s in plain]
    assert [s['diagnostics'] for s in sets] == [s['diagnostics'] for s in plain]


@pytest.mark.parametrize(
    'text,setter_assists,team_assists',
    [
        ('7E# 8A#', {'#': 1, '+': 0, '!': 0, '-': 0}, {'#': 1, '+': 0, '!': 0, '-': 0}),
        ('7E+ A-', {'#': 0, '+': 0, '!': 0, '-': 1}, {'#': 0, '+': 0, '!': 0, '-': 1}),
        ('7E# 8D+ 8A#', dict.fromkeys('#+!-', 0), dict.fromkeys('#+!-', 0)),
        ('8D+ 7E#\n8A#', dict.fromkeys('#+!-', 0), dict.fromkeys('#+!-', 0)),
        ('E# 8A# 7E!', dict.fromkeys('#+!-', 0), dict.fromkeys('#+!-', 0)),
    ],
)
def test_assists(text, setter_assists, team_assists):
    parsed = parse_log(text)
    assert parsed['players']['7']['assists'] == setter_assists
    assert parsed['team']['assists'] == team_assists


def test_snapshot_player_rating_uses_set_override():
    lines = ['7A# @won @t:1-2', '7A# 7R+ @won @t:3-4', '7A- @lost @t:5-6']
    roles = VIDEO + '@role: 7=S\n'
    positions = {'7': 'OH'}
    item = parse_log(roles + '\n'.join(lines), positions)['replay']['sets'][0]
    assert item['eligible']
    for index, snapshot in enumerate(item['snapshots'][1:], 1):
        prefix = parse_log(roles + '\n'.join(lines[:index]), positions)
        row = snapshot['players'][0]
        assert row['rating'] == calculate_player_rating(prefix['players']['7'], 'OH')
        assert snapshot['team']['rating'] == calculate_rating(prefix['team'])
    final = item['snapshots'][-1]['players'][0]['rating']
    assert final == 7.4
    plain = parse_log(VIDEO + '\n'.join(lines), positions)['replay']['sets'][0]
    assert plain['snapshots'][-1]['players'][0]['rating'] == 7.7


@pytest.mark.parametrize(
    'text,expected',
    [
        ('@role: 2=S\n2E# 7A#', []),
        ('@role: 2=XX\n2E#', [('ERROR', 'R11')]),
        ('@role: 2S\n2E#', [('ERROR', 'R11')]),
        ('@role: 9=S\n2E#', [('ERROR', 'R2'), ('WARN', 'R11')]),
        ('@role: 2=S, 2=MB\n2E#', [('WARN', 'R11')]),
        ('@role: 2=S\n@role: 2=MB\n2E#', [('WARN', 'R11')]),
        ('@role: 7=S\n2E#', [('WARN', 'R11')]),
        ('2E#\n@role: 2=S', [('WARN', 'R11')]),
        ('2E#\n---\n@role: 2=S\n7A#', [('WARN', 'R11')]),
    ],
)
def test_validator_r11(tmp_path, text, expected):
    path = tmp_path / 'match.txt'
    path.write_text(text, encoding='utf-8')
    issues = validate_file(path, {'2', '7'})
    assert sorted((i[1], i[2]) for i in issues) == expected


def test_validator_r11_messages(tmp_path):
    path = tmp_path / 'match.txt'
    path.write_text('@role: 2=S, 2=MB, 7=L\n2E#\n@role: 2=OH', encoding='utf-8')
    messages = [i[3] for i in validate_file(path, {'2', '7'})]
    assert any('only the first is used' in m for m in messages)
    assert any('override has no effect in this set' in m for m in messages)
    assert any('@role: should precede the first rally' in m for m in messages)


LOG = '2A# 2A# 2A- 2R+\n---\n@role: 2=S\n2E# 7A# @won\n2E+ 7A- @lost\n2D+ 2A# 2S#\n2R+'


@pytest.fixture
def conn():
    connection = sqlite3.connect(':memory:')
    init_db(connection)
    init_db(connection)
    yield connection
    connection.close()


def test_db_round_trip_and_season_rating(conn):
    parsed = parse_log(LOG, {'2': 'OH'})
    upsert_match(conn, '01_test', 'Test', parsed)
    stored = get_match(conn, '01_test')
    for num, stats in parsed['players'].items():
        assert stored['players'][num]['assists'] == stats['assists']
        assert stored['players'][num]['role_blocks'] == stats['role_blocks']
    assert (
        stored['team']['assists']
        == parsed['team']['assists']
        == {
            '#': 1,
            '+': 0,
            '!': 0,
            '-': 1,
        }
    )
    assert stored['team']['role_blocks'] == []
    season = get_player_season_stats(conn, '2', 'OH')
    expected = calculate_player_rating(parsed['players']['2'], 'OH')
    assert season[0]['rating'] == expected
    assert expected != calculate_player_rating(parse_log(_without_roles(LOG))['players']['2'], 'OH')


def test_db_null_role_blocks_rate_as_single_inferred_block(conn):
    parsed = parse_log(LOG)
    upsert_match(conn, '01_test', 'Test', parsed)
    conn.execute('UPDATE player_match_stats SET role_blocks = NULL')
    data = parsed['players']['2']
    single = {**data, 'role_blocks': [blk(data['total'], data['actions']['E']['tot'], None)]}
    assert get_player_season_stats(conn, '2', 'OH')[0]['rating'] == (
        calculate_player_rating(single, 'OH')
    )
    assert get_match(conn, '01_test')['players']['2']['role_blocks'] == []
