#!/usr/bin/env python3
"""Volleyball Analytics - Static Report Generator

Reads .txt match log files in the current directory and generates
static HTML reports in the docs/ folder for GitHub Pages.

Usage: python generate.py
"""

import re
import glob
import shutil
import webbrowser
from pathlib import Path
from datetime import date

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------
WEIGHTS = {'#': 1.0, '+': 0.4, '!': -0.3, '-': -1.0}
FULL_NAMES = {
    'S': 'Saque',
    'R': 'Recepción de Saque',
    'E': 'Acomodo',
    'A': 'Ataque',
    'D': 'Defensa',
    'B': 'Bloqueo',
}
ACTIONS = list(FULL_NAMES.keys())
GRADES = ['#', '+', '!', '-']

_RE_PLAYER = re.compile(r'^(\d+)([SREADB])([#+!\-])$')
_RE_TEAM   = re.compile(r'^([SREADB])([#+!\-])$')
_RE_ANY    = re.compile(r'^(\d*)([SREADB])([#+!\-])$')
_RE_PHASE  = re.compile(r'^(\d+)([SREADB])([#+!\-])$|^([SREADB])([#+!\-])$')
_RE_YT     = re.compile(r'^https?://(www\.)?(youtube\.com|youtu\.be)/')

# ---------------------------------------------------------------------------
# Data helpers
# ---------------------------------------------------------------------------
def _new_stats():
    return {
        'total': 0,
        'score_sum': 0.0,
        'grades': {g: 0 for g in GRADES},
        'actions': {a: {'tot': 0, 'good': 0} for a in ACTIONS},
        'grade_count': {g: {a: 0 for a in ACTIONS} for g in GRADES},
    }

def _record(stats, action, grade):
    stats['total'] += 1
    stats['grades'][grade] += 1
    stats['score_sum'] += WEIGHTS.get(grade, 0)
    stats['actions'][action]['tot'] += 1
    if grade in ('#', '+'):
        stats['actions'][action]['good'] += 1
    stats['grade_count'][grade][action] += 1

# ---------------------------------------------------------------------------
# Parsing
# ---------------------------------------------------------------------------
def parse_log(log_string):
    lines = log_string.strip().splitlines()
    rallies = []
    players = {}
    youtube_urls = []
    team = _new_stats()

    for line in lines:
        trimmed = line.strip()
        if not trimmed or trimmed == '---':
            continue
        if trimmed.lower().startswith('@youtube:'):
            url = trimmed[9:].strip()
            if _RE_YT.match(url):
                youtube_urls.append(url)
            continue

        tokens = trimmed.split()
        rally_tokens = []

        for token in tokens:
            m = _RE_PLAYER.match(token)
            if m:
                num, action, grade = m.group(1), m.group(2), m.group(3)
                if num not in players:
                    players[num] = _new_stats()
                _record(players[num], action, grade)
                _record(team, action, grade)
                rally_tokens.append(token)
            else:
                m = _RE_TEAM.match(token)
                if m:
                    action, grade = m.group(1), m.group(2)
                    _record(team, action, grade)
                    rally_tokens.append(token)

        if rally_tokens:
            rallies.append(rally_tokens)

    return {'players': players, 'team': team, 'rallies': rallies, 'youtube_urls': youtube_urls}

# ---------------------------------------------------------------------------
# Calculations
# ---------------------------------------------------------------------------
def calculate_rating(data):
    if data['total'] == 0:
        return 0.0
    raw = 6.0 + (data['score_sum'] / data['total']) * 4.0
    return round(max(1.0, min(10.0, raw)), 1)

def calculate_phase_stats(rallies):
    stats = {
        'so_good': {'attempts': 0, 'kills': 0},
        'so_bad':  {'attempts': 0, 'kills': 0},
        'trans':   {'attempts': 0, 'kills': 0},
    }
    for rally in rallies:
        current_phase = None
        saw_set = False
        for token in rally:
            m = _RE_PHASE.match(token)
            if not m:
                continue
            if m.group(1) is not None:
                action, grade = m.group(2), m.group(3)
            else:
                action, grade = m.group(4), m.group(5)

            if action == 'R':
                if grade in ('#', '+'):
                    current_phase = 'so_good'
                    stats['so_good']['attempts'] += 1
                elif grade == '!':
                    current_phase = 'so_bad'
                    stats['so_bad']['attempts'] += 1
                else:
                    current_phase = None
                saw_set = False
            elif action == 'D':
                current_phase = 'trans'
                stats['trans']['attempts'] += 1
                saw_set = False
            elif action == 'E':
                if current_phase:
                    saw_set = True
                else:
                    current_phase = None
                    saw_set = False
            elif action == 'A':
                if current_phase and saw_set and grade == '#':
                    stats[current_phase]['kills'] += 1
                current_phase = None
                saw_set = False
            else:
                current_phase = None
                saw_set = False
    return stats

