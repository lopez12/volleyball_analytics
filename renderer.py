"""Volleyball Analytics - HTML rendering engine.

Contains all HTML card builders and page renderers.
No knowledge of SQLite or file I/O.
"""

import json
import re
import statistics

from analytics import (
    ACTIONS, FULL_NAMES, GRADES,
    PLAYER_POSITIONS, POSITION_LABELS, PLAYER_NAMES,
    calculate_rating, calculate_phase_stats, calculate_point_stats,
)

# ---------------------------------------------------------------------------
# Collapsible section helper
# ---------------------------------------------------------------------------

_COLLAPSIBLE_JS = """<script>
function toggleSection(el) {
  el.classList.toggle('collapsed');
  var content = el.nextElementSibling;
  content.classList.toggle('collapsed');
}
</script>"""


# ---------------------------------------------------------------------------
# Shared layout helpers
# ---------------------------------------------------------------------------


def _back_link(href='index.html', label='← Inicio'):
    """Return a top-of-page back-link div."""
    return (
        f'<div style="margin-bottom:12px;">'
        f'<a href="{href}" style="color:var(--primary);text-decoration:none;'
        f'font-weight:600;font-size:0.88rem;">{label}</a>'
        f'</div>'
    )


def _back_nav(href='index.html', label='← Inicio'):
    """Return a prominent centered bottom navigation button."""
    return (
        f'<div style="margin-top:24px;text-align:center;">'
        f'<a href="{href}" style="display:inline-block;padding:10px 22px;'
        f'background:var(--primary);color:white;border-radius:8px;'
        f'text-decoration:none;font-weight:600;">{label}</a>'
        f'</div>'
    )


# Shared scoring metric descriptions used in match cards and team season trend.
_SCORING_DESCRIPTIONS = {
    'bp': '% Puntos ganados con posesión (saque propio).',
    'so': '% Puntos ganados recibiendo (saque rival).',
}


def _section(title, content_html, collapsed=False):
    """Wrap a section title and its content in a collapsible container."""
    t_cls = 'section-title collapsed' if collapsed else 'section-title'
    c_cls = 'section-content collapsed' if collapsed else 'section-content'
    return (
        f'<h3 class="{t_cls}" onclick="toggleSection(this)">'
        f'<span class="section-title-text">{title}</span>'
        f'<span class="chevron">▾</span>'
        f'</h3>'
        f'<div class="{c_cls}">{content_html}</div>'
    )


# Actions that are less relevant per position and should start collapsed
_POSITION_COLLAPSED_ACTIONS = {
    'L':   {'S', 'A', 'B', 'E'},   # Libero: Reception + Defense are primary
    'MB':  {'R', 'D', 'E'},          # Middle Blocker: Attack + Block + Serve primary
    'OH':  {'B', 'E'},              # Outside Hitter: Attack + Reception primary
    'OPP': {'R', 'B'},              # Opposite: Attack focused
    'S':   {'A', 'R', 'B'},         # Setter: Set is primary; no blocking
    'U':   set(),                   # Universal: nothing collapsed
}

def _action_efficiency_charts(match_stats, chart_labels_json, canvas_prefix, collapsed_actions=None):
    """Build collapsible dual-line (Perfecto / Positivo) efficiency charts for each action.

    Args:
        match_stats (list[dict]): Per-match stat rows (player or team).
        chart_labels_json (str): JSON-encoded list of match label strings.
        canvas_prefix (str): Prefix for canvas element IDs (e.g. 'chart-action' or 'chart-team-action').
        collapsed_actions (set | None): Action codes whose section starts collapsed. Defaults to none.

    Returns:
        str: HTML string with one collapsible section per action.
    """
    if collapsed_actions is None:
        collapsed_actions = set()
    charts_html = ''
    for action in ACTIONS:
        a_lower = action.lower()
        season_total = sum(m[f'{a_lower}_tot'] for m in match_stats)
        if season_total < 5:
            continue
        positive_pcts = []
        perfect_pcts = []
        for m in match_stats:
            tot = m[f'{a_lower}_tot']
            good = m[f'{a_lower}_good']
            perf = m[f'perfect_{a_lower}']
            positive_pcts.append(round((good / tot) * 100) if tot > 0 else None)
            perfect_pcts.append(round((perf / tot) * 100) if tot > 0 else None)
        positive_json = json.dumps(positive_pcts)
        perfect_json = json.dumps(perfect_pcts)
        action_name = FULL_NAMES[action]
        canvas_id = f'{canvas_prefix}-{a_lower}'
        chart_html = f'''
    <div class="stat-card" style="margin-top:8px;">
      <div class="card-body"><canvas id="{canvas_id}" height="200"></canvas></div>
    </div>
    <script>
    (function() {{
      const labels = {chart_labels_json};
      new Chart(document.getElementById('{canvas_id}'), {{
        type: 'line',
        data: {{
          labels: labels,
          datasets: [
            {{ label: 'Positivo (#+ %)', data: {positive_json}, borderColor: '#22c55e', backgroundColor: 'rgba(34,197,94,0.08)', fill: true, tension: 0.3, spanGaps: true }},
            {{ label: 'Perfecto (# %)',  data: {perfect_json},  borderColor: '#6366f1', backgroundColor: 'rgba(99,102,241,0.12)', fill: true, tension: 0.3, spanGaps: true }}
          ]
        }},
        options: {{
          responsive: true,
          interaction: {{ mode: 'index', intersect: false }},
          scales: {{ y: {{ min: 0, max: 100, ticks: {{ callback: v => v + '%' }} }} }},
          plugins: {{
            legend: {{ display: true, position: 'bottom', labels: {{ boxWidth: 12, font: {{ size: 11 }} }} }},
            tooltip: {{ callbacks: {{ label: ctx => ctx.dataset.label + ': ' + (ctx.parsed.y !== null ? ctx.parsed.y + '%' : '-') }} }}
          }}
        }}
      }});
    }})();
    </script>'''
        charts_html += _section(
            f'{action_name} - Eficiencia',
            chart_html,
            collapsed=(action in collapsed_actions),
        )
    return charts_html


# Ordered grade symbol → DB column prefix pairs, used for cross-tab aggregation.
_GRADE_PREFIXES = (('#', 'perfect'), ('+', 'positive'), ('!', 'regular'), ('-', 'error'))


