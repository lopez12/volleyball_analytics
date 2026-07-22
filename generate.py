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

import shutil
import sqlite3
import webbrowser
from pathlib import Path
from datetime import date

from analytics import parse_log, load_team_config, calculate_efficiency
from db import (
    init_db, upsert_match, get_all_matches_meta, get_match,
    get_phase_stats_from_db, get_point_stats_from_db, get_earned_points_from_db,
    get_all_player_nums, get_player_season_stats, get_team_season_stats,
)
from renderer import (
    format_title, render_match_page, render_index_page,
    render_player_season_page, render_team_season_page,
    render_players_page, render_matches_page, render_root_index_page,
    aggregate_season_data,
)

TEAMS_ROOT = Path('teams')
DOCS_ROOT = Path('docs')
DATA_ROOT = Path('data')


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
        conn.execute(f"DELETE FROM matches WHERE stem NOT IN ({placeholders})", current_stems)
    else:
        conn.execute("DELETE FROM matches")
    conn.commit()

    # Parse all .txt files and upsert into the database
    for txt_path in txt_files:
        log_text = txt_path.read_text(encoding='utf-8')
        parsed = parse_log(log_text)
        if parsed['team']['total'] == 0:
            print(f'  Skipped (no data): {team_slug}/{tournament_slug}/{txt_path.name}')
            continue
        stem = txt_path.stem
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

    # Render match pages from DB
    for meta in matches_meta:
        stem = meta['file'].replace('.html', '')
        parsed = get_match(conn, stem)
        if not parsed:
            continue
        parsed['_phase_stats'] = get_phase_stats_from_db(conn, stem)
        parsed['_point_stats'] = get_point_stats_from_db(conn, stem)
        parsed['_earned_points'] = get_earned_points_from_db(conn, stem)
        html = render_match_page(meta['title'], parsed, today)
        (out_dir / meta['file']).write_text(html, encoding='utf-8')
        print(f'  Generated: docs/{team_slug}/{tournament_slug}/{meta["file"]}')

    # --- Season (dataset aggregate) pages ---
    team_season = get_team_season_stats(conn)
    if team_season:
        html = render_team_season_page(team_season, today, team_name, tournament_name, team_type)
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
            pnum, pstats, team_match_ratings, today,
            positions, names, team_name, tournament_name, team_type,
        )
        (out_dir / f'player_{pnum}.html').write_text(html, encoding='utf-8')
        print(f'  Generated: docs/{team_slug}/{tournament_slug}/player_{pnum}.html')

        ratings = [m['rating'] for m in pstats]
        avg_rating = round(sum(ratings) / len(ratings), 1)
        season_efficiency = calculate_efficiency(aggregate_season_data(pstats))
        player_summaries.append({
            'player_num': pnum,
            'name': names.get(pnum, f'#{pnum}'),
            'position': positions.get(pnum, 'U'),
            'rating': avg_rating,
            'matches_played': len(pstats),
            'total_actions': sum(m['total'] for m in pstats),
            'efficiency': season_efficiency,
        })

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
        matches_meta, today, team_name, tournament_name, team_type,
        player_summaries, team_season_summary,
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
    every generated dataset, and the result is opened in the default browser.

    Returns:
        None
    """
    # Wipe previously generated HTML so stale pages never linger, then rebuild.
    if DOCS_ROOT.exists():
        shutil.rmtree(DOCS_ROOT)
    DOCS_ROOT.mkdir(exist_ok=True)
    DATA_ROOT.mkdir(exist_ok=True)
    shutil.copy('styles.css', DOCS_ROOT / 'styles.css')

    today = date.today().strftime('%d/%m/%Y')

    datasets = discover_datasets()
    if not datasets:
        print('No datasets found under teams/. Nothing to generate.')

    summaries = []
    for team_slug, tournament_slug, ds_dir in datasets:
        summary = _generate_dataset(team_slug, tournament_slug, ds_dir, today)
        if summary:
            summaries.append(summary)

    # Root selector page
    root_html = render_root_index_page(summaries, today)
    (DOCS_ROOT / 'index.html').write_text(root_html, encoding='utf-8')
    print(f'  Generated: docs/index.html (root selector, {len(summaries)} dataset(s))')

    print(f'Done. {len(summaries)} dataset(s) processed.')

    index_path = (DOCS_ROOT / 'index.html').resolve().as_uri()
    webbrowser.open(index_path)


if __name__ == '__main__':
    main()
