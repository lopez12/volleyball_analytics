"""Volleyball Analytics - Parsing and calculation engine.

Contains all constants, data structures, parsing logic, and statistical
calculations. No knowledge of HTML or SQLite.
"""

import json
import math
import re
from datetime import date as _date
from urllib.parse import parse_qs, urlparse

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------
# Legacy score_sum total only; not used by any rating.
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

# Shared grade values and player-rating constants. Derived from the
# 2026-11-11 analysis (#56) and frozen: never recomputed per dataset.
# Per-action value of each grade for team, player and per-action ratings.
PLAYER_GRADE_VALUES = {
    'S': {'#': 1.0, '+': 0.1, '!': -0.2, '-': -1.0},
    'R': {'#': 0.5, '+': 0.25, '!': -0.2, '-': -1.0},
    'E': {'#': 0.4, '+': 0.2, '!': -0.4, '-': -1.0},
    'A': {'#': 1.0, '+': 0.0, '!': -0.2, '-': -1.0},
    'D': {'#': 0.5, '+': 0.25, '!': 0.0, '-': -0.8},
    'B': {'#': 1.0, '+': 0.2, '!': -0.3, '-': -0.8},
}
# Per-role action mix; keys equal POSITION_LABELS keys.
ROLE_ACTION_WEIGHTS = {
    'S': {'E': 0.50, 'S': 0.15, 'D': 0.15, 'R': 0.10, 'A': 0.05, 'B': 0.05},
    'OH': {'A': 0.35, 'R': 0.25, 'S': 0.15, 'D': 0.15, 'B': 0.05, 'E': 0.05},
    'OPP': {'A': 0.45, 'S': 0.15, 'B': 0.15, 'D': 0.15, 'R': 0.05, 'E': 0.05},
    'MB': {'A': 0.40, 'B': 0.25, 'S': 0.20, 'D': 0.10, 'R': 0.0, 'E': 0.05},
    'L': {'R': 0.45, 'D': 0.40, 'E': 0.10, 'S': 0.05, 'A': 0.0, 'B': 0.0},
    'U': {a: 1 / 6 for a in ACTIONS},
}
SETTER_SHARE_LOW = 0.15  # E share at or below which no setter profile is applied
SETTER_SHARE_HIGH = 0.55  # E share at or above which the full setter profile is applied
ASSIST_WEIGHT = 0.30  # weight of the setter assist term, scaled by the setter factor
RATING_SHRINK = 3  # pseudo-touches at value 0 per action
RATING_CENTER = 7.0  # rating of an average raw score
RATING_RAW_MEAN = 0.066  # raw score mapped to RATING_CENTER
RATING_SCALE = 11.6  # rating points per unit of raw score

# Team and per-action scales fitted on 2026-11-11 data (#57) and frozen.
TEAM_RATING_RAW_MEAN = 0.114  # team raw score mapped to RATING_CENTER
TEAM_RATING_SCALE = 17.6  # team rating points per unit of raw score
# Per-action average raw score mapped to RATING_CENTER.
ACTION_NOTA_CENTER = {
    'S': 0.206,
    'R': 0.023,
    'E': 0.071,
    'A': 0.1,
    'D': 0.069,
    'B': 0.155,
}
# Per-action Nota points per unit of raw score.
ACTION_NOTA_SCALE = {
    'S': 4.8,
    'R': 5.3,
    'E': 7.3,
    'A': 4.3,
    'D': 5.8,
    'B': 4.0,
}

# ---------------------------------------------------------------------------
# Player position config
# ---------------------------------------------------------------------------
# Per-team rosters (player number -> position / name) are NOT defined here.
# They live in each dataset's team.json and are loaded via load_team_config().
# Only the universal position label map is global.

POSITION_LABELS = {
    'S': 'Acomodo',
    'OH': 'Esquina',
    'OPP': 'Opuesto',
    'MB': 'Centro',
    'L': 'Líbero',
    'U': 'Universal',
}

# Per-set role override: '@role: <num>=<POS>[, <num>=<POS> ...]'. Applies to the
# '---' block it appears in; POS must be a POSITION_LABELS key.
_RE_ROLE = re.compile(r'^@role:\s*(\d+=[A-Za-z]+(?:\s*,\s*\d+=[A-Za-z]+)*)\s*$', re.IGNORECASE)
_RE_ROLE_ENTRY = re.compile(r'(\d+)=([A-Za-z]+)')


def _parse_role_line(trimmed):
    """Parse a ``@role:`` line into ``(num, POS)`` entries, or return None.

    Args:
        trimmed (str): A stripped log line, e.g. '@role: 2=S, 25=MB'.

    Returns:
        list[tuple[str, str]] | None: Entries in line order with POS upper-cased;
            None when the syntax is wrong or any POS is not a POSITION_LABELS key.
    """
    m = _RE_ROLE.match(trimmed)
    if not m:
        return None
    entries = [(num, pos.upper()) for num, pos in _RE_ROLE_ENTRY.findall(m.group(1))]
    if any(pos not in POSITION_LABELS for _, pos in entries):
        return None
    return entries


def load_team_config(path):
    """Load a per-dataset team.json and return team/tournament metadata plus roster maps.

    The team.json schema is:
        {
            "team": "Vodkas",
            "tournament": "Atlas Chapalita Cup",
            "type": "tournament",            # "tournament" or "friendly"
            "roster": {
                "7": { "name": "Gio", "position": "OH" },
                ...
            },
            "objectives": [                   # optional season goals (see renderer)
                { "label": "Saques ace", "current": 87, "target": 130 },
                ...
            ]
        }

    Args:
        path (str | Path): Path to a dataset's team.json file.

    Returns:
        dict with keys:
            'team' (str): Display team name.
            'tournament' (str): Display tournament/competition name.
            'type' (str): 'tournament' or 'friendly'.
            'positions' (dict): Maps player number string -> position code.
            'names' (dict): Maps player number string -> display name. Players
                without a name are omitted so callers can fall back to '#<num>'.
            'objectives' (list): Optional raw season-goal entries (empty when
                absent); normalized and rendered by render_team_season_page().
    """
    with open(path, encoding='utf-8') as f:
        cfg = json.load(f)
    roster = cfg.get('roster', {})
    positions = {num: info.get('position', 'U') for num, info in roster.items()}
    names = {num: info['name'] for num, info in roster.items() if info.get('name')}
    objectives = cfg.get('objectives', [])
    if not isinstance(objectives, list):
        objectives = []
    return {
        'team': cfg.get('team', ''),
        'tournament': cfg.get('tournament', ''),
        'type': cfg.get('type', 'tournament'),
        'positions': positions,
        'names': names,
        'objectives': objectives,
    }