def _aggregate_season_data(match_stats):
    """Aggregate per-match stat rows into a season totals dict for build_card_html.

    Args:
        match_stats (list[dict]): Per-match stat rows (player or team).

    Returns:
        dict: Keys 'total', 'grades', 'actions', 'grade_count' — compatible with build_card_html.
    """
    grades = {'#': 0, '+': 0, '!': 0, '-': 0}
    grade_count = {g: {a: 0 for a in ACTIONS} for g in GRADES}
    actions = {a: {'tot': 0, 'good': 0} for a in ACTIONS}
    total = 0
    for m in match_stats:
        total += m['total']
        grades['#'] += m['grade_perfect']
        grades['+'] += m['grade_positive']
        grades['!'] += m['grade_regular']
        grades['-'] += m['grade_error']
        for action in ACTIONS:
            a_lower = action.lower()
            actions[action]['tot'] += m[f'{a_lower}_tot']
            actions[action]['good'] += m[f'{a_lower}_good']
            for grade, prefix in _GRADE_PREFIXES:
                grade_count[grade][action] += m[f'{prefix}_{a_lower}']
    return {'total': total, 'grades': grades, 'actions': actions, 'grade_count': grade_count}


# ---------------------------------------------------------------------------
# HTML helpers
# ---------------------------------------------------------------------------


def _pct(n, total):
    """Calculate an integer percentage, guarding against division by zero.

    Args:
        n (int | float): The part value (numerator).
        total (int | float): The whole value (denominator).

    Returns:
        int: Rounded integer percentage in the range 0–100.
            Returns 0 if `total` is 0.
    """
    return round((n / total) * 100) if total > 0 else 0


def _rating_color(rating):
    """Return a CSS hex colour string that encodes the performance rating tier.

    Tiers:
        rating >= 8.0  →  '#16a34a'  (green  — high performance)
        rating >= 6.0  →  '#ca8a04'  (amber  — average performance)
        rating <  6.0  →  '#dc2626'  (red    — below-average performance)

    Args:
        rating (float): Performance rating on the 1–10 scale from calculate_rating().

    Returns:
        str: A CSS-compatible hex colour string.
    """
    if rating >= 8:
        return '#16a34a'
    if rating >= 6:
        return '#ca8a04'
    return '#dc2626'

# ---------------------------------------------------------------------------
# Card HTML builders
# ---------------------------------------------------------------------------


def build_card_html(title, data, rating, extra_class=''):
    """Build and return the full HTML string for a single player or team statistics card.

    The card is composed of four sections:
        1. Header: displays the title (e.g. '#7' or 'Equipo') and a colour-coded
           rating badge using _rating_color().
        2. Grade bars: four metric rows (Perfecto, Positivo, Regular, Error) showing
           each grade's share of total actions as a percentage bar.
        3. Action-efficiency pills: one pill per action type that has at least one
           occurrence, showing 'good/total'. Pills are highlighted green if
           efficiency == 100 % or red if efficiency < 40 %.
        4. Grade × action cross-tab table: rows are action types, columns are grades.
           The highest value in the good columns (# and +) is highlighted green;
           the highest in Regular is highlighted amber; the highest in Error is red.

    Args:
        title (str): Display label for the card header, e.g. '#7' or 'Equipo'.
        data (dict): Statistics dictionary from parse_log() or _row_to_stats().
            Must contain 'total', 'grades', 'actions', and 'grade_count'.
        rating (float): Pre-calculated performance rating from calculate_rating().
        extra_class (str, optional): Additional CSS class(es) appended to the
            card's root <div>, e.g. 'team-summary-card'. Defaults to ''.

    Returns:
        str: A self-contained HTML string for the card element.
    """
    total = data['total']
    grades = data['grades']
    actions = data['actions']
    grade_count = data['grade_count']

    perfect_pct = _pct(grades['#'], total)
    positive_pct = _pct(grades['+'], total)
    regular_pct = _pct(grades['!'], total)
    error_pct = _pct(grades['-'], total)
    r_color = _rating_color(rating)

    # Action pills
    pills = []
    for action in ACTIONS:
        a = actions[action]
        if a['tot'] == 0:
            continue
        eff = a['good'] / a['tot']
        pill_class = 'high-perf' if eff == 1.0 else (
            'low-perf' if eff < 0.4 else '')
        name = FULL_NAMES[action]
        good = a['good']
        tot = a['tot']
        pills.append(
            f'<div class="action-pill {pill_class}">'
            f'<span class="action-name">{name}</span>'
            f'<span class="action-count">{good}/{tot}</span>'
            f'</div>'
        )
    pills_html = ''.join(pills)

    # Summary table – highlight max values per column
    max_good = max(
        (max(grade_count['#'][a], grade_count['+'][a]) for a in ACTIONS), default=0)
    max_regular = max((grade_count['!'][a] for a in ACTIONS), default=0)
    max_bad = max((grade_count['-'][a] for a in ACTIONS), default=0)

    rows = []
    for action in ACTIONS:
        perfect = grade_count['#'][action]
        positive = grade_count['+'][action]
        regular = grade_count['!'][action]
        error = grade_count['-'][action]
        action_name = FULL_NAMES[action]
        pc = 'highlight-good' if perfect == max_good and max_good > 0 else ''
        posc = 'highlight-good' if positive == max_good and max_good > 0 else ''
        rc = 'highlight-regular' if regular == max_regular and max_regular > 0 else ''
        ec = 'highlight-bad' if error == max_bad and max_bad > 0 else ''
        rows.append(
            f'<tr><td>{action_name}</td>'
            f'<td class="{pc}">{perfect}</td>'
            f'<td class="{posc}">{positive}</td>'
            f'<td class="{rc}">{regular}</td>'
            f'<td class="{ec}">{error}</td></tr>'
        )
    rows_html = ''.join(rows)

    card_class = f'stat-card {extra_class}'.strip()
    return (
        f'<div class="{card_class}">'
        f'<div class="card-header">'
        f'<span class="player-number">{title}</span>'
        f'<span class="player-rating" style="color:{r_color};background:white;">{rating}</span>'
        f'</div>'
        f'<div class="card-body">'
        f'<div class="metric-row"><span>Perfecto (#)</span><span style="color:var(--success);">{perfect_pct}%</span></div>'
        f'<div class="bar-container"><div class="bar-fill" style="width:{perfect_pct}%;background-color:var(--success);"></div></div>'
        f'<div class="metric-row"><span>Positivo (+)</span><span style="color:var(--primary);">{positive_pct}%</span></div>'
        f'<div class="bar-container"><div class="bar-fill" style="width:{positive_pct}%;background-color:var(--primary);"></div></div>'
        f'<div class="metric-row"><span>Regular (!)</span><span style="color:var(--warning);">{regular_pct}%</span></div>'
        f'<div class="bar-container"><div class="bar-fill" style="width:{regular_pct}%;background-color:var(--warning);"></div></div>'
        f'<div class="metric-row"><span>Error (-)</span><span style="color:var(--danger);">{error_pct}%</span></div>'
        f'<div class="bar-container"><div class="bar-fill" style="width:{error_pct}%;background-color:var(--danger);"></div></div>'
        f'<div class="action-section">'
        f'<div class="action-title">Efectividad por Acción (Buenos/Total)</div>'
        f'<div class="action-grid">{pills_html}</div>'
        f'</div>'
        f'<div class="action-section" style="margin-top:16px;">'
        f'<div class="action-title" style="margin-bottom:8px;">Resumen por Calidad y Acción</div>'
        f'<div style="overflow-x:auto;">'
        f'<table class="summary-table">'
        f'<thead><tr><th></th><th>Perfecto</th><th>Positivo</th><th>Regular</th><th>Error</th></tr></thead>'
        f'<tbody>{rows_html}</tbody>'
        f'</table></div></div>'
        f'</div></div>'
    )


