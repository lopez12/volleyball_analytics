#!/usr/bin/env python3
"""Volleyball Analytics - Static Report Generator

Discovers every (team, tournament) dataset under 'teams/', stores parsed
match data in a per-dataset SQLite database, and generates static HTML
reports under 'docs/' for GitHub Pages. A root selector page at
'docs/index.html' links to every dataset dashboard.

Source tree (committed):
    teams/<team_slug>/<tournament_slug>/team.json
    teams/<team_slug>/<tournament_slug>/matches/NN_<opponent>.txt

Generated trees (git-ignored):
    data/<team_slug>/<tournament_slug>/volleyball.db
    docs/<team_slug>/<tournament_slug>/...
    docs/index.html

Usage: python generate.py
"""

import json
import os
import shutil
import sqlite3
import webbrowser
from datetime import date
from pathlib import Path
from xml.sax.saxutils import escape as xml_escape

from analytics import calculate_efficiency, load_team_config, parse_log
from db import (
    get_all_matches_meta,
    get_all_player_nums,
    get_earned_points_from_db,
    get_match,
    get_phase_stats_from_db,
    get_player_season_stats,
    get_point_stats_from_db,
    get_team_season_stats,
    init_db,
    upsert_match,
)
from renderer import (
    aggregate_season_data,
    format_title,
    render_index_page,
    render_match_page,
    render_matches_page,
    render_not_found_page,
    render_player_season_page,
    render_players_page,
    render_root_index_page,
    render_team_season_page,
    render_watch_page,
)

TEAMS_ROOT = Path('teams')
DOCS_ROOT = Path('docs')
DATA_ROOT = Path('data')
FAVICON_PATH = Path('favicon.ico')

# Canonical origin for absolute URLs in robots.txt and sitemap.xml. Overridable
# so forks and preview deploys can point at a different host.
SITE_URL = os.environ.get('SITE_URL', 'https://volleyballanalytics.app').strip().rstrip('/')

# Content-Security-Policy allowing the site's existing inline scripts/styles,
# Chart.js (jsDelivr), and the logger's YouTube IFrame playback. One line.
_CSP = (
    "default-src 'self'; "
    "script-src 'self' 'unsafe-inline' https://cdn.jsdelivr.net https://www.youtube.com https://s.ytimg.com; "
    "style-src 'self' 'unsafe-inline'; "
    "img-src 'self' data: https://i.ytimg.com; "
    'frame-src https://www.youtube.com https://www.youtube-nocookie.com; '
    "connect-src 'self' https://www.youtube.com; "
    "font-src 'self'; "
    "object-src 'none'; "
    "base-uri 'self'; "
    "frame-ancestors 'self'"
)

# Cloudflare Pages _headers file: security headers applied to every path.
# Ignored harmlessly by GitHub Pages and on file://.
_HEADERS_FILE = f"""/*
  X-Content-Type-Options: nosniff
  Referrer-Policy: strict-origin-when-cross-origin
  Permissions-Policy: geolocation=(), microphone=(), camera=()
  X-Frame-Options: SAMEORIGIN
  Content-Security-Policy: {_CSP}
"""


def _build_sitemap(docs_root, site_url, lastmod):
    """Build the sitemap.xml document listing every generated HTML page.

    Walks docs_root for '*.html' files (excluding 404.html), maps each to an
    absolute URL under site_url, and returns a well-formed urlset. Entries are
    sorted so the build is deterministic.

    Args:
        docs_root (Path): The generated site root (docs/).
        site_url (str): Canonical origin with no trailing slash.
        lastmod (str): ISO 8601 date applied to every entry.

    Returns:
        str: The sitemap.xml document.
    """
    rel_paths = sorted(
        p.relative_to(docs_root).as_posix()
        for p in docs_root.rglob('*.html')
        if p.name != '404.html'
    )
    urls = ''.join(
        f'  <url><loc>{xml_escape(f"{site_url}/{rel}")}</loc><lastmod>{lastmod}</lastmod></url>\n'
        for rel in rel_paths
    )
    return (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">\n'
        f'{urls}'
        '</urlset>\n'
    )


