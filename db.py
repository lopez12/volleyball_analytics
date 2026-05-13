"""Volleyball Analytics - SQLite persistence layer.

Provides schema creation, upsert logic, and query helpers.
No knowledge of HTML rendering.
"""

import json
import sqlite3

from analytics import (
    ACTIONS, GRADES,
    calculate_rating, calculate_phase_stats, calculate_point_stats,
)

# ---------------------------------------------------------------------------
# Schema
# ---------------------------------------------------------------------------

_SCHEMA = """
CREATE TABLE IF NOT EXISTS matches (
    id             INTEGER PRIMARY KEY AUTOINCREMENT,
    stem           TEXT    UNIQUE NOT NULL,
    title          TEXT    NOT NULL,
    generated_date TEXT    NOT NULL,
    youtube_urls   TEXT    NOT NULL DEFAULT '[]'
);

CREATE TABLE IF NOT EXISTS team_match_stats (
    match_id        INTEGER PRIMARY KEY REFERENCES matches(id) ON DELETE CASCADE,
    total           INTEGER NOT NULL,
    score_sum       REAL    NOT NULL,
    grade_perfect   INTEGER NOT NULL,
    grade_positive  INTEGER NOT NULL,
    grade_regular   INTEGER NOT NULL,
    grade_error     INTEGER NOT NULL,
    s_tot INTEGER, s_good INTEGER,
    r_tot INTEGER, r_good INTEGER,
    e_tot INTEGER, e_good INTEGER,
    a_tot INTEGER, a_good INTEGER,
    d_tot INTEGER, d_good INTEGER,
    b_tot INTEGER, b_good INTEGER,
    perfect_s INTEGER, perfect_r INTEGER, perfect_e INTEGER,
    perfect_a INTEGER, perfect_d INTEGER, perfect_b INTEGER,
    positive_s INTEGER, positive_r INTEGER, positive_e INTEGER,
    positive_a INTEGER, positive_d INTEGER, positive_b INTEGER,
    regular_s INTEGER, regular_r INTEGER, regular_e INTEGER,
    regular_a INTEGER, regular_d INTEGER, regular_b INTEGER,
    error_s INTEGER, error_r INTEGER, error_e INTEGER,
    error_a INTEGER, error_d INTEGER, error_b INTEGER,
    so_good_attempts INTEGER, so_good_kills INTEGER,
    so_bad_attempts  INTEGER, so_bad_kills  INTEGER,
    trans_attempts   INTEGER, trans_kills   INTEGER,
    bp_total INTEGER, bp_won INTEGER,
    so_total INTEGER, so_won INTEGER
);

CREATE TABLE IF NOT EXISTS player_match_stats (
    match_id        INTEGER NOT NULL REFERENCES matches(id) ON DELETE CASCADE,
    player_num      TEXT    NOT NULL,
    total           INTEGER NOT NULL,
    score_sum       REAL    NOT NULL,
    grade_perfect   INTEGER NOT NULL,
    grade_positive  INTEGER NOT NULL,
    grade_regular   INTEGER NOT NULL,
    grade_error     INTEGER NOT NULL,
    s_tot INTEGER, s_good INTEGER,
    r_tot INTEGER, r_good INTEGER,
    e_tot INTEGER, e_good INTEGER,
    a_tot INTEGER, a_good INTEGER,
    d_tot INTEGER, d_good INTEGER,
    b_tot INTEGER, b_good INTEGER,
    perfect_s INTEGER, perfect_r INTEGER, perfect_e INTEGER,
    perfect_a INTEGER, perfect_d INTEGER, perfect_b INTEGER,
    positive_s INTEGER, positive_r INTEGER, positive_e INTEGER,
    positive_a INTEGER, positive_d INTEGER, positive_b INTEGER,
    regular_s INTEGER, regular_r INTEGER, regular_e INTEGER,
    regular_a INTEGER, regular_d INTEGER, regular_b INTEGER,
    error_s INTEGER, error_r INTEGER, error_e INTEGER,
    error_a INTEGER, error_d INTEGER, error_b INTEGER,
    PRIMARY KEY (match_id, player_num)
);
"""

# Mapping from grade symbols to column name prefixes
_GRADE_PREFIX = {'#': 'perfect', '+': 'positive', '!': 'regular', '-': 'error'}


def init_db(conn):
    """Create all database tables if they do not exist and enable foreign key enforcement.

    Executes the _SCHEMA script which creates three tables:
        - 'matches': one row per match file (stem, title, date, youtube URLs).
        - 'team_match_stats': one row per match with all aggregated team statistics,
          including grade counts, per-action totals, phase stats, and point stats.
        - 'player_match_stats': one row per (match, player) pair with the same
          statistical columns as team_match_stats minus the phase/point stats.

    All tables use CREATE TABLE IF NOT EXISTS, so this function is safe to call
    on an existing database without losing data.

    Args:
        conn (sqlite3.Connection): An open database connection.

    Returns:
        None
    """
    conn.executescript(_SCHEMA)
    conn.execute("PRAGMA foreign_keys = ON")
    conn.commit()