def build_phase_card_html(phase_stats):
    """Build and return the HTML string for the 'Game Phase Efficiency' summary card.

    Renders one labelled metric row and progress bar for each of the three phases
    that has at least one attempt recorded:
        - Side-Out (Pase Bueno): attacks following a quality reception (R# / R+).
        - Side-Out (Pase Regular): attacks following a poor reception (R!).
        - Transición: attacks following a defensive dig (D).

    Bar colour thresholds (kill %):
        >= 50 %  →  green  (var(--success))
        >= 35 %  →  blue   (var(--primary))
        <  35 %  →  red    (var(--danger))

    If no phase has any attempts, a fallback 'No hay secuencias suficientes' message
    is shown instead of bars.

    Args:
        phase_stats (dict): Output of calculate_phase_stats() or get_phase_stats_from_db().
            Keys: 'so_good', 'so_bad', 'trans', each mapping to
            {'attempts': int, 'kills': int}.

    Returns:
        str: A self-contained HTML string for the phase-efficiency card element.
    """
    phases = [
        ('so_good', 'Side-Out (Pase Bueno)'),
        ('so_bad',  'Side-Out (Pase Regular)'),
        ('trans',   'Transición'),
    ]
    parts = []
    for key, label in phases:
        s = phase_stats[key]
        kills = s['kills']
        attempts = s['attempts']
        if attempts == 0:
            continue
        p = _pct(kills, attempts)
        bar_color = 'var(--success)' if p >= 50 else (
            'var(--primary)' if p >= 35 else 'var(--danger)')
        parts.append(
            f'<div class="metric-row" style="margin-top:12px;">'
            f'<span>{label} <span style="font-weight:normal;color:#6b7280;font-size:0.8em;">({kills}/{attempts} pts)</span></span>'
            f'<span style="color:{bar_color};">{p}%</span></div>'
            f'<div class="bar-container"><div class="bar-fill" style="width:{p}%;background-color:{bar_color};"></div></div>'
        )
    content = ''.join(parts) or (
        '<div style="padding:10px;text-align:center;color:#9ca3af;font-size:0.8rem;">'
        'No hay secuencias suficientes</div>'
    )
    return (
        '<div class="stat-card team-summary-card" style="margin-top:10px;">'
        '<div class="card-header"><span class="player-number">Eficacia por Fase de Juego</span></div>'
        '<div class="card-body">'
        '<div style="margin-bottom:15px;font-size:0.85rem;color:#4b5563;background:#f8fafc;'
        'padding:10px;border-radius:6px;border:1px solid #e2e8f0;line-height:1.4;">'
        '<strong>Side-Out:</strong> Capacidad de ganar puntos tras recibir saque.<br>'
        '<strong>Transición:</strong> Capacidad de ganar puntos tras defender un remate.'
        '</div>'
        '<div class="action-section" style="border-top:none;padding-top:0;">'
        '<div class="action-title">Kill % por Situación</div>'
        f'{content}'
        '</div></div></div>'
    )


def build_scoring_card_html(point_stats):
    """Build and return the HTML string for the 'Point Performance' summary card.

    Displays two metrics as labelled rows with colour-coded progress bars:
        - Break Point %: percentage of points won when the team is serving.
        - Side-Out %: percentage of points won when the team is receiving.

    Colour thresholds:
        Break Point:  >= 40 %  green, >= 30 %  blue, < 30 %  red.
        Side-Out:     >= 60 %  green, >= 50 %  blue, < 50 %  red.

    Each label includes a secondary annotation showing raw counts (won/total).

    Args:
        point_stats (dict): Output of calculate_point_stats() or get_point_stats_from_db().
            Must contain:
                'bp' (dict): {'total': int, 'won': int} for Break Point rallies.
                'so' (dict): {'total': int, 'won': int} for Side-Out rallies.

    Returns:
        str: A self-contained HTML string for the scoring-performance card element.
    """
    bp = point_stats['bp']
    so = point_stats['so']
    bp_won = bp['won']
    bp_total = bp['total']
    so_won = so['won']
    so_total = so['total']
    bp_pct = _pct(bp_won, bp_total)
    so_pct = _pct(so_won, so_total)
    bp_color = 'var(--success)' if bp_pct >= 40 else (
        'var(--primary)' if bp_pct >= 30 else 'var(--danger)')
    so_color = 'var(--success)' if so_pct >= 60 else (
        'var(--primary)' if so_pct >= 50 else 'var(--danger)')
    return (
        '<div class="stat-card team-summary-card" style="margin-top:10px;">'
        '<div class="card-header"><span class="player-number">Rendimiento de Puntos</span></div>'
        '<div class="card-body">'
        '<div style="margin-bottom:15px;font-size:0.85rem;color:#4b5563;background:#f8fafc;'
        'padding:10px;border-radius:6px;border:1px solid #e2e8f0;line-height:1.4;">'
        f'<strong>Break Point:</strong> {_SCORING_DESCRIPTIONS["bp"]}<br>'
        f'<strong>Side-Out:</strong> {_SCORING_DESCRIPTIONS["so"]}'
        '</div>'
        f'<div class="metric-row" style="margin-top:12px;">'
        f'<span>Break Point % <span style="font-weight:normal;color:#6b7280;font-size:0.8em;">({bp_won}/{bp_total} pts)</span></span>'
        f'<span style="color:{bp_color};">{bp_pct}%</span></div>'
        f'<div class="bar-container"><div class="bar-fill" style="width:{bp_pct}%;background-color:{bp_color};"></div></div>'
        f'<div class="metric-row" style="margin-top:12px;">'
        f'<span>Side-Out % <span style="font-weight:normal;color:#6b7280;font-size:0.8em;">({so_won}/{so_total} pts)</span></span>'
        f'<span style="color:{so_color};">{so_pct}%</span></div>'
        f'<div class="bar-container"><div class="bar-fill" style="width:{so_pct}%;background-color:{so_color};"></div></div>'
        '</div></div>'
    )