def discover_datasets():
    """Find every dataset folder under teams/ that contains a team.json.

    Returns:
        list[tuple[str, str, Path]]: Sorted (team_slug, tournament_slug, dataset_dir)
            triples, one per dataset folder holding a team.json file.
    """
    datasets = []
    if not TEAMS_ROOT.is_dir():
        return datasets
    for team_dir in sorted(p for p in TEAMS_ROOT.iterdir() if p.is_dir()):
        for ds_dir in sorted(p for p in team_dir.iterdir() if p.is_dir()):
            if (ds_dir / 'team.json').exists():
                datasets.append((team_dir.name, ds_dir.name, ds_dir))
    return datasets


def write_datasets_manifest(datasets):
    """Write docs/datasets.json: a roster manifest for the Match Logger setup flow.

    Emits one entry per discovered dataset with its committed team.json roster
    (numbers, names, positions) so the logger can offer team/roster selection
    without hitting the GitHub API. Contains no secrets - only data already
    committed under teams/**/team.json. Refreshed on every build.

    Args:
        datasets (list[tuple[str, str, Path]]): (team_slug, tournament_slug,
            dataset_dir) triples from discover_datasets().

    Returns:
        None
    """
    manifest = []
    for team_slug, tournament_slug, ds_dir in datasets:
        try:
            cfg = json.loads((ds_dir / 'team.json').read_text(encoding='utf-8'))
        except (OSError, ValueError) as exc:
            print(f'  Skipped manifest entry ({team_slug}/{tournament_slug}): {exc}')
            continue
        manifest.append(
            {
                'team_slug': team_slug,
                'tournament_slug': tournament_slug,
                'team': cfg.get('team', ''),
                'tournament': cfg.get('tournament', ''),
                'type': cfg.get('type', 'tournament'),
                'roster': cfg.get('roster', {}),
            }
        )
    DOCS_ROOT.mkdir(exist_ok=True)
    payload = json.dumps(manifest, ensure_ascii=False, indent=2)
    (DOCS_ROOT / 'datasets.json').write_text(payload, encoding='utf-8')
    print(f'  Generated: docs/datasets.json ({len(manifest)} dataset(s))')

    # Also emit the manifest as a script-injected global. The logger loads this
    # via a <script> tag so team selection works over file:// too (fetch is
    # blocked there), not only when served/deployed.
    js = 'window.LOGGER_DATASETS = ' + payload + ';\n'
    logger_docs = DOCS_ROOT / 'logger'
    if logger_docs.is_dir():
        (logger_docs / 'datasets.js').write_text(js, encoding='utf-8')
        print('  Generated: docs/logger/datasets.js')
    # Keep the source placeholder current so opening logger/ directly also
    # reflects newly added datasets (otherwise it goes stale).
    logger_src = Path('logger')
    if logger_src.is_dir():
        (logger_src / 'datasets.js').write_text(js, encoding='utf-8')
        print('  Generated: logger/datasets.js')


