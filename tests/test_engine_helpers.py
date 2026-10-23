import json

import pytest

from analytics import _new_stats, _record, load_team_config


def empty_stats():
    return {
        'total': 0,
        'score_sum': 0.0,
        'grades': dict.fromkeys('#+!-', 0),
        'actions': {a: {'tot': 0, 'good': 0} for a in 'SREADB'},
        'grade_count': {g: dict.fromkeys('SREADB', 0) for g in '#+!-'},
    }


def test_new_stats_shape_and_independence():
    first, second = _new_stats(), _new_stats()
    assert first == second == empty_stats()
    first['actions']['A']['tot'] = 1
    first['grade_count']['#']['A'] = 1
    first['grades']['#'] = 1
    assert second == empty_stats()
    assert first['actions']['S'] == {'tot': 0, 'good': 0}
    assert first['grade_count']['+'] == dict.fromkeys('SREADB', 0)


@pytest.mark.parametrize('action', 'SREADB')
@pytest.mark.parametrize(
    'grade,score,good', [('#', 1.0, 1), ('+', 0.4, 1), ('!', -0.3, 0), ('-', -1.0, 0)]
)
def test_record_updates_only_relevant_counters(action, grade, score, good):
    stats = _new_stats()
    assert _record(stats, action, grade) is None
    expected = empty_stats()
    expected['total'] = 1
    expected['score_sum'] = score
    expected['grades'][grade] = 1
    expected['actions'][action] = {'tot': 1, 'good': good}
    expected['grade_count'][grade][action] = 1
    assert stats == expected


def test_record_accumulates():
    stats = _new_stats()
    for grade in '#+!-':
        _record(stats, 'A', grade)
    assert stats['total'] == 4
    assert stats['score_sum'] == pytest.approx(0.1)
    assert stats['actions']['A'] == {'tot': 4, 'good': 2}
    assert stats['grades'] == dict.fromkeys('#+!-', 1)


def test_load_complete_team_config(tmp_path):
    path = tmp_path / 'team.json'
    objectives = [{'label': 'Top 4', 'current': 5, 'target': 4}]
    path.write_text(
        json.dumps(
            {
                'team': 'Equipo',
                'tournament': 'Copa',
                'type': 'friendly',
                'roster': {
                    '7': {'name': 'Jos\u00e9', 'position': 'OH'},
                    '8': {'name': ''},
                    '12': {'position': 'S'},
                },
                'objectives': objectives,
            },
            ensure_ascii=False,
        ),
        encoding='utf-8',
    )
    assert load_team_config(path) == {
        'team': 'Equipo',
        'tournament': 'Copa',
        'type': 'friendly',
        'positions': {'7': 'OH', '8': 'U', '12': 'S'},
        'names': {'7': 'Jos\u00e9'},
        'objectives': objectives,
    }


@pytest.mark.parametrize(
    'config',
    [
        {},
        {'objectives': None},
        {'objectives': {}},
        {'objectives': 'bad'},
        {'objectives': 1},
        {'objectives': []},
    ],
)
def test_load_team_config_defaults(tmp_path, config):
    path = tmp_path / 'team.json'
    path.write_text(json.dumps(config), encoding='utf-8')
    assert load_team_config(path) == {
        'team': '',
        'tournament': '',
        'type': 'tournament',
        'positions': {},
        'names': {},
        'objectives': [],
    }


def test_load_team_config_missing_file(tmp_path):
    with pytest.raises(FileNotFoundError):
        load_team_config(tmp_path / 'missing.json')


def test_load_team_config_malformed_json(tmp_path):
    path = tmp_path / 'team.json'
    path.write_text('{', encoding='utf-8')
    with pytest.raises(json.JSONDecodeError):
        load_team_config(path)