# ---------------------------------------------------------------------------
# Page rendering
# ---------------------------------------------------------------------------


def format_title(stem):
    """Convert a match log filename stem into a human-readable match title.

    Replaces underscores with spaces, title-cases all words, then corrects
    'Vs' back to lowercase 'vs' to follow standard volleyball naming conventions.

    Example:
        'vodkas_vs_alaba' → 'Vodkas vs Alaba'
        '01_vodkas_vs_alaba' → 'Vodkas vs Alaba'

    Args:
        stem (str): The filename without extension, e.g. 'vodkas_vs_alaba' or
            '01_vodkas_vs_alaba'.

    Returns:
        str: A formatted, human-readable match title.
    """
    clean = re.sub(r'^\d+_', '', stem)
    return clean.replace('_', ' ').title().replace(' Vs ', ' vs ')


def render_match_page(match_title, parsed, generated_date):
    """Render a complete static HTML page for a single match report.

    Assembles the full HTML document with the following sections:
        1. Report header: match title, generation date, and an optional YouTube
           banner with per-set links when 'youtube_urls' is non-empty.
        2. Global summary: three stat cards showing team rating, total actions,
           and perfect-efficiency percentage.
        3. Team actions: team card, phase-efficiency card, and scoring card.
        4. Player detail: one card per player who has at least one recorded action,
           sorted by rating descending.
        5. Navigation link back to the index page.

    Phase and point stats are sourced from rallies when available (live parse path),
    or from the '_phase_stats' / '_point_stats' keys injected by generate.py when
    the parsed dict was reconstructed from the database (no rallies stored).

    Args:
        match_title (str): Human-readable match title, e.g. 'Vodkas vs Alaba'.
        parsed (dict): Output of parse_log() or get_match(), containing:
            'players' (dict): Player number → stats dict.
            'team' (dict): Aggregated team stats dict.
            'rallies' (list): Rally token lists; may be empty when reading from DB.
            'youtube_urls' (list[str]): YouTube URLs for the match.
            '_phase_stats' (dict, optional): Pre-computed phase stats from DB.
            '_point_stats' (dict, optional): Pre-computed point stats from DB.
        generated_date (str): Date string displayed in the header, 'DD/MM/YYYY'.

    Returns:
        str: A complete HTML document string (<!DOCTYPE html> … </html>),
            linking to the shared styles.css stylesheet.
    """
    players = parsed['players']
    team = parsed['team']
    rallies = parsed['rallies']
    youtube_urls = parsed['youtube_urls']

    team_rating = calculate_rating(team)
    total_actions = team['total']
    perfect_pct = _pct(team['grades']['#'], total_actions)

    # YouTube banner
    yt_html = ''
    if youtube_urls:
        links = ''.join(
            f'<a href="{url}" target="_blank" rel="noopener noreferrer" class="youtube-set-link">Set {i + 1}</a>'
            for i, url in enumerate(youtube_urls)
        )
        yt_html = (
            '<div class="youtube-banner" style="display:flex;">'
            '<div class="youtube-banner__label"><span>Ver partido</span></div>'
            f'<div class="youtube-banner__links">{links}</div>'
            '</div>'
        )

    team_card = build_card_html(
        'Equipo', team, team_rating, 'team-summary-card')

    # Use pre-computed stats from DB if rallies are empty
    if rallies:
        phase_stats = calculate_phase_stats(rallies)
        point_stats = calculate_point_stats(rallies)
    else:
        phase_stats = parsed.get('_phase_stats', {
            'so_good': {'attempts': 0, 'kills': 0},
            'so_bad': {'attempts': 0, 'kills': 0},
            'trans': {'attempts': 0, 'kills': 0},
        })
        point_stats = parsed.get('_point_stats', {
            'bp': {'total': 0, 'won': 0},
            'so': {'total': 0, 'won': 0},
        })

    phase_card = build_phase_card_html(phase_stats)
    scoring_card = build_scoring_card_html(point_stats)

    players_sorted = sorted(
        [(num, data, calculate_rating(data))
         for num, data in players.items() if data['total'] > 0],
        key=lambda x: x[2],
        reverse=True,
    )
    player_cards = ''.join(build_card_html(
        f'#{num}', data, rating) for num, data, rating in players_sorted)

    return f"""<!DOCTYPE html>
<html lang="es">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>{match_title} - Volleyball Analytics</title>
  <link rel="stylesheet" href="styles.css">
  {_COLLAPSIBLE_JS}
</head>
<body>
<div class="container">
  {_back_link('matches.html', '← Todos los partidos')}
  <div class="report-header">
    <h1>Reporte: {match_title}</h1>
    <p>Generado: {generated_date}</p>
    {yt_html}
  </div>

  {_section('Resumen Global', f'''<div class="general-stats">
    <div class="stat-card"><div class="stat-value">{team_rating}</div><div class="stat-label">Rating Equipo</div></div>
    <div class="stat-card"><div class="stat-value">{total_actions}</div><div class="stat-label">Acciones Totales</div></div>
    <div class="stat-card"><div class="stat-value" style="color:var(--success)">{perfect_pct}%</div><div class="stat-label">Eficacia Perfecta</div></div>
  </div>''')}

  {_section('Acciones de Equipo', f'''<div class="players-grid">
    {team_card}
    {phase_card}
    {scoring_card}
  </div>''')}

  {_section('Detalle por Jugador', f'<div class="players-grid">{player_cards}</div>')}

  {_back_nav('matches.html', '← Todos los partidos')}
</div>
</body>
</html>"""