def _generate_dataset(team_slug, tournament_slug, ds_dir, today):
    """Build the SQLite DB and all HTML pages for a single dataset.

    Args:
        team_slug (str): Folder-safe team identifier (e.g. 'vodkas').
        tournament_slug (str): Folder-safe dataset identifier (e.g. 'apertura-2026').
        ds_dir (Path): Path to the dataset source folder under teams/.
        today (str): Formatted generation date for page headers.

    Returns:
        dict | None: A root-index summary dict for this dataset, or None if the
            dataset has no valid match data (in which case nothing is rendered).
    """
    config = load_team_config(ds_dir / 'team.json')
    team_name = config['team']
    tournament_name = config['tournament']
    team_type = config['type']
    positions = config['positions']
    names = config['names']
    objectives = config['objectives']

    matches_dir = ds_dir / 'matches'
    out_dir = DOCS_ROOT / team_slug / tournament_slug
    data_dir = DATA_ROOT / team_slug / tournament_slug
    data_dir.mkdir(parents=True, exist_ok=True)

    conn = sqlite3.connect(str(data_dir / 'volleyball.db'))
    init_db(conn)

    txt_files = sorted(matches_dir.glob('*.txt')) if matches_dir.is_dir() else []

    # Remove DB entries for stems that no longer have a matching .txt file
    current_stems = [p.stem for p in txt_files]
    if current_stems:
        placeholders = ','.join('?' * len(current_stems))
        conn.execute(f'DELETE FROM matches WHERE stem NOT IN ({placeholders})', current_stems)
    else:
        conn.execute('DELETE FROM matches')
    conn.commit()

    # Parse all .txt files and upsert into the database
    replays = {}
    for txt_path in txt_files:
        log_text = txt_path.read_text(encoding='utf-8')
        parsed = parse_log(log_text)
        stem = txt_path.stem
        replays[stem] = parsed['replay']
        eligible = any(item['eligible'] for item in parsed['replay']['sets'])
        if not eligible:
            # Only remove the exact generated watch file for this known source.
            (out_dir / f'{stem}_watch.html').unlink(missing_ok=True)
        if parsed['team']['total'] == 0 and not eligible:
            print(f'  Skipped (no data): {team_slug}/{tournament_slug}/{txt_path.name}')
            continue
        title = format_title(stem, team_name)
        upsert_match(conn, stem, title, parsed)
        print(f'  Stored: {team_slug}/{tournament_slug}/{txt_path.name}')

    matches_meta = get_all_matches_meta(conn)
    if not matches_meta:
        print(f'  Skipped dataset (no matches): {team_slug}/{tournament_slug}')
        conn.close()
        return None

    out_dir.mkdir(parents=True, exist_ok=True)
    shutil.copy('styles.css', out_dir / 'styles.css')
    shutil.copy('viewer.js', out_dir / 'viewer.js')

    # Render match pages from DB
    for meta in matches_meta:
        stem = meta['file'].replace('.html', '')
        parsed = get_match(conn, stem)
        if not parsed:
            continue
        parsed['_phase_stats'] = get_phase_stats_from_db(conn, stem)
        parsed['_point_stats'] = get_point_stats_from_db(conn, stem)
        parsed['_earned_points'] = get_earned_points_from_db(conn, stem)
        replay = replays.get(stem)
        watch_href = None
        if replay and any(item['eligible'] for item in replay['sets']):
            watch_href = f'{stem}_watch.html'
            watch_html = render_watch_page(meta['title'], replay, names, meta['file'])
            (out_dir / watch_href).write_text(watch_html, encoding='utf-8')
            print(f'  Generated: docs/{team_slug}/{tournament_slug}/{watch_href}')
        html = render_match_page(meta['title'], parsed, today, replay, watch_href)
        (out_dir / meta['file']).write_text(html, encoding='utf-8')
        print(f'  Generated: docs/{team_slug}/{tournament_slug}/{meta["file"]}')

    # --- Season (dataset aggregate) pages ---
    team_season = get_team_season_stats(conn)
    if team_season:
        html = render_team_season_page(
            team_season, today, team_name, tournament_name, team_type, objectives
        )
        (out_dir / 'team_season.html').write_text(html, encoding='utf-8')
        print(f'  Generated: docs/{team_slug}/{tournament_slug}/team_season.html')

    # Build team ratings lookup (match_id -> rating) for player season comparison
    team_ratings_by_match = {m['match_id']: m['rating'] for m in team_season}

    # Player season pages
    player_nums = get_all_player_nums(conn)
    player_summaries = []
    for pnum in player_nums:
        pstats = get_player_season_stats(conn, pnum)
        if not pstats:
            continue
        team_match_ratings = [team_ratings_by_match.get(m['match_id'], 0.0) for m in pstats]
        html = render_player_season_page(
            pnum,
            pstats,
            team_match_ratings,
            today,
            positions,
            names,
            team_name,
            tournament_name,
            team_type,
        )
        (out_dir / f'player_{pnum}.html').write_text(html, encoding='utf-8')
        print(f'  Generated: docs/{team_slug}/{tournament_slug}/player_{pnum}.html')

        ratings = [m['rating'] for m in pstats]
        avg_rating = round(sum(ratings) / len(ratings), 1)
        season_efficiency = calculate_efficiency(aggregate_season_data(pstats))
        player_summaries.append(
            {
                'player_num': pnum,
                'name': names.get(pnum, f'#{pnum}'),
                'position': positions.get(pnum, 'U'),
                'rating': avg_rating,
                'matches_played': len(pstats),
                'total_actions': sum(m['total'] for m in pstats),
                'efficiency': season_efficiency,
            }
        )

    player_summaries.sort(key=lambda x: x['rating'], reverse=True)

    # Dataset aggregate summary for the dataset index hero
    team_season_summary = None
    if team_season:
        team_ratings = [m['rating'] for m in team_season]
        team_season_summary = {
            'rating': round(sum(team_ratings) / len(team_ratings), 1),
            'matches_played': len(team_season),
            'wins': sum(1 for m in team_season if m.get('result') == 'W'),
            'losses': sum(1 for m in team_season if m.get('result') == 'L'),
        }

    index_html = render_index_page(
        matches_meta,
        today,
        team_name,
        tournament_name,
        team_type,
        player_summaries,
        team_season_summary,
        objectives,
    )
    (out_dir / 'index.html').write_text(index_html, encoding='utf-8')
    print(f'  Generated: docs/{team_slug}/{tournament_slug}/index.html')

    players_html = render_players_page(player_summaries, today)
    (out_dir / 'players.html').write_text(players_html, encoding='utf-8')
    print(f'  Generated: docs/{team_slug}/{tournament_slug}/players.html')

    matches_html = render_matches_page(matches_meta, today)
    (out_dir / 'matches.html').write_text(matches_html, encoding='utf-8')
    print(f'  Generated: docs/{team_slug}/{tournament_slug}/matches.html')

    conn.close()

    summary = {
        'team': team_name,
        'tournament': tournament_name,
        'type': team_type,
        'href': f'{team_slug}/{tournament_slug}/index.html',
        'rating': team_season_summary['rating'] if team_season_summary else 0.0,
        'matches_played': team_season_summary['matches_played'] if team_season_summary else 0,
        'wins': team_season_summary['wins'] if team_season_summary else 0,
        'losses': team_season_summary['losses'] if team_season_summary else 0,
    }
    return summary