_RE_PLAYER = re.compile(r'^(\d+)([SREADB])([#+!\-])$')
_RE_TEAM = re.compile(r'^([SREADB])([#+!\-])$')
_RE_ANY = re.compile(r'^(\d*)([SREADB])([#+!\-])$')
_RE_PHASE = re.compile(r'^(\d+)([SREADB])([#+!\-])$|^([SREADB])([#+!\-])$')
_RE_YT = re.compile(r'^https?://(www\.)?(youtube\.com|youtu\.be)/')
_RE_SET = re.compile(r'^@set:\s*(\d+)-(\d+)$', re.IGNORECASE)
_RE_START = re.compile(r'^@start:\s*(\d+)-(\d+)$', re.IGNORECASE)
# Optional, match-level play date. ISO 8601 only; validity is confirmed against
# the calendar in _parse_date_token (e.g. '2026-13-40' matches the shape but is
# rejected). Absence is never an error.
_RE_DATE = re.compile(r'^@date:\s*(\d{4})-(\d{2})-(\d{2})$', re.IGNORECASE)


def _parse_date_token(trimmed):
    """Return the ISO date string for a valid ``@date:`` line, else None.

    Args:
        trimmed (str): A stripped log line, e.g. '@date: 2026-05-17'.

    Returns:
        str | None: 'YYYY-MM-DD' when the line is a well-formed, real calendar
            date; None when the shape is wrong or the date is impossible.
    """
    m = _RE_DATE.match(trimmed)
    if not m:
        return None
    try:
        return _date(int(m.group(1)), int(m.group(2)), int(m.group(3))).isoformat()
    except ValueError:
        return None


# Inline trailing rally-outcome tokens (Phase 2 - grade integrity).
#   @won        -> we scored the rally by our own play (a kill).
#   @won:re     -> we scored, cause = rival error (gifted point).
#   @won:se     -> we scored because the opponent faulted their serve
#                  (a subset of :re; a "free" side-out won with zero touches).
#   @lost       -> the opponent scored the rally.
# Tokens are case-insensitive and consumed as the rally outcome (not stored as
# action tokens). See ARCHITECT-BRIEF-scoring-phase2.md.
_RE_OUTCOME = re.compile(r'^@(won|lost)(?::(re|se))?$', re.IGNORECASE)


def _parse_outcome_token(token):
    """Parse an inline rally-outcome token (Phase 2), or return None if not one.

    Recognises the ``@won`` / ``@lost`` grammar (optionally with a ``:re`` or
    ``:se`` cause suffix), case-insensitively. Cause suffixes only apply to
    ``@won``; any cause attached to ``@lost`` is ignored.

    Args:
        token (str): A single whitespace-delimited token from a rally line.

    Returns:
        dict | None: ``{'result': 'won'|'lost', 'cause': 're'|'se'|None}`` when
            the token is a valid outcome token, otherwise None. A ``'se'`` cause
            implies (and is a subset of) a ``'re'`` rival-error gift.
    """
    m = _RE_OUTCOME.match(token)
    if not m:
        return None
    result = m.group(1).lower()
    cause = m.group(2).lower() if m.group(2) else None
    if result == 'lost':
        cause = None
    return {'result': result, 'cause': cause}


# Optional, per-rally video timestamp (Phase 4). A trailing metadata token
# '@t:<start>[-<end>]' giving seconds (int or decimal) into that set's video,
# consumed as rally timing rather than a played token. Absence is never an
# error; a malformed token is ignored here (validate_logs.py WARNs on it).
_RE_TIMESTAMP = re.compile(r'^@t:(\d+(?:\.\d+)?)(?:-(\d+(?:\.\d+)?))?$', re.IGNORECASE)


def _parse_timestamp_token(token):
    """Parse a per-rally ``@t:<start>[-<end>]`` timestamp token, or return None.

    Args:
        token (str): A single whitespace-delimited token from a rally line.

    Returns:
        dict | None: ``{'start': float, 'end': float | None}`` in seconds when
            the token is well-formed, otherwise None. ``end`` is None when only
            a start time is given (e.g. ``@t:12``).
    """
    m = _RE_TIMESTAMP.match(token)
    if not m:
        return None
    end = float(m.group(2)) if m.group(2) is not None else None
    return {'start': float(m.group(1)), 'end': end}


# ---------------------------------------------------------------------------
# Data helpers
# ---------------------------------------------------------------------------


def _new_stats():
    """Create and return a fresh, zeroed-out statistics dictionary for a player or team.

    The returned dictionary has the following structure:
        - 'total' (int): Total number of recorded actions across all types and grades.
        - 'score_sum' (float): Legacy cumulative score. Each action contributes
          WEIGHTS[grade] to this sum; it is not used by any rating.
        - 'grades' (dict): Count of actions per grade symbol:
            '#' (Perfect), '+' (Positive), '!' (Regular), '-' (Error).
        - 'actions' (dict): Per-action-letter summary with two sub-keys:
            'tot' (int): Total number of times this action was recorded.
            'good' (int): Times this action received a '#' or '+' grade.
          Action letters: 'S' (Serve), 'R' (Reception), 'E' (Set),
          'A' (Attack), 'D' (Defense), 'B' (Block).
        - 'grade_count' (dict): Cross-tabulation of grade × action counts.
          Outer key is a grade symbol, inner key is an action letter.
          e.g. grade_count['#']['A'] gives the number of perfect attacks.
        - 'assists' (dict): Count per grade of the attack that immediately
          followed a player set on the same rally line (see _record_assists).
        - 'role_blocks' (list): Per '---' block in which a player touched the
          ball, {'touches', 'sets', 'role'}; always empty for team stats.

    Returns:
        dict: A zeroed statistics dictionary ready to accumulate recorded actions.
    """
    return {
        'total': 0,
        'score_sum': 0.0,
        'grades': {g: 0 for g in GRADES},
        'actions': {a: {'tot': 0, 'good': 0} for a in ACTIONS},
        'grade_count': {g: {a: 0 for a in ACTIONS} for g in GRADES},
        'assists': {g: 0 for g in GRADES},
        'role_blocks': [],
    }


