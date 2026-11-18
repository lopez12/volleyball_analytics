"""Regression tests for the rendered per-action positive-rate and Nota labels."""

from pathlib import Path

from analytics import ACTIONS, parse_log
from renderer import _GRADE_PREFIXES, _action_efficiency_charts, build_card_html

OMEGA_LOG = Path(__file__).parents[1] / 'teams/nova/atlas-chapalita-cup-2026/matches/07_omega.txt'
NOTA_TOOLTIP = (
    'title="Nota: promedio de los grados de esta acción en una escala fija, '
    'ajustado hacia el centro cuando hay pocos intentos; '
    'desglose en Resumen por Calidad y Acción"'
)


def _omega_player_seven_stats():
    parsed = parse_log(OMEGA_LOG.read_text(encoding='utf-8'))
    return parsed['players']['7']


def _stats_to_row(stats):
    """Flatten a parse_log stats dict into a per-match DB-style stat row."""
    row = {
        'total': stats['total'],
        'grade_perfect': stats['grades']['#'],
        'grade_positive': stats['grades']['+'],
        'grade_regular': stats['grades']['!'],
        'grade_error': stats['grades']['-'],
    }
    for action in ACTIONS:
        a_lower = action.lower()
        row[f'{a_lower}_tot'] = stats['actions'][action]['tot']
        row[f'{a_lower}_good'] = stats['actions'][action]['good']
        for grade, prefix in _GRADE_PREFIXES:
            row[f'{prefix}_{a_lower}'] = stats['grade_count'][grade][action]
    return row


def test_omega_action_pill_explains_positive_rate_and_nota():
    html = build_card_html('#7', _omega_player_seven_stats(), 7.0)

    assert 'Acciones positivas (#/+) / Total · % · Nota' in html
    assert 'Efectividad por Acción' not in html
    assert '<span class="action-count">5/7</span>' in html
    assert '<span class="action-pct">71%</span>' in html
    assert NOTA_TOOLTIP in html
    assert '<span class="action-rating" style="color:#ca8a04;" ' in html
    assert '>6.3</span>' in html
    assert '>5.8</span>' not in html
    assert 'Resumen por Calidad y Acción' in html


def test_omega_season_trend_heading_uses_positive_rate_and_new_nota():
    row = _stats_to_row(_omega_player_seven_stats())
    html = _action_efficiency_charts([row], '["Omega"]', 'chart-test')

    assert 'Ataque - Acciones positivas (#/+) · 71% · Nota 6.3' in html
    assert 'Ataque - Eficiencia' not in html
