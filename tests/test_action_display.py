"""Regression tests for the rendered positive/complementary action-quality data."""

import json
import re
from pathlib import Path

from analytics import ACTIONS, parse_log
from renderer import (
    _GRADE_PREFIXES,
    _action_efficiency_charts,
    _json_for_script,
    _rating_tier,
    build_card_html,
    render_match_page,
    render_player_season_page,
    render_team_season_page,
)

OMEGA_LOG = Path(__file__).parents[1] / 'teams/nova/atlas-chapalita-cup-2026/matches/07_omega.txt'
NOTA_TOOLTIP = (
    'title="Promedio de los grados de la acción en escala fija; se ajusta al centro cuando '
    'hay pocos intentos, excepto en bloqueo."'
)


def _omega_player_seven_stats():
    parsed = parse_log(OMEGA_LOG.read_text(encoding='utf-8'))
    return parsed['players']['7']


def _stats_to_row(stats, title='Omega'):
    """Flatten a parse_log stats dict into a per-match DB-style stat row."""
    row = {
        'total': stats['total'],
        'grade_perfect': stats['grades']['#'],
        'grade_positive': stats['grades']['+'],
        'grade_regular': stats['grades']['!'],
        'grade_error': stats['grades']['-'],
        'match_title': title,
        'match_stem': '01_omega',
        'rating': 7.0,
    }
    for action in ACTIONS:
        a_lower = action.lower()
        row[f'{a_lower}_tot'] = stats['actions'][action]['tot']
        row[f'{a_lower}_good'] = stats['actions'][action]['good']
        for grade, prefix in _GRADE_PREFIXES:
            row[f'{prefix}_{a_lower}'] = stats['grade_count'][grade][action]
    return row


def _action_grid(html):
    return re.search(
        r'<div class="action-grid action-grid--summary">(.*?</div>)</div>', html, re.S
    ).group(1)


def _pill(name, count, pct, nota):
    tier = _rating_tier(nota)
    pill_class = f'action-pill action-pill--{tier}'
    return (
        f'<div class="{pill_class}" data-tier="{tier}">'
        f'<span class="action-name">{name}</span>'
        f'<span class="action-count">{count}</span>'
        f'<span class="action-pct">{pct}</span>'
        f'<span class="rating-pill" data-tier="{tier}" {NOTA_TOOLTIP}>{nota}</span>'
        '</div>'
    )


def test_omega_action_pills_preserve_positive_count_percent_nota_and_grade_mix():
    html = build_card_html('#7', _omega_player_seven_stats(), 7.0)

    assert (
        '<div class="card-header"><span class="player-number">#7</span>'
        '<span class="rating-pill" data-tier="mid">7.0</span></div>'
    ) in html
    assert (
        '<div class="action-title">Acciones positivas (#/+) / Total · % · Nota</div>'
        '<div class="action-grid action-grid--summary">'
    ) in html
    assert _pill('Ataque', '5/7', '71%', 6.3) in _action_grid(html)
    assert 'action-summary-table' not in html and '<caption>' not in html
    assert 'Efectividad por Acción' not in html
    assert 'Resumen por Calidad y Acción' in html
    assert '<td class="highlight-good">5</td>' in html
    assert '>5.8</td>' not in html


def test_action_pills_cover_all_actions_and_block_exception():
    parsed = parse_log('S# S+ R! R- E+ E- A# A- D+ D- B#')
    html = build_card_html('Equipo', parsed['team'], 7.0)
    grid = _action_grid(html)

    assert re.findall(r'<span class="action-name">(.*?)</span>', grid) == [
        'Saque',
        'Recepción',
        'Acomodo',
        'Ataque',
        'Defensa',
        'Bloqueo',
    ]
    assert grid.count('<div class="action-pill') == 6
    assert _pill('Bloqueo', '1/1', '100%', 10.0) in grid
    assert _pill('Recepción', '0/2', '0%', 5.0) in grid
    assert '<tr><td>Recepción</td>' in html
    assert 'Recepción de Saque' not in html
    assert 'escala fija' in grid


def test_action_pill_tier_follows_nota_not_positive_percentage():
    cases = (
        ('7S+ 7S+ 7S+ 7S+ 7S+ 7S+ 7S+', 'Saque', '7/7', '100%', '7.1', 'mid'),
        ('B#', 'Bloqueo', '1/1', '100%', '10.0', 'high'),
        ('A-', 'Ataque', '0/1', '0%', '5.0', 'low'),
        ('A+ A+ A+ A! A! A! A!', 'Ataque', '3/7', '43%', '6.0', 'mid'),
        ('A# A# A#', 'Ataque', '3/3', '100%', '8.0', 'high'),
    )
    for log, name, count, pct, nota, tier in cases:
        parsed = parse_log(log)
        html = build_card_html('Equipo', parsed['team'], 7.0)
        grid = _action_grid(html)
        match = re.search(
            rf'<div class="action-pill action-pill--{tier}" data-tier="{tier}">'
            rf'<span class="action-name">{name}</span>'
            rf'<span class="action-count">{count}</span>'
            rf'<span class="action-pct">{pct}</span>'
            rf'<span class="rating-pill" data-tier="{tier}" {NOTA_TOOLTIP}>{nota}</span>'
            r'</div>',
            grid,
        )
        assert match, f'Expected {tier} outer and Nota tiers for {log}'