def _record(stats, action, grade):
    """Record a single volleyball action into a statistics dictionary, updating all counters.

    Mutates the provided `stats` dictionary in place by:
        - Incrementing 'total' by 1.
        - Adding WEIGHTS[grade] to 'score_sum'.
        - Incrementing 'grades[grade]' by 1.
        - Incrementing 'actions[action]["tot"]' by 1.
        - Incrementing 'actions[action]["good"]' by 1 if the grade is '#' or '+'.
        - Incrementing 'grade_count[grade][action]' by 1.

    Args:
        stats (dict): A statistics dictionary created by _new_stats(), modified in place.
        action (str): Single-letter action code — one of 'S', 'R', 'E', 'A', 'D', 'B'.
        grade (str): Single-character quality grade — one of '#', '+', '!', '-'.

    Returns:
        None
    """
    stats['total'] += 1
    stats['grades'][grade] += 1
    stats['score_sum'] += WEIGHTS.get(grade, 0)
    stats['actions'][action]['tot'] += 1
    if grade in ('#', '+'):
        stats['actions'][action]['good'] += 1
    stats['grade_count'][grade][action] += 1


def _record_assists(tokens, players, team):
    """Credit setter assists for one rally line.

    A player set token (``<num>E<g>``) immediately followed by an attack token
    (player or team ``A<g>``) credits ``assists[<attack grade>]`` to both the
    setter and the team. Only adjacent tokens of the same line count.

    Args:
        tokens (list[str]): The rally's valid play tokens, in order.
        players (dict): Player number -> stats dict; must contain every setter.
        team (dict): Team stats dict.

    Returns:
        None
    """
    for token, following in zip(tokens, tokens[1:], strict=False):
        m_set = _RE_PLAYER.match(token)
        m_att = _RE_ANY.match(following)
        if m_set and m_set.group(2) == 'E' and m_att and m_att.group(2) == 'A':
            grade = m_att.group(3)
            players[m_set.group(1)]['assists'][grade] += 1
            team['assists'][grade] += 1


# ---------------------------------------------------------------------------
# Parsing
# ---------------------------------------------------------------------------