def calculate_point_stats(rallies):
    bp = {'total': 0, 'won': 0}
    so = {'total': 0, 'won': 0}

    for r, rally in enumerate(rallies):
        if not rally:
            continue
        rally_type = None
        for token in rally:
            m = _RE_ANY.match(token)
            if not m:
                continue
            action = m.group(2)
            if action == 'S':
                rally_type = 'serve'
            elif action == 'R':
                rally_type = 'receive'
            break

        if not rally_type:
            continue

        won = _determine_win(r, rallies)
        if rally_type == 'serve':
            bp['total'] += 1
            if won:
                bp['won'] += 1
        else:
            so['total'] += 1
            if won:
                so['won'] += 1

    return {'bp': bp, 'so': so}

def _determine_win(r, rallies):
    if r + 1 < len(rallies):
        for token in rallies[r + 1]:
            m = _RE_ANY.match(token)
            if not m:
                continue
            return m.group(2) == 'S'
        return False
    # Last rally: check if last token is a terminal kill
    if rallies[r]:
        m = _RE_ANY.match(rallies[r][-1])
        return bool(m and m.group(3) == '#')
    return False

# ---------------------------------------------------------------------------
# HTML helpers
# ---------------------------------------------------------------------------
def _pct(n, total):
    return round((n / total) * 100) if total > 0 else 0

def _rating_color(rating):
    if rating >= 8:
        return '#16a34a'
    if rating >= 6:
        return '#ca8a04'
    return '#dc2626'

