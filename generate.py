#!/usr/bin/env python3
"""Volleyball Analytics - Static Report Generator

Reads .txt match log files, stores parsed data in a SQLite database,
and generates static HTML reports in the docs/ folder for GitHub Pages.

Usage: python generate.py
"""

import shutil
import sqlite3
import webbrowser
from pathlib import Path
from datetime import date

from analytics import parse_log, PLAYER_POSITIONS, POSITION_LABELS, PLAYER_NAMES, calculate_rating
from db import (
    init_db, upsert_match, get_all_matches_meta, get_match,
    get_phase_stats_from_db, get_point_stats_from_db,
    get_all_player_nums, get_player_season_stats, get_team_season_stats,
)
from renderer import (
    format_title, render_match_page, render_index_page,
    render_player_season_page, render_team_season_page,
)


def main():
    """Entry point: parse all .txt match files, persist to DB, render static HTML, open browser.

    Execution steps:
        1. Create 'docs/' and 'data/' directories if they do not exist.
        2. Copy 'styles.css' into 'docs/' so all report pages share the same stylesheet.
        3. Open (or create) 'data/volleyball.db' and call init_db() to ensure
           all tables exist.
        4. For each '*.txt' file in the current directory (sorted alphabetically):
               a. Read and parse the file via parse_log().
               b. Skip files with no recorded team actions (no valid tokens).
               c. Upsert parsed data into the database via upsert_match().
        5. For each match stored in the database:
               a. Reconstruct the parsed dict via get_match().
               b. Fetch pre-computed phase and point stats from the DB and inject
                  them into the parsed dict so the renderer can build the cards
                  without needing raw rallies.
               c. Render the match HTML page via render_match_page() and write
                  it to 'docs/<stem>.html'.
        6. Fetch all match metadata via get_all_matches_meta(), render
           'docs/index.html' via render_index_page(), and write it.
        7. Close the database connection.
        8. Open 'docs/index.html' in the default system web browser.

    Prints one status line per stored match and generated file, plus a final
    summary count. Files with no valid data are reported as skipped.

    Returns:
        None
    """
    output_dir = Path('docs')
    output_dir.mkdir(exist_ok=True)
    data_dir = Path('data')
    data_dir.mkdir(exist_ok=True)
    shutil.copy('styles.css', output_dir / 'styles.css')

    today = date.today().strftime('%d/%m/%Y')

    # Open (or create) the SQLite database
    db_path = data_dir / 'volleyball.db'
    conn = sqlite3.connect(str(db_path))
    init_db(conn)

    # Remove DB entries for stems that no longer have a matching .txt file
    current_stems = [p.stem for p in Path('.').glob('*.txt')]
    if current_stems:
        placeholders = ','.join('?' * len(current_stems))
        conn.execute(f"DELETE FROM matches WHERE stem NOT IN ({placeholders})", current_stems)
        conn.commit()

    # Parse all .txt files and upsert into the database
    for txt_path in sorted(Path('.').glob('*.txt')):
        log_text = txt_path.read_text(encoding='utf-8')
        parsed = parse_log(log_text)
        if parsed['team']['total'] == 0:
            print(f'  Skipped (no data): {txt_path.name}')
            continue

        stem = txt_path.stem
        title = format_title(stem)
        upsert_match(conn, stem, title, parsed)
        print(f'  Stored: {txt_path.name}')

    # Render match pages from DB
    matches_meta = get_all_matches_meta(conn)
    for meta in matches_meta:
        stem = meta['file'].replace('.html', '')
        parsed = get_match(conn, stem)
        if not parsed:
            continue

        # Inject pre-calculated phase/point stats so renderer works without rallies
        phase_stats = get_phase_stats_from_db(conn, stem)
        point_stats = get_point_stats_from_db(conn, stem)
        parsed['_phase_stats'] = phase_stats
        parsed['_point_stats'] = point_stats

        html = render_match_page(meta['title'], parsed, today)
        (output_dir / meta['file']).write_text(html, encoding='utf-8')
        print(f'  Generated: docs/{meta["file"]}')

    # --- Season pages ---
    # Team season
    team_season = get_team_season_stats(conn)
    if team_season:
        html = render_team_season_page(team_season, today)
        (output_dir / 'team_season.html').write_text(html, encoding='utf-8')
        print('  Generated: docs/team_season.html')

    # Build team ratings lookup (match_id → rating) for player season comparison
    team_ratings_by_match = {m['match_id']: m['rating'] for m in team_season}

    # Player season pages
    player_nums = get_all_player_nums(conn)
    player_summaries = []
    for pnum in player_nums:
        pstats = get_player_season_stats(conn, pnum)
        if not pstats:
            continue
        # Team ratings aligned to this player's matches
        team_match_ratings = [team_ratings_by_match.get(m['match_id'], 0.0) for m in pstats]

        html = render_player_season_page(pnum, pstats, team_match_ratings, today)
        (output_dir / f'player_{pnum}.html').write_text(html, encoding='utf-8')
        print(f'  Generated: docs/player_{pnum}.html')

        # Summary for index page
        ratings = [m['rating'] for m in pstats]
        avg_rating = round(sum(ratings) / len(ratings), 1)
        player_summaries.append({
            'player_num': pnum,
            'name': PLAYER_NAMES.get(pnum, f'#{pnum}'),
            'position': PLAYER_POSITIONS.get(pnum, 'U'),
            'rating': avg_rating,
            'matches_played': len(pstats),
            'total_actions': sum(m['total'] for m in pstats),
        })

    # Sort players by season rating descending
    player_summaries.sort(key=lambda x: x['rating'], reverse=True)

    # Team season summary for index
    team_season_summary = None
    if team_season:
        team_ratings = [m['rating'] for m in team_season]
        team_season_summary = {
            'rating': round(sum(team_ratings) / len(team_ratings), 1),
            'matches_played': len(team_season),
            'wins': sum(1 for m in team_season if m.get('result') == 'W'),
            'losses': sum(1 for m in team_season if m.get('result') == 'L'),
        }

    # Render index page with season data
    index_html = render_index_page(matches_meta, today, player_summaries, team_season_summary)
    (output_dir / 'index.html').write_text(index_html, encoding='utf-8')
    print(f'  Generated: docs/index.html')
    print(f'Done. {len(matches_meta)} match(es) + {len(player_summaries)} player(s) + team season processed.')

    conn.close()

    index_path = (output_dir / 'index.html').resolve().as_uri()
    webbrowser.open(index_path)


if __name__ == '__main__':
    main()