def parse_log(log_string, positions=None):
    """Parse a raw match log string and return structured statistics for all players and the team.

    Each non-empty line in the log represents one rally. Tokens within a line are
    space-separated and follow one of these formats:
        - Player token:  '<number><action><grade>'  e.g. '7S#', '10A+'.
        - Team token:    '<action><grade>'           e.g. 'S#', 'R-' (no player number).
        - Set separator: '---'                       skipped silently.
        - YouTube link:  '@youtube: <url>'           URL stored if it is a valid
                                                     youtube.com or youtu.be address.
        - Set score:     '@set: V-R'                 e.g. '@set: 25-18'. Team score
                                                     first, rival score second.
        - Match date:    '@date: YYYY-MM-DD'         Optional, match-level. The
                                                     first valid ISO date wins;
                                                     malformed dates are dropped.
        - Set role:      '@role: <num>=<POS>[, ...]' Optional role override for
                                                     its '---' block only; the
                                                     first valid entry per player
                                                     wins; malformed lines are
                                                     dropped. Never a rally.
        - Rally outcome: '@won' / '@lost' / '@won:re' / '@won:se'  (inline,
                                                     trailing, case-insensitive).
                                                     Consumed as the rally's
                                                     outcome, not a played token.
                                                     A line consisting solely of
                                                     an outcome token is a valid
                                                     "touchless" rally.
        - Rally timestamp: '@t:<start>[-<end>]'      Optional, per-rally video
                                                     time in seconds (int or
                                                     decimal) into that set's
                                                     video, e.g. '@t:3-9' or
                                                     '@t:12'. Consumed as rally
                                                     timing, not a played token;
                                                     absence is never an error.
    Tokens that match neither the player nor team pattern are silently ignored.
    Player tokens are recorded in both the individual player's stats and the team stats.
    Team-only tokens are recorded only in team stats.

    Args:
        log_string (str): Full text content of a .txt match log file.
        positions (dict | None): Roster player number -> position code, used
            only for replay snapshot player ratings.

    Returns:
        dict with the following keys:
            'players' (dict): Maps player number strings (e.g. '7') to their
                individual statistics dictionaries (see _new_stats()), including
                per-block 'role_blocks' and setter 'assists'.
            'team' (dict): Aggregated statistics dictionary for the whole team,
                including both player-tagged tokens and bare team tokens.
            'rallies' (list[list[str]]): Ordered list of rallies; each rally is
                a list of valid token strings in the order they appeared on that line.
                Rallies with no valid tokens are omitted, unless the line carried
                an outcome token (a "touchless" rally, e.g. a standalone '@won:se'),
                in which case an empty token list is kept so its outcome is aligned.
            'rally_outcomes' (list[dict]): One entry per rally in 'rallies' (same
                order/length), each {'result': 'won'|'lost'|None, 'cause':
                're'|'se'|None}. 'result' is None when the rally carried no
                explicit outcome token (heuristic-fallback marker). 'se' implies
                a gifted serve-error point and is a subset of 're'.
            'rally_timestamps' (list): One entry per rally in 'rallies' (same
                order/length): {'start': float, 'end': float|None} in seconds
                when the rally carried an '@t:' token, else None. A rally that
                carried only a timestamp (no plays or outcome) is retained so
                its timing stays aligned (a pre-analysis segment).
            'points' (dict): Team-level earned/gifted point summary derived from
                the explicit outcomes: 'won', 'won_kill', 'won_rival_error',
                'won_serve_error', 'lost'.
            'youtube_urls' (list[str]): Validated YouTube URLs found in
                '@youtube:' lines, in the order they appear in the file.
            'set_scores' (list[tuple[int, int]]): List of (team, rival) score
                tuples, one per '@set:' line, in file order. Empty list if none.
            'match_date' (str | None): The match play date as an ISO
                'YYYY-MM-DD' string from the first valid '@date:' line, or None
                when absent or malformed. Distinct from the report build date.
            'replay' (dict): Additive ordered source-set model, exclusion
                diagnostics, certified timelines and completed-prefix snapshots.
                Stricter replay eligibility does not change legacy outputs.
    """
    lines = log_string.strip().splitlines()
    rallies = []
    rally_outcomes = []
    rally_timestamps = []
    players = {}
    youtube_urls = []
    set_scores = []
    match_date = None
    team = _new_stats()
    replay_sets = []
    replay_set = _new_replay_set()
    block_counts = {}  # player -> [touches, sets] in the current block

    def close_block():
        for num, (touches, sets) in block_counts.items():
            players[num]['role_blocks'].append(
                {'touches': touches, 'sets': sets, 'role': replay_set['roles'].get(num)}
            )
        block_counts.clear()
        if _replay_set_has_content(replay_set):
            replay_sets.append(replay_set)

    for line in lines:
        trimmed = line.strip()
        if trimmed == '---':
            close_block()
            replay_set = _new_replay_set()
            continue
        if not trimmed:
            continue
        if trimmed.lower().startswith('@role:'):
            for num, pos in _parse_role_line(trimmed) or []:
                replay_set['roles'].setdefault(num, pos)
            continue
        if trimmed.lower().startswith('@youtube:'):
            url = trimmed[9:].strip()
            replay_set['videos'].append(url)
            if _RE_YT.match(url):
                youtube_urls.append(url)
            continue
        if trimmed.lower().startswith('@date:'):
            # First valid date wins; malformed dates are dropped, not rallies.
            if match_date is None:
                iso = _parse_date_token(trimmed)
                if iso is not None:
                    match_date = iso
            continue
        if trimmed.lower().startswith('@start:'):
            m_start = _RE_START.match(trimmed)
            if m_start:
                replay_set['starts'].append([int(m_start[1]), int(m_start[2])])
                if replay_set['rallies']:
                    replay_set['diagnostics'].append(
                        'El marcador inicial debe aparecer antes de la primera jugada.'
                    )
            else:
                replay_set['diagnostics'].append('Formato de @start: no válido; usa @start: V-R.')
            continue
        m_set = _RE_SET.match(trimmed)
        if m_set:
            set_scores.append((int(m_set.group(1)), int(m_set.group(2))))
            replay_set['scores'].append([int(m_set.group(1)), int(m_set.group(2))])
            continue

        tokens = trimmed.split()
        rally_tokens = []
        outcome = {'result': None, 'cause': None}
        outcome_seen = False
        timestamp = None
        ts_seen = False
        replay_tokens = []
        replay_outcomes = []
        replay_times = []
        replay_comment = False

        for token in tokens:
            if token.startswith('#'):
                replay_comment = True
            replay_content = not replay_comment
            parsed_ts = _parse_timestamp_token(token)
            if parsed_ts is not None:
                if replay_content:
                    replay_times.append(parsed_ts)
                # First timestamp token wins; duplicates on the line are ignored.
                if not ts_seen:
                    timestamp = parsed_ts
                    ts_seen = True
                continue
            parsed_outcome = _parse_outcome_token(token)
            if parsed_outcome is not None:
                if replay_content:
                    replay_outcomes.append(parsed_outcome)
                # First outcome token wins; duplicates on the same line are ignored.
                if not outcome_seen:
                    outcome = parsed_outcome
                    outcome_seen = True
                continue
            m = _RE_PLAYER.match(token)
            if m:
                num, action, grade = m.group(1), m.group(2), m.group(3)
                if num not in players:
                    players[num] = _new_stats()
                _record(players[num], action, grade)
                _record(team, action, grade)
                counts = block_counts.setdefault(num, [0, 0])
                counts[0] += 1
                counts[1] += action == 'E'
                rally_tokens.append(token)
                if replay_content:
                    replay_tokens.append(token)
            else:
                m = _RE_TEAM.match(token)
                if m:
                    action, grade = m.group(1), m.group(2)
                    _record(team, action, grade)
                    rally_tokens.append(token)
                    if replay_content:
                        replay_tokens.append(token)
                elif replay_content:
                    replay_set['diagnostics'].append(
                        f'Contenido no reconocido: {token}. No se puede confirmar el registro completo.'
                    )

        _record_assists(rally_tokens, players, team)

        if replay_tokens or replay_outcomes or replay_times:
            replay_set['rallies'].append(
                {
                    'tokens': replay_tokens,
                    'outcomes': replay_outcomes,
                    'timestamps': replay_times,
                }
            )

        # Keep the rally when it has playable tokens OR carried an explicit
        # outcome (a touchless rally, e.g. an opponent serve fault '@won:se') OR
        # only a timestamp (a pre-analysis segment to be tagged later, Phase 4).
        if rally_tokens or outcome_seen or ts_seen:
            rallies.append(rally_tokens)
            rally_outcomes.append(outcome)
            rally_timestamps.append(timestamp)

    close_block()
    points = calculate_earned_points(rally_outcomes)
    return {
        'players': players,
        'team': team,
        'rallies': rallies,
        'rally_outcomes': rally_outcomes,
        'rally_timestamps': rally_timestamps,
        'points': points,
        'youtube_urls': youtube_urls,
        'set_scores': set_scores,
        'match_date': match_date,
        'replay': build_replay(replay_sets, positions or {}),
    }