# ---------------------------------------------------------------------------
# Card HTML builders
# ---------------------------------------------------------------------------
def build_card_html(title, data, rating, extra_class=''):
    total       = data['total']
    grades      = data['grades']
    actions     = data['actions']
    grade_count = data['grade_count']

    perfect_pct  = _pct(grades['#'], total)
    positive_pct = _pct(grades['+'], total)
    regular_pct  = _pct(grades['!'], total)
    error_pct    = _pct(grades['-'], total)
    r_color      = _rating_color(rating)

    # Action pills
    pills = []
    for action in ACTIONS:
        a = actions[action]
        if a['tot'] == 0:
            continue
        eff = a['good'] / a['tot']
        pill_class = 'high-perf' if eff == 1.0 else ('low-perf' if eff < 0.4 else '')
        name  = FULL_NAMES[action]
        good  = a['good']
        tot   = a['tot']
        pills.append(
            f'<div class="action-pill {pill_class}">'
            f'<span class="action-name">{name}</span>'
            f'<span class="action-count">{good}/{tot}</span>'
            f'</div>'
        )
    pills_html = ''.join(pills)

    # Summary table – highlight max values per column
    max_good    = max((max(grade_count['#'][a], grade_count['+'][a]) for a in ACTIONS), default=0)
    max_regular = max((grade_count['!'][a] for a in ACTIONS), default=0)
    max_bad     = max((grade_count['-'][a] for a in ACTIONS), default=0)

    rows = []
    for action in ACTIONS:
        perfect  = grade_count['#'][action]
        positive = grade_count['+'][action]
        regular  = grade_count['!'][action]
        error    = grade_count['-'][action]
        action_name = FULL_NAMES[action]
        pc   = 'highlight-good'    if perfect  == max_good    and max_good    > 0 else ''
        posc = 'highlight-good'    if positive == max_good    and max_good    > 0 else ''
        rc   = 'highlight-regular' if regular  == max_regular and max_regular > 0 else ''
        ec   = 'highlight-bad'     if error    == max_bad     and max_bad     > 0 else ''
        rows.append(
            f'<tr><td>{action_name}</td>'
            f'<td class="{pc}">{perfect}</td>'
            f'<td class="{posc}">{positive}</td>'
            f'<td class="{rc}">{regular}</td>'
            f'<td class="{ec}">{error}</td></tr>'
        )
    rows_html = ''.join(rows)

    card_class = f'player-card {extra_class}'.strip()
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
    phases = [
        ('so_good', 'Side-Out (Pase Bueno)'),
        ('so_bad',  'Side-Out (Pase Regular)'),
        ('trans',   'Transición'),
    ]
    parts = []
    for key, label in phases:
        s       = phase_stats[key]
        kills   = s['kills']
        attempts = s['attempts']
        if attempts == 0:
            continue
        p = _pct(kills, attempts)
        bar_color = 'var(--success)' if p >= 50 else ('var(--primary)' if p >= 35 else 'var(--danger)')
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
        '<div class="player-card team-summary-card" style="margin-top:10px;">'
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
    bp       = point_stats['bp']
    so       = point_stats['so']
    bp_won   = bp['won'];  bp_total = bp['total']
    so_won   = so['won'];  so_total = so['total']
    bp_pct   = _pct(bp_won, bp_total)
    so_pct   = _pct(so_won, so_total)
    bp_color = 'var(--success)' if bp_pct >= 40 else ('var(--primary)' if bp_pct >= 30 else 'var(--danger)')
    so_color = 'var(--success)' if so_pct >= 60 else ('var(--primary)' if so_pct >= 50 else 'var(--danger)')
    return (
        '<div class="player-card team-summary-card" style="margin-top:10px;">'
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
    """'vodkas_vs_alaba' → 'Vodkas vs Alaba'"""
    return stem.replace('_', ' ').title().replace(' Vs ', ' vs ')


def render_match_page(match_title, parsed, generated_date):
    players      = parsed['players']
    team         = parsed['team']
    rallies      = parsed['rallies']
    youtube_urls = parsed['youtube_urls']

    team_rating  = calculate_rating(team)
    total_actions = team['total']
    perfect_pct  = _pct(team['grades']['#'], total_actions)

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

    team_card    = build_card_html('Equipo', team, team_rating, 'team-summary-card')
    phase_card   = build_phase_card_html(calculate_phase_stats(rallies))
    scoring_card = build_scoring_card_html(calculate_point_stats(rallies))

    players_sorted = sorted(
        [(num, data, calculate_rating(data)) for num, data in players.items() if data['total'] > 0],
        key=lambda x: x[2],
        reverse=True,
    )
    player_cards = ''.join(build_card_html(f'#{num}', data, rating) for num, data, rating in players_sorted)

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
    cards = []
    for m in matches:
        r_color = _rating_color(m['rating'])
        title   = m['title']
        rating  = m['rating']
        tot     = m['total_actions']
        pct     = m['perfect_pct']
        href    = m['file']
        cards.append(
            f'<div class="player-card">'
            f'<div class="card-header">'
            f'<span class="player-number">{title}</span>'
            f'<span class="player-rating" style="color:{r_color};background:white;">{rating}</span>'
            f'</div>'
            f'<div class="card-body">'
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

# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------
def main():
    output_dir = Path('docs')
    output_dir.mkdir(exist_ok=True)
    shutil.copy('styles.css', output_dir / 'styles.css')

    today = date.today().strftime('%d/%m/%Y')
    matches = []

    for txt_path in sorted(Path('.').glob('*.txt')):
        log_text = txt_path.read_text(encoding='utf-8')
        parsed   = parse_log(log_text)
        if parsed['team']['total'] == 0:
            print(f'  Skipped (no data): {txt_path.name}')
            continue

        stem   = txt_path.stem
        title  = format_title(stem)
        rating = calculate_rating(parsed['team'])
        total  = parsed['team']['total']
        pct    = _pct(parsed['team']['grades']['#'], total)

        out_file = f'{stem}.html'
        html = render_match_page(title, parsed, today)
        (output_dir / out_file).write_text(html, encoding='utf-8')
        print(f'  Generated: docs/{out_file}')

        matches.append({
            'title':        title,
            'file':         out_file,
            'rating':       rating,
            'total_actions': total,
            'perfect_pct':  pct,
        })

    index_html = render_index_page(matches, today)
    (output_dir / 'index.html').write_text(index_html, encoding='utf-8')
    print(f'  Generated: docs/index.html')
    print(f'Done. {len(matches)} match(es) processed.')

    index_path = (output_dir / 'index.html').resolve().as_uri()
    webbrowser.open(index_path)


if __name__ == '__main__':
    main()