# ---------------------------------------------------------------------------
# Upsert
# ---------------------------------------------------------------------------


def _stats_to_row(stats):
    """Convert a stats dict produced by _new_stats() into a flat column-value dict.

    Maps the nested structure of a statistics dictionary to the flat column names
    used in the 'team_match_stats' and 'player_match_stats' tables. Specifically:
        - 'total' and 'score_sum' map directly.
        - 'grades' values map to 'grade_perfect', 'grade_positive', etc.
        - 'actions[A]["tot"]' maps to 'a_tot', 'actions[A]["good"]' to 'a_good', etc.
        - 'grade_count[grade][action]' maps to '<grade_prefix>_<action_lower>',
          e.g. grade_count['#']['A'] → 'perfect_a'.

    The resulting dict does NOT include 'match_id', 'player_num', phase stats,
    or point stats — the caller adds those before insertion.

    Args:
        stats (dict): A statistics dictionary created by _new_stats() and
            populated by _record() calls.

    Returns:
        dict: Flat dict mapping column names (str) to their values (int or float).
    """
    row = {
        'total': stats['total'],
        'score_sum': stats['score_sum'],
        'grade_perfect': stats['grades']['#'],
        'grade_positive': stats['grades']['+'],
        'grade_regular': stats['grades']['!'],
        'grade_error': stats['grades']['-'],
    }
    for action in ACTIONS:
        a_lower = action.lower()
        row[f'{a_lower}_tot'] = stats['actions'][action]['tot']
        row[f'{a_lower}_good'] = stats['actions'][action]['good']
    for grade in GRADES:
        prefix = _GRADE_PREFIX[grade]
        for action in ACTIONS:
            a_lower = action.lower()
            row[f'{prefix}_{a_lower}'] = stats['grade_count'][grade][action]
    return row


def upsert_match(conn, stem, title, parsed):
    """Store or replace one match's complete data in the database.

    Upsert strategy:
        1. INSERT OR UPDATE the 'matches' row for this stem (ON CONFLICT DO UPDATE).
        2. DELETE any existing 'team_match_stats' and 'player_match_stats' rows
           for the same match_id, then INSERT fresh rows.
    This makes the operation fully idempotent — calling it twice with the same
    data leaves the database in an identical state.

    Phase stats (so_good/so_bad/trans) and point stats (bp/so) are computed from
    the parsed rallies here and stored as scalar columns in 'team_match_stats'.
    This avoids having to store raw rally data while still allowing the renderer
    to display these stats without re-parsing the source file.

    Players with zero total actions are skipped and not written to the DB.

    Args:
        conn (sqlite3.Connection): An open database connection.
        stem (str): Filename stem without extension, e.g. 'vodkas_vs_alaba'.
            Used as the unique key in the 'matches' table.
        title (str): Human-readable match title, e.g. 'Vodkas vs Alaba'.
        parsed (dict): Output of parse_log(), containing:
            'players' (dict): Player number → stats dict.
            'team' (dict): Aggregated team stats dict.
            'rallies' (list): Rally token lists, needed to compute phase/point stats.
            'youtube_urls' (list[str]): YouTube URLs stored as a JSON array.

    Returns:
        None
    """
    from datetime import date
    generated_date = date.today().strftime('%d/%m/%Y')
    youtube_json = json.dumps(parsed['youtube_urls'])

    # Upsert match row
    conn.execute(
        """INSERT INTO matches (stem, title, generated_date, youtube_urls)
           VALUES (?, ?, ?, ?)
           ON CONFLICT(stem) DO UPDATE SET
               title = excluded.title,
               generated_date = excluded.generated_date,
               youtube_urls = excluded.youtube_urls""",
        (stem, title, generated_date, youtube_json),
    )
    match_id = conn.execute(
        "SELECT id FROM matches WHERE stem = ?", (stem,)
    ).fetchone()[0]

    # Team stats
    team_row = _stats_to_row(parsed['team'])
    rallies = parsed['rallies']
    phase = calculate_phase_stats(rallies)
    points = calculate_point_stats(rallies)
    team_row.update({
        'so_good_attempts': phase['so_good']['attempts'],
        'so_good_kills': phase['so_good']['kills'],
        'so_bad_attempts': phase['so_bad']['attempts'],
        'so_bad_kills': phase['so_bad']['kills'],
        'trans_attempts': phase['trans']['attempts'],
        'trans_kills': phase['trans']['kills'],
        'bp_total': points['bp']['total'],
        'bp_won': points['bp']['won'],
        'so_total': points['so']['total'],
        'so_won': points['so']['won'],
    })
    team_row['match_id'] = match_id

    # Delete existing team/player rows for idempotency
    conn.execute("DELETE FROM team_match_stats WHERE match_id = ?", (match_id,))
    conn.execute("DELETE FROM player_match_stats WHERE match_id = ?", (match_id,))

    cols = ', '.join(team_row.keys())
    placeholders = ', '.join(['?'] * len(team_row))
    conn.execute(
        f"INSERT INTO team_match_stats ({cols}) VALUES ({placeholders})",
        list(team_row.values()),
    )

    # Player stats
    for player_num, player_data in parsed['players'].items():
        if player_data['total'] == 0:
            continue
        p_row = _stats_to_row(player_data)
        p_row['match_id'] = match_id
        p_row['player_num'] = player_num
        cols = ', '.join(p_row.keys())
        placeholders = ', '.join(['?'] * len(p_row))
        conn.execute(
            f"INSERT INTO player_match_stats ({cols}) VALUES ({placeholders})",
            list(p_row.values()),
        )

    conn.commit()