def _new_replay_set():
    """Return an empty source block; exact separators alone delimit blocks."""
    return {
        'rallies': [],
        'videos': [],
        'scores': [],
        'starts': [],
        'diagnostics': [],
        'roles': {},
    }


def _replay_set_has_content(replay_set):
    """Return True when a block holds anything but '@role:' overrides."""
    return any(value for key, value in replay_set.items() if key != 'roles')


def youtube_video_id(url):
    """Return a supported YouTube URL's strict video ID, or None.

    Args:
        url (str): A source video URL.

    Returns:
        str | None: An eleven-character ID, never an arbitrary URL.
    """
    try:
        parsed = urlparse(url)
        if parsed.scheme not in ('https', 'http') or parsed.username or parsed.password:
            return None
        if parsed.netloc.lower() in ('youtu.be', 'www.youtu.be'):
            video_id = parsed.path.removeprefix('/')
        elif parsed.netloc.lower() in ('youtube.com', 'www.youtube.com'):
            if parsed.path == '/watch':
                values = parse_qs(parsed.query).get('v', [])
                video_id = values[0] if len(values) == 1 else ''
            elif parsed.path.startswith(('/embed/', '/shorts/')):
                video_id = parsed.path.split('/')[-1]
            else:
                return None
        else:
            return None
        return video_id if re.fullmatch(r'[A-Za-z0-9_-]{11}', video_id) else None
    except ValueError:
        return None


def _replay_counts(stats, rating):
    """Return detached JSON-compatible counts using the existing formulas."""
    return {
        'touches': stats['total'],
        'aces': stats['grade_count']['#']['S'],
        'kills': stats['grade_count']['#']['A'],
        'blocks': stats['grade_count']['#']['B'],
        'points': sum(stats['grade_count']['#'][action] for action in ('S', 'A', 'B')),
        'errors': stats['grades']['-'],
        'attack_efficiency': calculate_efficiency(stats)['attack_eff'],
        'rating': rating if stats['total'] else None,
    }


def _replay_snapshots(rallies, start_score, roles=None, positions=None):
    """Build zero and completed-prefix snapshots without mutating shared stats.

    Player rows use calculate_player_rating() over a single block carrying the
    set's '@role:' override; the team row keeps calculate_rating().
    """
    roles = roles or {}
    positions = positions or {}
    team = _new_stats()
    players = {
        _RE_ANY.match(token).group(1): _new_stats()
        for rally in rallies
        for token in rally['tokens']
        if _RE_ANY.match(token).group(1)
    }
    score = list(start_score)
    longest = None

    def player_rating(num, stats):
        block = {
            'touches': stats['total'],
            'sets': stats['actions']['E']['tot'],
            'role': roles.get(num),
        }
        return calculate_player_rating({**stats, 'role_blocks': [block]}, positions.get(num, 'U'))

    def snapshot():
        return {
            'score': list(score),
            'team': _replay_counts(team, calculate_rating(team)),
            'players': [
                {'number': num, **_replay_counts(stats, player_rating(num, stats))}
                for num, stats in sorted(players.items(), key=lambda item: int(item[0]))
            ],
            'longest': dict(longest) if longest is not None else None,
        }

    snapshots = [snapshot()]
    for rally in rallies:
        for token in rally['tokens']:
            num, action, grade = _RE_ANY.match(token).groups()
            _record(team, action, grade)
            if num:
                _record(players[num], action, grade)
        _record_assists(rally['tokens'], players, team)
        score[0 if rally['outcome']['result'] == 'won' else 1] += 1
        duration = rally['end'] - rally['start']
        if longest is None or duration > longest['duration']:
            longest = {'id': rally['id'], 'start': rally['start'], 'duration': duration}
        snapshots.append(snapshot())
    return snapshots


def build_replay(source_sets, positions=None):
    """Certify source blocks and produce per-set replay payloads and diagnostics.

    Args:
        source_sets (list[dict]): Ordered blocks retained by the normal parser.
        positions (dict | None): Roster player number -> position code for
            snapshot player ratings.

    Returns:
        dict: All source sets (including exclusions), with eligible timelines
            and deterministic snapshots. No outcome or timing is inferred.
    """
    sets = []
    for number, source in enumerate(source_sets, 1):
        reasons = list(source['diagnostics'])
        videos = source['videos']
        video_id = youtube_video_id(videos[0]) if len(videos) == 1 else None
        if not video_id:
            reasons.append('Se requiere una única URL de YouTube válida con ID de 11 caracteres.')
        scores = source['scores']
        starts = source['starts']
        start_score = starts[0] if starts else [0, 0]
        if len(starts) > 1:
            reasons.append('Hay más de un marcador inicial en el set.')
        if scores and any(
            start > final for start, final in zip(start_score, scores[0], strict=True)
        ):
            reasons.append('El marcador inicial supera el marcador final del set.')
        if scores and any(score != scores[0] for score in scores):
            reasons.append('Hay marcadores finales contradictorios en el set.')
        if not source['rallies']:
            reasons.append('El set no contiene jugadas registradas.')
        rallies = []
        previous_end = None
        for index, rally in enumerate(source['rallies'], 1):
            prefix = f'Jugada {index}: '
            outcomes = rally['outcomes']
            times = rally['timestamps']
            if len(outcomes) != 1:
                reasons.append(prefix + 'se requiere exactamente un resultado explícito.')
            if not rally['tokens'] and outcomes != [{'result': 'won', 'cause': 'se'}]:
                reasons.append(prefix + 'faltan toques calificados; podría ser solo segmentación.')
            valid_time = (
                len(times) == 1
                and times[0]['end'] is not None
                and math.isfinite(times[0]['start'])
                and math.isfinite(times[0]['end'])
                and 0 <= times[0]['start'] <= times[0]['end']
            )
            if not valid_time:
                reasons.append(
                    prefix + 'se requiere un intervalo finito completo con 0 ≤ inicio ≤ fin.'
                )
            else:
                start, end = times[0]['start'], times[0]['end']
                if previous_end is not None and previous_end > start:
                    reasons.append(prefix + 'el intervalo se superpone o retrocede en el video.')
                previous_end = end
                if len(outcomes) == 1:
                    rallies.append(
                        {
                            'id': f's{number}-r{index}',
                            'number': index,
                            'start': start,
                            'end': end,
                            'tokens': rally['tokens'],
                            'outcome': outcomes[0],
                        }
                    )
        if scores and all(len(r['outcomes']) == 1 for r in source['rallies']):
            actual = [
                sum(r['outcomes'][0]['result'] == result for r in source['rallies'])
                for result in ('won', 'lost')
            ]
            recorded = actual
            actual = [start + count for start, count in zip(start_score, recorded, strict=True)]
            if actual != scores[0]:
                reasons.append('Los resultados de las jugadas no coinciden con el marcador final.')
                missing = [final - count for final, count in zip(scores[0], recorded, strict=True)]
                if all(count >= 0 for count in missing):
                    won, lost = missing
                    reasons.append(
                        f'Faltan {won} ganados y {lost} perdidos; si la grabación empezó tarde, '
                        f'agrega `@start: {won}-{lost}`.'
                    )
        eligible = not reasons
        sets.append(
            {
                'id': f's{number}',
                'number': number,
                'video_id': video_id,
                'final_score': scores[0] if scores else None,
                'start_score': list(start_score),
                'reconciled': bool(scores) and eligible,
                'diagnostics': list(dict.fromkeys(reasons)),
                'eligible': eligible,
                'rallies': rallies if eligible else [],
                'snapshots': (
                    _replay_snapshots(rallies, start_score, source.get('roles'), positions)
                    if eligible
                    else []
                ),
                'source': source,
            }
        )
    return {'sets': sets}


