"""Volleyball Analytics - HTML rendering engine.

Contains all HTML card builders and page renderers.
No knowledge of SQLite or file I/O.
"""

import re

from analytics import (
    ACTIONS, FULL_NAMES, GRADES,
    calculate_rating, calculate_phase_stats, calculate_point_stats,
)

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
        '<strong>Break Point:</strong> % Puntos ganados con posesión (saque propio).<br>'
        '<strong>Side-Out:</strong> % Puntos ganados recibiendo (saque rival).'
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
</head>
<body>
<div class="container">
  <div class="report-header">
    <h1>Reporte: {match_title}</h1>
    <p>Generado: {generated_date}</p>
    {yt_html}
  </div>

  <h3 class="section-title">Resumen Global</h3>
  <div class="general-stats">
    <div class="stat-card"><div class="stat-value">{team_rating}</div><div class="stat-label">Rating Equipo</div></div>
    <div class="stat-card"><div class="stat-value">{total_actions}</div><div class="stat-label">Acciones Totales</div></div>
    <div class="stat-card"><div class="stat-value" style="color:var(--success)">{perfect_pct}%</div><div class="stat-label">Eficacia Perfecta</div></div>
  </div>

  <h3 class="section-title">Acciones de Equipo</h3>
  <div class="players-grid">
    {team_card}
    {phase_card}
    {scoring_card}
  </div>

  <h3 class="section-title">Detalle por Jugador</h3>
  <div class="players-grid">
    {player_cards}
  </div>

  <div style="margin-top:24px;text-align:center;">
    <a href="index.html" style="display:inline-block;padding:10px 22px;background:var(--primary);color:white;border-radius:8px;text-decoration:none;font-weight:600;">← Todos los partidos</a>
  </div>
</div>
</body>
</html>"""


def render_index_page(matches, generated_date):
    """Render the static HTML index page that lists all available match reports.

    Generates one summary card per match. Each card shows:
        - Match title with a colour-coded team rating badge.
        - Win/Loss result badge and set score breakdown (if available).
        - Total recorded team actions.
        - Perfect-efficiency percentage.
        - A 'Ver Reporte →' link to the individual match HTML page.

    Args:
        matches (list[dict]): Ordered list of match metadata dicts. Each dict
            must contain:
                'title'          (str):   Human-readable match title.
                'file'           (str):   Relative filename, e.g. 'vodkas_vs_alaba.html'.
                'rating'         (float): Pre-calculated team rating (1.0–10.0).
                'total_actions'  (int):   Total recorded team actions.
                'perfect_pct'    (int):   Percentage of Perfect ('#') grade actions.
                'set_scores'     (list):  List of (vodkas, rival) int tuples; empty if unknown.
                'result'         (str|None): 'W', 'L', or None.
        generated_date (str): Date string displayed in the page header, 'DD/MM/YYYY'.

    Returns:
        str: A complete HTML document string (<!DOCTYPE html> … </html>),
            linking to the shared styles.css stylesheet.
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

        # Result badge
        if result == 'W':
            badge_html = '<span class="result-badge result-win">Victoria</span>'
        elif result == 'L':
            badge_html = '<span class="result-badge result-loss">Derrota</span>'
        else:
            badge_html = ''

        # Set score line
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
  <title>Volleyball Analytics</title>
  <link rel="stylesheet" href="styles.css">
</head>
<body>
<div class="container">
  <div class="report-header">
    <h1>🏐 Volleyball Analytics</h1>
    <p>Generado: {generated_date}</p>
  </div>
  <h3 class="section-title">Partidos</h3>
  <div class="players-grid">
    {cards_html}
  </div>
</div>
</body>
</html>"""