def render_index_page(matches, generated_date, player_summaries=None, team_season_summary=None):
    """Render the static HTML index page as a navigation hub.

    Sections (top to bottom): Team Season, Players, Matches.

    Args:
        matches (list[dict]): Ordered list of match metadata dicts.
        generated_date (str): Date string displayed in the page header.
        player_summaries (list[dict], optional): Per-player season summary for the Players section.
        team_season_summary (dict, optional): Team season summary for the Team Season link.

    Returns:
        str: A complete HTML document string.
    """
    # --- Hero stats ---
    if team_season_summary:
        ts = team_season_summary
        r_color = _rating_color(ts['rating'])
        wins = ts.get('wins', 0)
        losses = ts.get('losses', 0)
        rating_val = ts['rating']
        matches_played = ts['matches_played']
    else:
        r_color = '#6b7280'
        wins = 0
        losses = 0
        rating_val = 0.0
        matches_played = len(matches)

    # --- Tile data ---
    player_count = len(player_summaries) if player_summaries else 0
    top_player_html = ''
    if player_summaries:
        top = player_summaries[0]
        top_player_html = f'MVP: <strong>{top["name"]}</strong> ({top["rating"]})'

    last_match_html = ''
    if matches:
        lm = matches[-1]
        lm_r_color = _rating_color(lm['rating'])
        lm_result = lm.get('result')
        if lm_result == 'W':
            lm_badge = '<span class="result-badge result-win">Victoria</span>'
        elif lm_result == 'L':
            lm_badge = '<span class="result-badge result-loss">Derrota</span>'
        else:
            lm_badge = ''
        last_match_html = (
            f'<div class="hub-last-match">'
            f'<span class="hub-last-match-label">Último Partido</span>'
            f'<span class="hub-last-match-title">{lm["title"]}</span>'
            f'{lm_badge}'
            f'<span class="hub-last-match-rating" style="color:{lm_r_color};">{lm["rating"]}</span>'
            f'<a href="{lm["file"]}">Ver Reporte →</a>'
            f'</div>'
        )

    # Last match info for tile
    last_match_tile_stat = ''
    if matches:
        lm = matches[-1]
        lm_result = lm.get('result')
        result_text = 'Victoria' if lm_result == 'W' else ('Derrota' if lm_result == 'L' else '-')
        opponent = lm['title'].replace('Vodkas vs ', '')
        last_match_tile_stat = f'Último: <strong>{result_text}</strong> vs {opponent}'

    return f"""<!DOCTYPE html>
<html lang="es">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>Volleyball Analytics</title>
  <link rel="stylesheet" href="styles.css">
</head>
<body>
<div class="container">
  <div class="hub-hero">
    <h1><span style="-webkit-text-fill-color:initial;">🏐</span> Vodkas - Volleyball Analytics</h1>
    <p class="hub-subtitle">Generado: {generated_date}</p>
    <div class="hub-hero-stats">
      <div class="hub-hero-stat">
        <div class="stat-value" style="color:{r_color};">{rating_val}</div>
        <div class="stat-label">Rating</div>
      </div>
      <div class="hub-hero-stat">
        <div class="stat-value">{wins}W - {losses}L</div>
        <div class="stat-label">Récord</div>
      </div>
      <div class="hub-hero-stat">
        <div class="stat-value">{matches_played}</div>
        <div class="stat-label">Partidos</div>
      </div>
    </div>
  </div>

  <div class="hub-nav">
    <a href="team_season.html" class="hub-tile">
      <span class="hub-tile-icon">📊</span>
      <span class="hub-tile-title">Equipo</span>
      <span class="hub-tile-stat">Rating <strong>{rating_val}</strong> · {wins}W-{losses}L</span>
      <span class="hub-tile-btn">Ver Temporada →</span>
    </a>
    <a href="players.html" class="hub-tile">
      <span class="hub-tile-icon">👥</span>
      <span class="hub-tile-title">Jugadores</span>
      <span class="hub-tile-stat">{player_count} jugadores · {top_player_html}</span>
      <span class="hub-tile-btn">Ver Jugadores →</span>
    </a>
    <a href="matches.html" class="hub-tile">
      <span class="hub-tile-icon">🏐</span>
      <span class="hub-tile-title">Partidos</span>
      <span class="hub-tile-stat">{len(matches)} partidos · {last_match_tile_stat}</span>
      <span class="hub-tile-btn">Ver Partidos →</span>
    </a>
  </div>

  {last_match_html}
</div>
</body>
</html>"""


# ---------------------------------------------------------------------------
# Player Season Page
# ---------------------------------------------------------------------------