# ---------------------------------------------------------------------------
# Calculations
# ---------------------------------------------------------------------------


def calculate_rating(data):
    """Compute the team rating from its plain touch average on a fixed 1–10 scale.

    Every touch uses PLAYER_GRADE_VALUES, without role weights or shrinkage:

        raw = Σ_action Σ_grade (grade_count[grade][action]
                                * PLAYER_GRADE_VALUES[action][grade]) / total
        rating = round(clamp(RATING_CENTER + (raw - TEAM_RATING_RAW_MEAN)
                             * TEAM_RATING_SCALE, 1.0, 10.0), 1)

    The frozen team scale maps its average raw score to RATING_CENTER (7.0).

    Args:
        data (dict): A statistics dictionary with at minimum:
            'total' (int): Total number of recorded actions.
            'grade_count' (dict): Cross-tab of grade -> action -> count, as
                produced by _new_stats()/_record() or _row_to_stats().
            Not mutated.

    Returns:
        float: Rounded performance rating in the inclusive range [1.0, 10.0].
            Returns 0.0 if 'total' is 0 (no recorded actions).
    """
    total = data['total']
    if total == 0:
        return 0.0
    grade_count = data['grade_count']
    raw = (
        sum(
            grade_count[grade][action] * PLAYER_GRADE_VALUES[action][grade]
            for action in ACTIONS
            for grade in GRADES
        )
        / total
    )
    return round(
        _clamp(RATING_CENTER + (raw - TEAM_RATING_RAW_MEAN) * TEAM_RATING_SCALE, 1.0, 10.0), 1
    )


def _clamp(value, low, high):
    """Return ``value`` limited to the inclusive range [low, high]."""
    return max(low, min(high, value))


def calculate_player_rating(data, position='U'):
    """Compute a player's role-weighted 1-10 match rating.

    Each '---' block in which the player touched the ball resolves a setter
    factor alpha and a base role: an explicit '@role:' override wins ('S' means
    alpha = 1, any other code alpha = 0 with that base); otherwise alpha is
    inferred from the block's set share between SETTER_SHARE_LOW and
    SETTER_SHARE_HIGH, with the roster ``position`` as base ('S' -> 'U').
    Blocks are touch-weighted into one action mix. Per-action scores use the
    match totals with PLAYER_GRADE_VALUES and RATING_SHRINK pseudo-touches; a
    setter assist term (ASSIST_WEIGHT x alpha) values the attacks after her
    sets. The raw score maps linearly onto a fixed scale centered at
    RATING_CENTER. The team rating stays calculate_rating().

    Args:
        data (dict): A player stats dict with 'total', 'actions' and
            'grade_count'; optional 'assists' (missing = zeros) and
            'role_blocks' (missing or empty = one inferred block). Not mutated.
        position (str): Roster position code; unknown codes act as 'U'.

    Returns:
        float: Rating in [1.0, 10.0] rounded to one decimal, or 0.0 when the
            player has no touches.
    """
    total = data['total']
    if total == 0:
        return 0.0
    grade_count = data['grade_count']
    blocks = [b for b in data.get('role_blocks') or [] if b['touches'] > 0] or [
        {'touches': total, 'sets': data['actions']['E']['tot'], 'role': None}
    ]
    span = SETTER_SHARE_HIGH - SETTER_SHARE_LOW
    block_touches = sum(b['touches'] for b in blocks)
    alpha = 0.0
    weights = dict.fromkeys(ACTIONS, 0.0)
    for block in blocks:
        role = block['role']
        if role:
            block_alpha = 1.0 if role == 'S' else 0.0
            base = role if role in ROLE_ACTION_WEIGHTS and role != 'S' else 'U'
        else:
            share = block['sets'] / block['touches']
            block_alpha = _clamp((share - SETTER_SHARE_LOW) / span, 0.0, 1.0)
            base = position if position in ROLE_ACTION_WEIGHTS and position != 'S' else 'U'
        fraction = block['touches'] / block_touches
        alpha += fraction * block_alpha
        for action in ACTIONS:
            weights[action] += fraction * (
                block_alpha * ROLE_ACTION_WEIGHTS['S'][action]
                + (1 - block_alpha) * ROLE_ACTION_WEIGHTS[base][action]
            )

    tots = {a: data['actions'][a]['tot'] for a in ACTIONS}
    if not any(tots[a] > 0 and weights[a] > 0 for a in ACTIONS):
        weights = ROLE_ACTION_WEIGHTS['U']

    num = den = 0.0
    for action in ACTIONS:
        n = tots[action]
        if n == 0 or weights[action] <= 0:
            continue
        value = sum(grade_count[g][action] * PLAYER_GRADE_VALUES[action][g] for g in GRADES)
        num += weights[action] * value / (n + RATING_SHRINK)
        den += weights[action]

    assists = data.get('assists') or dict.fromkeys(GRADES, 0)
    n_ast = sum(assists.values())
    if alpha > 0 and n_ast > 0:
        value = sum(assists[g] * PLAYER_GRADE_VALUES['A'][g] for g in GRADES)
        num += alpha * ASSIST_WEIGHT * value / (n_ast + RATING_SHRINK)
        den += alpha * ASSIST_WEIGHT

    raw = num / den
    return round(_clamp(RATING_CENTER + (raw - RATING_RAW_MEAN) * RATING_SCALE, 1.0, 10.0), 1)