# ---------------------------------------------------------------------------
# Query helpers
# ---------------------------------------------------------------------------


def _row_to_stats(row):
    """Reconstruct a parse_log()-compatible stats dict from a flat DB row dict.

    This is the inverse of _stats_to_row(). It reads the flat column names from
    a database row (as a plain dict with string keys) and rebuilds the nested
    structure expected by calculate_rating(), build_card_html(), and the renderer.

    The reconstructed dict has exactly the same shape as a dict produced by
    _new_stats() and populated via _record() calls, so all downstream functions
    accept it without modification.

    Note: 'grade_count' values for grade '!' are stored under column prefix 'regular_'
    and for grade '-' under 'error_', matching the _GRADE_PREFIX mapping.

    Args:
        row (dict): A flat dict of column name → value, e.g. as returned by
            dict(sqlite3.Row). Must contain all columns written by _stats_to_row().

    Returns:
        dict: A stats dict with keys 'total', 'score_sum', 'grades', 'actions',
            and 'grade_count', identical in structure to _new_stats() output.
    """
    stats = {
        'total': row['total'],
        'score_sum': row['score_sum'],
        'grades': {
            '#': row['grade_perfect'],
            '+': row['grade_positive'],
            '!': row['grade_regular'],
            '-': row['grade_error'],
        },
        'actions': {},
        'grade_count': {g: {} for g in GRADES},
    }
    for action in ACTIONS:
        a_lower = action.lower()
        stats['actions'][action] = {
            'tot': row[f'{a_lower}_tot'],
            'good': row[f'{a_lower}_good'],
        }
    for grade in GRADES:
        prefix = _GRADE_PREFIX[grade]
        for action in ACTIONS:
            a_lower = action.lower()
            stats['grade_count'][grade][action] = row[f'{prefix}_{a_lower}']
    return stats


def get_match(conn, stem):
    """Return a dict identical in structure to parse_log() output for the given match.

    Reconstructs the full parsed-data dict from the database by:
        1. Looking up the match row to get match_id and youtube_urls.
        2. Reading 'team_match_stats' and converting it with _row_to_stats().
        3. Reading all 'player_match_stats' rows and converting each one.

    The 'rallies' key is always returned as an empty list because raw rally
    tokens are not stored in the database. Callers that need phase/point stats
    for rendering should use get_phase_stats_from_db() and get_point_stats_from_db()
    and inject them as '_phase_stats' / '_point_stats' into the returned dict.

    Args:
        conn (sqlite3.Connection): An open database connection.
        stem (str): Filename stem, e.g. 'vodkas_vs_alaba'.

    Returns:
        dict with keys 'players', 'team', 'rallies' (empty list), 'youtube_urls';
            or None if no match with the given stem exists in the database.
    """
    conn.row_factory = sqlite3.Row
    match_row = conn.execute(
        "SELECT * FROM matches WHERE stem = ?", (stem,)
    ).fetchone()
    if not match_row:
        return None

    match_id = match_row['id']
    youtube_urls = json.loads(match_row['youtube_urls'])

    team_row = conn.execute(
        "SELECT * FROM team_match_stats WHERE match_id = ?", (match_id,)
    ).fetchone()
    team = _row_to_stats(dict(team_row))

    player_rows = conn.execute(
        "SELECT * FROM player_match_stats WHERE match_id = ?", (match_id,)
    ).fetchall()
    players = {}
    for p_row in player_rows:
        p_dict = dict(p_row)
        players[p_dict['player_num']] = _row_to_stats(p_dict)

    # Rallies are not stored — return empty list.
    # Phase/point stats are pre-calculated in team_match_stats.
    return {
        'players': players,
        'team': team,
        'rallies': [],
        'youtube_urls': youtube_urls,
    }