def render_player_season_page(player_num, match_stats, team_match_ratings, generated_date):
    """Render a complete season analytics page for a single player.

    Args:
        player_num (str): The player number.
        match_stats (list[dict]): Output of get_player_season_stats().
        team_match_ratings (list[float]): Team rating for each match (same order as match_stats matches).
        generated_date (str): Date string for the header.

    Returns:
        str: Complete HTML document.
    """
    pos_code = PLAYER_POSITIONS.get(player_num, 'U')
    pos_label = POSITION_LABELS.get(pos_code, 'Universal')
    display_name = PLAYER_NAMES.get(player_num, f'#{player_num}')

    # Season aggregations
    ratings = [m['rating'] for m in match_stats]
    season_rating = round(sum(ratings) / len(ratings), 1) if ratings else 0.0
    matches_played = len(match_stats)
    total_actions = sum(m['total'] for m in match_stats)

    best_match = max(match_stats, key=lambda m: m['rating'])
    worst_match = min(match_stats, key=lambda m: m['rating'])

    # Consistency
    if len(ratings) >= 2:
        std_dev = round(statistics.stdev(ratings), 2)
        if std_dev < 0.5:
            consistency_label = 'Consistente'
            consistency_color = 'var(--success)'
        elif std_dev < 1.0:
            consistency_label = 'Moderado'
            consistency_color = 'var(--warning)'
        else:
            consistency_label = 'Variable'
            consistency_color = 'var(--danger)'
    else:
        std_dev = 0.0
        consistency_label = 'N/A'
        consistency_color = '#6b7280'

    # Chart data
    chart_labels = json.dumps([m['match_title'].replace('Vodkas vs ', '') for m in match_stats])
    chart_ratings = json.dumps(ratings)
    chart_team_ratings = json.dumps(team_match_ratings)

    # Action efficiency trends (per match) — each action is its own collapsible section
    collapsed_actions = _POSITION_COLLAPSED_ACTIONS.get(pos_code, set())
    action_charts_html = _action_efficiency_charts(match_stats, chart_labels, 'chart-action', collapsed_actions)

    # Season totals cross-tab
    season_data = _aggregate_season_data(match_stats)
    season_actions = season_data['actions']  # also used for strengths/weaknesses below

    season_card = build_card_html(f'{display_name} - Temporada', season_data, season_rating, 'team-summary-card')

    # Strengths & Improvement Areas
    action_effs = []
    for action in ACTIONS:
        tot = season_actions[action]['tot']
        if tot >= 10:
            eff = round((season_actions[action]['good'] / tot) * 100)
            action_effs.append((FULL_NAMES[action], eff))
    action_effs.sort(key=lambda x: x[1], reverse=True)

    strengths_html = ''
    if action_effs:
        strengths = action_effs[:2]
        weaknesses = action_effs[-2:] if len(action_effs) >= 4 else action_effs[-1:]
        s_items = ''.join(f'<div class="metric-row"><span>{name}</span><span style="color:var(--success);">{eff}%</span></div>' for name, eff in strengths)
        w_items = ''.join(f'<div class="metric-row"><span>{name}</span><span style="color:var(--danger);">{eff}%</span></div>' for name, eff in weaknesses)
        strengths_html = (
            '<div class="stat-card" style="margin-top:16px;">'
            '<div class="card-header"><span class="player-number">Fortalezas y Áreas de Mejora</span></div>'
            '<div class="card-body">'
            '<div class="action-title" style="margin-bottom:8px;">Fortalezas (mayor eficiencia)</div>'
            f'{s_items}'
            '<div class="action-title" style="margin-top:16px;margin-bottom:8px;">Áreas de Mejora (menor eficiencia)</div>'
            f'{w_items}'
            '</div></div>'
        )

    # Match-by-match table
    match_rows = []
    for m in match_stats:
        opponent = m['match_title'].replace('Vodkas vs ', '')
        rating = m['rating']
        r_color = _rating_color(rating)
        perfect_pct = _pct(m['grade_perfect'], m['total'])
        error_pct = _pct(m['grade_error'], m['total'])
        href = f'{m["match_stem"]}.html'
        match_rows.append(
            f'<tr>'
            f'<td><a href="{href}" style="color:var(--primary);text-decoration:none;font-weight:500;">{opponent}</a></td>'
            f'<td style="color:{r_color};font-weight:600;">{rating}</td>'
            f'<td>{m["total"]}</td>'
            f'<td style="color:var(--success);">{perfect_pct}%</td>'
            f'<td style="color:var(--danger);">{error_pct}%</td>'
            f'</tr>'
        )
    match_table_html = ''.join(match_rows)

    r_color = _rating_color(season_rating)

    return f"""<!DOCTYPE html>
<html lang="es">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>{display_name} - Temporada - Volleyball Analytics</title>
  <link rel="stylesheet" href="styles.css">
  <script src="https://cdn.jsdelivr.net/npm/chart.js"></script>
  {_COLLAPSIBLE_JS}
</head>
<body>
<div class="container">
  {_back_link('players.html', '← Todos los jugadores')}
  <div class="report-header">
    <h1>{display_name} <span class="position-badge">{pos_label}</span></h1>
    <p>Temporada - Generado: {generated_date}</p>
  </div>

  {_section('Resumen de Temporada', f'''<div class="general-stats">
    <div class="stat-card"><div class="stat-value" style="color:{r_color}">{season_rating}</div><div class="stat-label">Rating Temporada</div></div>
    <div class="stat-card"><div class="stat-value">{matches_played}</div><div class="stat-label">Partidos Jugados</div></div>
    <div class="stat-card"><div class="stat-value">{total_actions}</div><div class="stat-label">Acciones Totales</div></div>
    <div class="stat-card"><div class="stat-value" style="color:{consistency_color};font-size:1.2rem;word-break:break-word;">{consistency_label}<span style="display:block;font-size:0.75em;color:#6b7280;font-weight:normal;">σ={std_dev}</span></div><div class="stat-label" title="Desviación estándar del rating entre partidos. σ &lt; 0.5: Consistente | σ &lt; 1.0: Moderado | σ ≥ 1.0: Variable">Consistencia ⓘ</div></div>
  </div>
  <div class="general-stats" style="margin-top:12px;">
    <div class="stat-card"><div class="stat-value" style="color:var(--success);">{best_match["rating"]}</div><div class="stat-label">Mejor: {best_match["match_title"].replace("Vodkas vs ", "")}</div></div>
    <div class="stat-card"><div class="stat-value" style="color:var(--danger);">{worst_match["rating"]}</div><div class="stat-label">Peor: {worst_match["match_title"].replace("Vodkas vs ", "")}</div></div>
  </div>''')}

  {_section('Progresión de Rating', f'''<div class="stat-card"><div class="card-body"><canvas id="chart-rating" height="250"></canvas></div></div>
  <script>
  (function() {{
    new Chart(document.getElementById('chart-rating'), {{
      type: 'line',
      data: {{
        labels: {chart_labels},
        datasets: [
          {{ label: '{display_name}', data: {chart_ratings}, borderColor: '#6366f1', backgroundColor: 'rgba(99,102,241,0.1)', fill: true, tension: 0.3 }},
          {{ label: 'Equipo', data: {chart_team_ratings}, borderColor: '#9ca3af', borderDash: [5,5], fill: false, tension: 0.3 }}
        ]
      }},
      options: {{
        responsive: true,
        interaction: {{ mode: 'index', intersect: false }},
        scales: {{ y: {{ min: 4, max: 10 }} }},
        plugins: {{
          annotation: {{ annotations: {{ target: {{ type: 'line', yMin: 7, yMax: 7, borderColor: '#22c55e', borderDash: [3,3], borderWidth: 1 }} }} }},
          tooltip: {{ callbacks: {{ label: ctx => ctx.dataset.label + ': ' + ctx.parsed.y }} }}
        }}
      }}
    }});
  }})();
  </script>''')}

  {action_charts_html}

  {_section('Estadísticas Acumuladas', f'<div class="players-grid">{season_card}{strengths_html}</div>')}

  {_section('Detalle por Partido', f'''<div style="overflow-x:auto;">
    <table class="summary-table">
      <thead><tr><th>Rival</th><th>Rating</th><th>Acciones</th><th>Perfecto %</th><th>Error %</th></tr></thead>
      <tbody>{match_table_html}</tbody>
    </table>
  </div>''')}

  {_back_nav('players.html', '← Todos los jugadores')}
</div>
</body>
</html>"""