def calculate_action_stats(data):
    """Compute the positive percentage and 1-10 grade ("Nota") for every action.

    Each action's plain touch average uses PLAYER_GRADE_VALUES, without shrinkage:

        avg = Σ_grade grade_count[grade][action]
                      * PLAYER_GRADE_VALUES[action][grade] / tot
        rating = round(clamp(RATING_CENTER + (avg - ACTION_NOTA_CENTER[action])
                             * ACTION_NOTA_SCALE[action], 1.0, 10.0), 1)

    The frozen centers and scales make 7.0 the average quality for that action
    in the calibration data, not a common absolute scale across actions.

    Args:
        data (dict): A stats dict with 'actions' and 'grade_count' keys (from
            parse_log, _row_to_stats, or a season aggregate).

    Returns:
        dict: Keyed by action letter in ACTIONS order, each value being {
            'tot'     (int): Attempts of the action.
            'good'    (int): Attempts graded '#' or '+'.
            'pos_pct' (float|None): good / tot in [0, 1]; None if tot == 0.
            'rating'  (float|None): 1-10 grade; None if tot == 0.
        }
    """
    actions = data['actions']
    gc = data['grade_count']
    result = {}
    for action in ACTIONS:
        tot = actions[action]['tot']
        good = actions[action]['good']
        if tot:
            avg = (
                sum(gc[grade][action] * PLAYER_GRADE_VALUES[action][grade] for grade in GRADES)
                / tot
            )
            pos_pct = good / tot
            rating = round(
                _clamp(
                    RATING_CENTER + (avg - ACTION_NOTA_CENTER[action]) * ACTION_NOTA_SCALE[action],
                    1.0,
                    10.0,
                ),
                1,
            )
        else:
            pos_pct = None
            rating = None
        result[action] = {'tot': tot, 'good': good, 'pos_pct': pos_pct, 'rating': rating}
    return result


def calculate_efficiency(data):
    """Compute standard per-skill efficiency metrics from a stats dictionary.

    Uses only counts already present in a stats dict (from parse_log,
    _row_to_stats, or a season aggregate). Each ratio metric is None when its
    action has zero attempts, so callers can render an em dash.

    Note: 'attack_eff' uses the current kill definition (an A# attack). Until
    Phase 2 (grade integrity) separates execution from outcome, A# can include
    points won on rival errors, so attack efficiency is slightly optimistic.

    Args:
        data (dict): A stats dict with 'actions' and 'grade_count' keys.

    Returns:
        dict: {
            'attack_eff'    (float|None): (A# - A-) / A_tot, range [-1, 1].
            'reception_pos' (float|None): (R# + R+) / R_tot, range [0, 1].
            'serve_ace_pct' (float|None): S# / S_tot.
            'serve_err_pct' (float|None): S- / S_tot.
            'set_pos'       (float|None): (E# + E+) / E_tot.
            'block_kills'   (int): count of B# (stuff blocks).
        }
    """
    actions = data['actions']
    gc = data['grade_count']
    a_tot = actions['A']['tot']
    r_tot = actions['R']['tot']
    s_tot = actions['S']['tot']
    e_tot = actions['E']['tot']
    return {
        'attack_eff': ((gc['#']['A'] - gc['-']['A']) / a_tot) if a_tot else None,
        'reception_pos': (actions['R']['good'] / r_tot) if r_tot else None,
        'serve_ace_pct': (gc['#']['S'] / s_tot) if s_tot else None,
        'serve_err_pct': (gc['-']['S'] / s_tot) if s_tot else None,
        'set_pos': (actions['E']['good'] / e_tot) if e_tot else None,
        'block_kills': gc['#']['B'],
    }