def test_card_pages_explain_short_reception_label_once():
    parsed = parse_log('7R# 7R+ 7R! 7R- 7R+')
    row = _stats_to_row(parsed['players']['7'])
    player = render_player_season_page(
        '7', [row], [7.2], '23/11/2026', {'7': 'OH'}, {'7': 'Gio'}, 'Nova', 'Copa'
    )
    team = render_team_season_page([_stats_to_row(parsed['team'])], '23/11/2026', 'Nova', 'Copa')
    match = render_match_page('Nova vs Omega', parsed, '23/11/2026')
    explanation = (
        '<p class="action-footnote">Recepción: recepción del saque rival. '
        'Defensa: defensa del resto de balones del rival (ataques y balones libres).</p>'
    )
    for html in (match, player, team):
        assert 'Recepción*' not in html
        assert html.count('class="action-footnote"') == 1
        assert html.index(explanation) > html.rindex('<table class="summary-table">')
    for html in (player, team):
        assert 'Recepción de Saque - Toques positivos' in html


def test_action_pills_empty_state_does_not_invent_pills():
    parsed = parse_log('')
    html = build_card_html('Equipo', parsed['team'], 0.0)
    assert (
        '<div class="action-grid action-grid--summary">'
        '<span class="action-empty">Sin acciones registradas</span></div>'
    ) in html
    assert 'action-pill' not in html


def test_complementary_series_are_partitioned_and_zero_attempts_are_null():
    grade_groups = [
        (3, 2, 1, 4),
        (5, 0, 1, 4),
        (1, 1, 3, 5),
        (0, 0, 0, 0),
    ]
    rows = []
    for perfect, positive, regular, error in grade_groups:
        log = ' '.join(
            [f'{perfect}A#'] * perfect
            + [f'{positive}A+'] * positive
            + [f'{regular}A!'] * regular
            + [f'{error}A-'] * error
        )
        rows.append(_stats_to_row(parse_log(log)['team']))

    html = _action_efficiency_charts(
        rows, _json_for_script(['#1', 'Cambio + a #', 'Rival <&"']), 'fixture'
    )
    datasets = re.search(r'datasets: \[(.*?)\n          \]', html, re.S).group(1)
    assert datasets.count("label: '") == 2
    assert "label: 'Positivas (#/+)'" in datasets
    assert "label: 'Regulares y errores (!/-)'" in datasets
    assert re.search(r'data: \[50, 50, 20, null\]', datasets)
    assert re.search(r'data: \[50, 50, 80, null\]', datasets)
    assert datasets.count('spanGaps: false') == 2
    assert 'fill: false' in datasets and datasets.count('tension: 0.3') == 2
    assert datasets.count("cubicInterpolationMode: 'monotone'") == 2
    assert "pointStyle: 'circle'" in datasets and "pointStyle: 'rectRot'" in datasets
    assert 'positiveCounts = [5, 5, 2, null]' in html
    assert 'otherCounts = [5, 5, 8, null]' in html
    assert 'totals = [10, 10, 10, null]' in html
    assert 'chart-test' not in html
    assert "getPropertyValue('--success')" in html
    assert "getPropertyValue('--danger')" in html
    assert "getPropertyValue('--text-main')" in html
    assert "chart._themeLegendToken = '--text-main'" in html
    assert "const chart = new Chart(document.getElementById('fixture-a')" in html
    assert 'window.registerSeasonChart(chart);' in html


def test_chart_json_escapes_markup_and_script_separators():
    label = 'Rival </script> "&<\u2028'
    encoded = _json_for_script([label])
    assert '</script>' not in encoded
    assert '\\u003c/script\\u003e' in encoded
    assert '\\u0026' in encoded
    assert '\\u2028' in encoded
    assert json.loads(encoded) == [label]


def test_player_and_opponent_labels_are_safe_in_chart_scripts():
    player_name = 'Gio </script> & "quote"'
    opponent = 'Rival </script> & "Final"'
    row = _stats_to_row(_omega_player_seven_stats(), f'Nova vs {opponent}')
    html = render_player_season_page(
        '7',
        [row],
        [7.2],
        '23/11/2026',
        {'7': 'OH'},
        {'7': player_name},
        'Nova',
        'Copa',
    )

    assert player_name not in html
    assert opponent not in html
    assert 'Gio &lt;/script&gt; &amp; &quot;quote&quot;' in html
    assert 'Rival &lt;/script&gt; &amp; &quot;Final&quot;' in html
    assert '\\u003c/script\\u003e \\u0026' in html
    assert 'label: "Gio \\u003c/script\\u003e \\u0026 \\"quote\\""' in html
    assert "window.registerSeasonChart(new Chart(document.getElementById('chart-rating')" in html
    assert re.search(
        r"const chart = new Chart\(document\.getElementById\('chart-action-a'\)"
        r'(?:(?!</script>).)*window\.registerSeasonChart\(chart\);',
        html,
        re.S,
    )


def test_omega_season_trend_heading_keeps_positive_rate_and_nota_distinct():
    row = _stats_to_row(_omega_player_seven_stats())
    html = _action_efficiency_charts([row], '["Omega"]', 'chart-test')
    assert 'Ataque - Toques positivos (#/+) · 71% · Nota 6.3' in html
    assert 'Ataque - Eficiencia' not in html
    assert 'Resumen por Calidad y Acción' not in html