# ---------------------------------------------------------------------------
# Team Season Page
# ---------------------------------------------------------------------------


def render_team_season_page(team_stats, generated_date):
    """Render a complete season analytics page for the team.

    Args:
        team_stats (list[dict]): Output of get_team_season_stats().
        generated_date (str): Date string for the header.

    Returns:
        str: Complete HTML document.
    """
    ratings = [m['rating'] for m in team_stats]
    season_rating = round(sum(ratings) / len(ratings), 1) if ratings else 0.0
    matches_played = len(team_stats)
    wins = sum(1 for m in team_stats if m.get('result') == 'W')
    losses = sum(1 for m in team_stats if m.get('result') == 'L')

    chart_labels = json.dumps([m['match_title'].replace('Vodkas vs ', '') for m in team_stats])
    chart_ratings = json.dumps(ratings)

    # Action efficiency trends
    action_charts_html = _action_efficiency_charts(team_stats, chart_labels, 'chart-team-action')

    # Phase stats trends (BP%, SO%)
    bp_pcts = []
    so_pcts = []
    for m in team_stats:
        bp_total = m.get('bp_total', 0)
        bp_won = m.get('bp_won', 0)
        so_total = m.get('so_total', 0)
        so_won = m.get('so_won', 0)
        bp_pcts.append(round((bp_won / bp_total) * 100) if bp_total > 0 else None)
        so_pcts.append(round((so_won / so_total) * 100) if so_total > 0 else None)

    bp_json = json.dumps(bp_pcts)
    so_json = json.dumps(so_pcts)

    # Season totals
    season_data = _aggregate_season_data(team_stats)
    season_card = build_card_html('Equipo - Temporada', season_data, season_rating, 'team-summary-card')

    # Match-by-match table
    match_rows = []
    for m in team_stats:
        opponent = m['match_title'].replace('Vodkas vs ', '')
        rating = m['rating']
        r_color = _rating_color(rating)
        result = m.get('result', '')
        result_str = 'W' if result == 'W' else ('L' if result == 'L' else '-')
        result_color = 'var(--success)' if result == 'W' else ('var(--danger)' if result == 'L' else '#6b7280')
        sets = m.get('set_scores', [])
        sets_str = ' / '.join(f'{v}-{r}' for v, r in sets) if sets else '-'
        href = f'{m["match_stem"]}.html'
        match_rows.append(
            f'<tr>'
            f'<td><a href="{href}" style="color:var(--primary);text-decoration:none;font-weight:500;">{opponent}</a></td>'
            f'<td style="color:{result_color};font-weight:600;">{result_str}</td>'
            f'<td style="color:{r_color};font-weight:600;">{rating}</td>'
            f'<td>{sets_str}</td>'
            f'</tr>'
        )
    match_table_html = ''.join(match_rows)

    r_color = _rating_color(season_rating)

    return f"""<!DOCTYPE html>
<html lang="es">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>Vodkas - Temporada - Volleyball Analytics</title>
  <link rel="stylesheet" href="styles.css">
  <script src="https://cdn.jsdelivr.net/npm/chart.js"></script>
  {_COLLAPSIBLE_JS}
</head>
<body>
<div class="container">
  {_back_link()}
  <div class="report-header">
    <h1><span style="-webkit-text-fill-color:initial;">🏐</span> Vodkas - Temporada</h1>
    <p>Generado: {generated_date}</p>
  </div>

  {_section('Resumen de Temporada', f'''<div class="general-stats">
    <div class="stat-card"><div class="stat-value" style="color:{r_color}">{season_rating}</div><div class="stat-label">Rating Temporada</div></div>
    <div class="stat-card"><div class="stat-value">{matches_played}</div><div class="stat-label">Partidos</div></div>
    <div class="stat-card"><div class="stat-value" style="color:var(--success);">{wins}W</div><div class="stat-label">Victorias</div></div>
    <div class="stat-card"><div class="stat-value" style="color:var(--danger);">{losses}L</div><div class="stat-label">Derrotas</div></div>
  </div>''')}

  {_section('Progresión de Rating', f'''<div class="stat-card"><div class="card-body"><canvas id="chart-team-rating" height="250"></canvas></div></div>
  <script>
  (function() {{
    new Chart(document.getElementById('chart-team-rating'), {{
      type: 'line',
      data: {{
        labels: {chart_labels},
        datasets: [
          {{ label: 'Rating Equipo', data: {chart_ratings}, borderColor: '#6366f1', backgroundColor: 'rgba(99,102,241,0.1)', fill: true, tension: 0.3 }}
        ]
      }},
      options: {{
        responsive: true,
        interaction: {{ mode: 'index', intersect: false }},
        scales: {{ y: {{ min: 4, max: 10 }} }},
        plugins: {{ tooltip: {{ callbacks: {{ label: ctx => ctx.dataset.label + ': ' + ctx.parsed.y }} }} }}
      }}
    }});
  }})();
  </script>''')}

  {_section('Rendimiento de Puntos (Tendencia)', f'''<div style="font-size:0.82rem;color:#6b7280;margin-bottom:14px;line-height:1.7;">
    <span style="color:#f59e0b;font-weight:600;">Break Point %</span>: {_SCORING_DESCRIPTIONS['bp']}<br>
    <span style="color:#22c55e;font-weight:600;">Side-Out %</span>: {_SCORING_DESCRIPTIONS['so']}
  </div>
  <div class="stat-card"><div class="card-body"><canvas id="chart-points" height="250"></canvas></div></div>
  <script>
  (function() {{
    new Chart(document.getElementById('chart-points'), {{
      type: 'line',
      data: {{
        labels: {chart_labels},
        datasets: [
          {{ label: 'Break Point %', data: {bp_json}, borderColor: '#f59e0b', fill: false, tension: 0.3, spanGaps: true }},
          {{ label: 'Side-Out %', data: {so_json}, borderColor: '#22c55e', fill: false, tension: 0.3, spanGaps: true }}
        ]
      }},
      options: {{
        responsive: true,
        interaction: {{ mode: 'index', intersect: false }},
        scales: {{ y: {{ min: 0, max: 100, ticks: {{ callback: v => v + '%' }} }} }},
        plugins: {{ tooltip: {{ callbacks: {{ label: ctx => ctx.dataset.label + ': ' + (ctx.parsed.y !== null ? ctx.parsed.y + '%' : '-') }} }} }}
      }}
    }});
  }})();
  </script>''')}

  {_section('Eficiencia por Acción (Tendencia)', action_charts_html)}

  {_section('Estadísticas Acumuladas', f'<div class="players-grid">{season_card}</div>')}

  {_section('Detalle por Partido', f'''<div style="overflow-x:auto;">
    <table class="summary-table">
      <thead><tr><th>Rival</th><th>Resultado</th><th>Rating</th><th>Sets</th></tr></thead>
      <tbody>{match_table_html}</tbody>
    </table>
  </div>''')}

  {_back_nav()}
</div>
</body>
</html>"""