def calculate_phase_stats(rallies, rally_outcomes=None):
    """Compute kill-percentage statistics broken down by the three main game phases.

    Iterates through every rally token-by-token, tracking state to identify
    complete attack sequences. A phase is entered when its trigger action occurs
    and ends (with or without a kill) when an Attack token is seen:
        - 'so_good': Triggered by a good Reception (R# or R+). Represents
          Side-Out play after a quality pass.
        - 'so_bad': Triggered by a poor Reception (R!). Represents Side-Out
          play after a below-average pass.
        - 'trans': Triggered by any Defense (D). Represents Transition play
          (counter-attack) after digging an opponent's attack.

    A kill is counted when the sequence trigger → Set (E) → Attack-perfect (A#)
    is completed without interruption. Any action other than E or A after the
    trigger resets the phase state without counting a kill.

    When explicit rally outcomes are supplied (Phase 2), a terminal A# in a
    rally that was explicitly lost (@lost) is NOT counted as a kill. Rallies
    with no explicit outcome (heuristic fallback) behave exactly as before, so
    token-less logs are unaffected.

    Args:
        rallies (list[list[str]]): Output of parse_log()['rallies']. Each
            element is a list of token strings representing one rally.
        rally_outcomes (list[dict] | None): Optional per-rally explicit outcomes
            from parse_log()['rally_outcomes'], aligned to `rallies`. When None,
            the legacy behaviour (count every completed A#) is used.

    Returns:
        dict: Three keys ('so_good', 'so_bad', 'trans'), each mapping to:
            'attempts' (int): Number of times this phase was entered.
            'kills'    (int): Number of A# attacks that completed the sequence.
    """
    stats = {
        'so_good': {'attempts': 0, 'kills': 0},
        'so_bad': {'attempts': 0, 'kills': 0},
        'trans': {'attempts': 0, 'kills': 0},
    }
    for i, rally in enumerate(rallies):
        outcome = rally_outcomes[i] if rally_outcomes and i < len(rally_outcomes) else None
        rally_lost = bool(outcome and outcome.get('result') == 'lost')
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
                if current_phase and saw_set and grade == '#' and not rally_lost:
                    stats[current_phase]['kills'] += 1
                current_phase = None
                saw_set = False
            else:
                current_phase = None
                saw_set = False
    return stats


def calculate_point_stats(rallies, rally_outcomes=None):
    """Compute Break Point % and Side-Out % from explicit outcomes or heuristics.

    Rally type is determined by the first recognised action token:
        - First action is 'S' (Serve)  → Break Point rally (team is serving).
        - First action is 'R' (Receive) → Side-Out rally (team is receiving).
    Rallies where neither S nor R appears first are skipped, except touchless
    serve-error gifts (a standalone '@won:se' line), which are counted as a
    Side-Out won with zero touches (we were receiving; C8).

    Win/loss uses _determine_win(), which returns the explicit outcome when one
    is present for the rally and otherwise falls back to the legacy heuristic:
        - Non-final rallies: won if the next rally also starts with 'S'
          (team retained or gained the serve).
        - Final rally: won if its last token has grade '#' (terminal kill).

    Args:
        rallies (list[list[str]]): Output of parse_log()['rallies'].
        rally_outcomes (list[dict] | None): Optional per-rally explicit outcomes
            from parse_log()['rally_outcomes'], aligned to `rallies`.

    Returns:
        dict with two keys:
            'bp' (dict): Break Point stats with 'total' (int) and 'won' (int).
            'so' (dict): Side-Out stats with 'total' (int) and 'won' (int).
    """
    bp = {'total': 0, 'won': 0}
    so = {'total': 0, 'won': 0}

    for r, rally in enumerate(rallies):
        outcome = rally_outcomes[r] if rally_outcomes and r < len(rally_outcomes) else None

        if not rally:
            # Touchless rally: only the opponent serve-error gift is classifiable
            # (we were receiving), counting as a Side-Out won with zero touches.
            if outcome and outcome.get('cause') == 'se':
                so['total'] += 1
                so['won'] += 1
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

        won = _determine_win(r, rallies, rally_outcomes)
        if rally_type == 'serve':
            bp['total'] += 1
            if won:
                bp['won'] += 1
        else:
            so['total'] += 1
            if won:
                so['won'] += 1

    return {'bp': bp, 'so': so}


def calculate_earned_points(rally_outcomes):
    """Summarise earned vs. gifted points from a list of explicit rally outcomes.

    Separates points we earned by our own play (a terminal kill) from points the
    opponent handed us (rival errors), and isolates the "free" serve-error gifts
    where the opponent faulted their own serve. Rallies without an explicit
    outcome (heuristic fallback) contribute nothing to any counter.

    Subset relationship: won_serve_error ⊆ won_rival_error ⊆ won. A '@won'
    without a cause is treated as an earned kill; '@won:re' as a rival-error
    gift; '@won:se' as both a rival-error gift and a serve-error gift.

    Args:
        rally_outcomes (list[dict]): Per-rally outcomes from parse_log(), each
            {'result': 'won'|'lost'|None, 'cause': 're'|'se'|None}.

    Returns:
        dict: {'won', 'won_kill', 'won_rival_error', 'won_serve_error', 'lost'},
            all non-negative ints.
    """
    points = {
        'won': 0,
        'won_kill': 0,
        'won_rival_error': 0,
        'won_serve_error': 0,
        'lost': 0,
    }
    for outcome in rally_outcomes:
        if not outcome:
            continue
        result = outcome.get('result')
        cause = outcome.get('cause')
        if result == 'won':
            points['won'] += 1
            if cause == 'se':
                points['won_rival_error'] += 1
                points['won_serve_error'] += 1
            elif cause == 're':
                points['won_rival_error'] += 1
            else:
                points['won_kill'] += 1
        elif result == 'lost':
            points['lost'] += 1
    return points


def _determine_win(r, rallies, rally_outcomes=None):
    """Determine whether the team won the rally at index `r`.

    When an explicit outcome exists for rally `r` (Phase 2 '@won'/'@lost'
    tokens), it is authoritative. Otherwise the legacy context heuristic runs:
        1. If a subsequent rally exists (index r+1), inspect its first valid token.
           A Serve ('S') as the opening action means the team kept or gained the
           serve, so the current rally is treated as a win.
        2. If rally `r` is the last rally in the list, inspect its last token.
           A '#' grade on the final action is treated as a winning kill.
        3. All other cases are treated as a loss (return False).

    Args:
        r (int): Zero-based index of the rally to evaluate.
        rallies (list[list[str]]): Full ordered list of rally token lists,
            as returned by parse_log().
        rally_outcomes (list[dict] | None): Optional per-rally explicit outcomes
            aligned to `rallies`. When the entry for `r` has a non-None 'result',
            it overrides the heuristic.

    Returns:
        bool: True if the team is inferred to have won rally `r`, False otherwise.
    """
    if rally_outcomes is not None and r < len(rally_outcomes):
        entry = rally_outcomes[r]
        result = entry.get('result') if entry else None
        if result is not None:
            return result == 'won'
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