def get_phase_stats_from_db(conn, stem):
    """Return pre-computed phase stats for a match, read directly from the database.

    Reads the so_good, so_bad, and trans attempts/kills columns stored in
    'team_match_stats' during upsert_match(). This avoids needing to re-parse
    the source .txt file or store raw rally data.

    The returned dict has the same shape as the output of calculate_phase_stats(),
    so it can be passed directly to build_phase_card_html().

    Args:
        conn (sqlite3.Connection): An open database connection.
        stem (str): Filename stem, e.g. 'vodkas_vs_alaba'.

    Returns:
        dict: Keys 'so_good', 'so_bad', 'trans', each mapping to
            {'attempts': int, 'kills': int}. Returns all-zero values if
            the match is not found.
    """
    conn.row_factory = sqlite3.Row
    row = conn.execute(
        """SELECT t.* FROM team_match_stats t
           JOIN matches m ON m.id = t.match_id
           WHERE m.stem = ?""", (stem,)
    ).fetchone()
    if not row:
        return {
            'so_good': {'attempts': 0, 'kills': 0},
            'so_bad': {'attempts': 0, 'kills': 0},
            'trans': {'attempts': 0, 'kills': 0},
        }
    return {
        'so_good': {'attempts': row['so_good_attempts'], 'kills': row['so_good_kills']},
        'so_bad': {'attempts': row['so_bad_attempts'], 'kills': row['so_bad_kills']},
        'trans': {'attempts': row['trans_attempts'], 'kills': row['trans_kills']},
    }


def get_point_stats_from_db(conn, stem):
    """Return pre-computed point stats for a match, read directly from the database.

    Reads the bp_total, bp_won, so_total, so_won columns stored in
    'team_match_stats' during upsert_match(). This avoids needing to re-parse
    the source .txt file or store raw rally data.

    The returned dict has the same shape as the output of calculate_point_stats(),
    so it can be passed directly to build_scoring_card_html().

    Args:
        conn (sqlite3.Connection): An open database connection.
        stem (str): Filename stem, e.g. 'vodkas_vs_alaba'.

    Returns:
        dict: Keys 'bp' and 'so', each mapping to {'total': int, 'won': int}.
            Returns all-zero values if the match is not found.
    """
    conn.row_factory = sqlite3.Row
    row = conn.execute(
        """SELECT t.* FROM team_match_stats t
           JOIN matches m ON m.id = t.match_id
           WHERE m.stem = ?""", (stem,)
    ).fetchone()
    if not row:
        return {'bp': {'total': 0, 'won': 0}, 'so': {'total': 0, 'won': 0}}
    return {
        'bp': {'total': row['bp_total'], 'won': row['bp_won']},
        'so': {'total': row['so_total'], 'won': row['so_won']},
    }


def get_all_matches_meta(conn):
    """Return metadata for all stored matches in the format expected by render_index_page().

    Joins 'matches' and 'team_match_stats' to compute per-match summary values:
        - rating: calculated from score_sum / total via calculate_rating().
        - perfect_pct: integer percentage of '#'-grade actions over total.

    Results are ordered alphabetically by filename stem, which corresponds to
    chronological order when filenames follow the 'vodkas_vs_<opponent>' convention.

    Args:
        conn (sqlite3.Connection): An open database connection.

    Returns:
        list[dict]: One dict per match, each with keys:
            'title'          (str):   Human-readable match title.
            'file'           (str):   Relative HTML filename, e.g. 'vodkas_vs_alaba.html'.
            'rating'         (float): Team performance rating (1.0–10.0).
            'total_actions'  (int):   Total recorded team actions.
            'perfect_pct'    (int):   Percentage of Perfect ('#') grade actions.
    """
    conn.row_factory = sqlite3.Row
    rows = conn.execute(
        """SELECT m.stem, m.title, t.total, t.score_sum, t.grade_perfect
           FROM matches m
           JOIN team_match_stats t ON t.match_id = m.id
           ORDER BY m.stem"""
    ).fetchall()

    matches = []
    for row in rows:
        total = row['total']
        rating = calculate_rating({'total': total, 'score_sum': row['score_sum']})
        pct = round((row['grade_perfect'] / total) * 100) if total > 0 else 0
        matches.append({
            'title': row['title'],
            'file': f"{row['stem']}.html",
            'rating': rating,
            'total_actions': total,
            'perfect_pct': pct,
        })
    return matches