# ---------------------------------------------------------------------------
# Players Intermediate Page
# ---------------------------------------------------------------------------


def render_players_page(player_summaries, generated_date):
    """Render the intermediate players listing page.

    Args:
        player_summaries (list[dict]): Per-player season summary dicts.
        generated_date (str): Date string for the header.

    Returns:
        str: Complete HTML document.
    """
    p_cards = []
    for ps in player_summaries:
        r_color = _rating_color(ps['rating'])
        pos_code = ps.get('position', 'U')
        pos_label = POSITION_LABELS.get(pos_code, 'Universal')
        display_name = ps.get('name', f'#{ps["player_num"]}')
        p_cards.append(
            '<div class="match-card">'
            '<div class="card-header">'
            f'<span class="player-number">{display_name}</span>'
            f'<span class="player-rating" style="color:{r_color};background:white;">{ps["rating"]}</span>'
            '</div>'
            '<div class="card-body">'
            f'<span class="position-badge">{pos_label}</span>'
            f'<div class="metric-row"><span>Partidos</span><span>{ps["matches_played"]}</span></div>'
            f'<div class="metric-row"><span>Acciones totales</span><span>{ps["total_actions"]}</span></div>'
            f'<a href="player_{ps["player_num"]}.html" style="display:block;margin-top:14px;padding:8px 0;background:var(--primary);'
            f'color:white;text-align:center;border-radius:6px;text-decoration:none;font-weight:600;">Ver Temporada →</a>'
            '</div></div>'
        )
    cards_html = ''.join(p_cards)

    return f"""<!DOCTYPE html>
<html lang="es">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>Jugadores - Volleyball Analytics</title>
  <link rel="stylesheet" href="styles.css">
</head>
<body>
<div class="container">
  <div class="page-header">
    <a href="index.html" class="back-link">← Inicio</a>
    <h1><span style="-webkit-text-fill-color:initial;">👥</span> Jugadores</h1>
  </div>
  <p style="color:#6b7280;font-size:0.85rem;margin:0 0 20px;">Generado: {generated_date}</p>
  <div class="players-grid">{cards_html}</div>
  {_back_nav()}
</div>
</body>
</html>"""


# ---------------------------------------------------------------------------
# Matches Intermediate Page
# ---------------------------------------------------------------------------


def render_matches_page(matches, generated_date):
    """Render the intermediate matches listing page.

    Args:
        matches (list[dict]): Ordered list of match metadata dicts.
        generated_date (str): Date string for the header.

    Returns:
        str: Complete HTML document.
    """
    cards = []
    for m in matches:
        r_color = _rating_color(m['rating'])
        title = m['title']
        rating = m['rating']
        tot = m['total_actions']
        pct = m['perfect_pct']
        href = m['file']
        result = m.get('result')
        set_scores = m.get('set_scores', [])

        if result == 'W':
            badge_html = '<span class="result-badge result-win">Victoria</span>'
        elif result == 'L':
            badge_html = '<span class="result-badge result-loss">Derrota</span>'
        else:
            badge_html = ''

        if set_scores:
            sets_str = ' / '.join(f'{v}-{r}' for v, r in set_scores)
            sets_html = f'<div class="metric-row"><span>Sets</span><span>{sets_str}</span></div>'
        else:
            sets_html = ''

        cards.append(
            f'<div class="match-card">'
            f'<div class="card-header">'
            f'<span class="player-number">{title}</span>'
            f'<span class="player-rating" style="color:{r_color};background:white;">{rating}</span>'
            f'</div>'
            f'<div class="card-body">'
            f'{badge_html}'
            f'{sets_html}'
            f'<div class="metric-row"><span>Acciones totales</span><span>{tot}</span></div>'
            f'<div class="metric-row"><span>Eficacia Perfecta</span><span style="color:var(--success);">{pct}%</span></div>'
            f'<a href="{href}" style="display:block;margin-top:14px;padding:8px 0;background:var(--primary);'
            f'color:white;text-align:center;border-radius:6px;text-decoration:none;font-weight:600;">Ver Reporte →</a>'
            f'</div></div>'
        )
    cards_html = ''.join(cards)

    return f"""<!DOCTYPE html>
<html lang="es">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>Partidos - Volleyball Analytics</title>
  <link rel="stylesheet" href="styles.css">
</head>
<body>
<div class="container">
  <div class="page-header">
    <a href="index.html" class="back-link">← Inicio</a>
    <h1><span style="-webkit-text-fill-color:initial;">🏐</span> Partidos</h1>
  </div>
  <p style="color:#6b7280;font-size:0.85rem;margin:0 0 20px;">Generado: {generated_date}</p>
  <div class="players-grid">{cards_html}</div>
  {_back_nav()}
</div>
</body>
</html>"""