def main():
    """Entry point: discover all datasets, render each, then build the root selector.

    For every dataset folder under 'teams/' that contains a team.json, this
    parses its match logs into a per-dataset SQLite database and renders a full
    dashboard under 'docs/<team>/<tournament>/'. Datasets with no valid match
    data are skipped. Finally a root 'docs/index.html' selector page links to
    every generated dataset, and the result is opened in the default browser
    (skipped when the CI environment variable is set, e.g. in GitHub Actions).

    Returns:
        None
    """
    # Wipe previously generated HTML so stale pages never linger, then rebuild.
    if DOCS_ROOT.exists():
        shutil.rmtree(DOCS_ROOT)
    DOCS_ROOT.mkdir(exist_ok=True)
    DATA_ROOT.mkdir(exist_ok=True)
    shutil.copy('styles.css', DOCS_ROOT / 'styles.css')
    shutil.copy(FAVICON_PATH, DOCS_ROOT / FAVICON_PATH.name)

    # Deploy the static Match Logger app to docs/logger/ (survives the rmtree
    # above). Guarded so the build never fails when logger/ is absent.
    if Path('logger').is_dir():
        shutil.copytree('logger', DOCS_ROOT / 'logger', dirs_exist_ok=True)
        print('  Copied: logger/ -> docs/logger/')

    today = date.today().strftime('%d/%m/%Y')

    datasets = discover_datasets()
    if not datasets:
        print('No datasets found under teams/. Nothing to generate.')

    # Publish the roster manifest consumed by the Match Logger setup flow.
    write_datasets_manifest(datasets)

    summaries = []
    for team_slug, tournament_slug, ds_dir in datasets:
        summary = _generate_dataset(team_slug, tournament_slug, ds_dir, today)
        if summary:
            summaries.append(summary)

    # Root selector page
    root_html = render_root_index_page(summaries, today)
    (DOCS_ROOT / 'index.html').write_text(root_html, encoding='utf-8')
    print(f'  Generated: docs/index.html (root selector, {len(summaries)} dataset(s))')

    # Deploy artifacts for the hosted site. robots.txt/sitemap.xml use absolute
    # URLs from SITE_URL; 404.html and _headers are platform conventions.
    (DOCS_ROOT / '404.html').write_text(render_not_found_page(today), encoding='utf-8')
    (DOCS_ROOT / 'robots.txt').write_text(
        f'User-agent: *\nAllow: /\nSitemap: {SITE_URL}/sitemap.xml\n', encoding='utf-8'
    )
    sitemap = _build_sitemap(DOCS_ROOT, SITE_URL, date.today().isoformat())
    (DOCS_ROOT / 'sitemap.xml').write_text(sitemap, encoding='utf-8')
    (DOCS_ROOT / '_headers').write_text(_HEADERS_FILE, encoding='utf-8')
    print('  Generated: docs/404.html, robots.txt, sitemap.xml, _headers')

    print(f'Done. {len(summaries)} dataset(s) processed.')

    if not os.environ.get('CI'):
        index_path = (DOCS_ROOT / 'index.html').resolve().as_uri()
        webbrowser.open(index_path)


if __name__ == '__main__':
    main()
