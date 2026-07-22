"""Volleyball Analytics - Parsing and calculation engine.

Contains all constants, data structures, parsing logic, and statistical
calculations. No knowledge of HTML or SQLite.
"""

import json
import re

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

# Per-action leverage weights for the rating. Terminal, point-scoring actions
# matter most; setting is a low-risk continuation and is intentionally
# discounted. ACTION_WEIGHTS['E'] is the primary tuning dial: lower it to
# further reduce setter inflation, raise it to reward playmaking.
ACTION_WEIGHTS = {
    'A': 1.3,   # Ataque   - terminal, scores points
    'B': 1.2,   # Bloqueo  - terminal, scores points
    'S': 1.1,   # Saque    - can ace or break serve-receive
    'R': 1.0,   # Recepción - baseline
    'D': 1.0,   # Defensa  - baseline
    'E': 0.65,  # Acomodo  - low-risk continuation (primary dial)
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
            }
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
    """
    with open(path, encoding='utf-8') as f:
        cfg = json.load(f)
    roster = cfg.get('roster', {})
    positions = {num: info.get('position', 'U') for num, info in roster.items()}
    names = {num: info['name'] for num, info in roster.items() if info.get('name')}
    return {
        'team': cfg.get('team', ''),
        'tournament': cfg.get('tournament', ''),
        'type': cfg.get('type', 'tournament'),
        'positions': positions,
        'names': names,
    }

_RE_PLAYER = re.compile(r'^(\d+)([SREADB])([#+!\-])$')
_RE_TEAM = re.compile(r'^([SREADB])([#+!\-])$')
_RE_ANY = re.compile(r'^(\d*)([SREADB])([#+!\-])$')
_RE_PHASE = re.compile(r'^(\d+)([SREADB])([#+!\-])$|^([SREADB])([#+!\-])$')
_RE_YT = re.compile(r'^https?://(www\.)?(youtube\.com|youtu\.be)/')
_RE_SET = re.compile(r'^@set:\s*(\d+)-(\d+)$', re.IGNORECASE)
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

# ---------------------------------------------------------------------------
# Data helpers
# ---------------------------------------------------------------------------


def _new_stats():
    """Create and return a fresh, zeroed-out statistics dictionary for a player or team.

    The returned dictionary has the following structure:
        - 'total' (int): Total number of recorded actions across all types and grades.
        - 'score_sum' (float): Cumulative weighted score. Each action contributes
          WEIGHTS[grade] to this sum. Used by calculate_rating().
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

    Returns:
        dict: A zeroed statistics dictionary ready to accumulate recorded actions.
    """
    return {
        'total': 0,
        'score_sum': 0.0,
        'grades': {g: 0 for g in GRADES},
        'actions': {a: {'tot': 0, 'good': 0} for a in ACTIONS},
        'grade_count': {g: {a: 0 for a in ACTIONS} for g in GRADES},
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

# ---------------------------------------------------------------------------
# Parsing
# ---------------------------------------------------------------------------


def parse_log(log_string):
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
        - Rally outcome: '@won' / '@lost' / '@won:re' / '@won:se'  (inline,
                                                     trailing, case-insensitive).
                                                     Consumed as the rally's
                                                     outcome, not a played token.
                                                     A line consisting solely of
                                                     an outcome token is a valid
                                                     "touchless" rally.
    Tokens that match neither the player nor team pattern are silently ignored.
    Player tokens are recorded in both the individual player's stats and the team stats.
    Team-only tokens are recorded only in team stats.

    Args:
        log_string (str): Full text content of a .txt match log file.

    Returns:
        dict with the following keys:
            'players' (dict): Maps player number strings (e.g. '7') to their
                individual statistics dictionaries (see _new_stats()).
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
            'points' (dict): Team-level earned/gifted point summary derived from
                the explicit outcomes: 'won', 'won_kill', 'won_rival_error',
                'won_serve_error', 'lost'.
            'youtube_urls' (list[str]): Validated YouTube URLs found in
                '@youtube:' lines, in the order they appear in the file.
            'set_scores' (list[tuple[int, int]]): List of (team, rival) score
                tuples, one per '@set:' line, in file order. Empty list if none.
    """
    lines = log_string.strip().splitlines()
    rallies = []
    rally_outcomes = []
    players = {}
    youtube_urls = []
    set_scores = []
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
        m_set = _RE_SET.match(trimmed)
        if m_set:
            set_scores.append((int(m_set.group(1)), int(m_set.group(2))))
            continue

        tokens = trimmed.split()
        rally_tokens = []
        outcome = {'result': None, 'cause': None}
        outcome_seen = False

        for token in tokens:
            parsed_outcome = _parse_outcome_token(token)
            if parsed_outcome is not None:
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
                rally_tokens.append(token)
            else:
                m = _RE_TEAM.match(token)
                if m:
                    action, grade = m.group(1), m.group(2)
                    _record(team, action, grade)
                    rally_tokens.append(token)

        # Keep the rally when it has playable tokens OR carried an explicit
        # outcome (a touchless rally, e.g. an opponent serve fault '@won:se').
        if rally_tokens or outcome_seen:
            rallies.append(rally_tokens)
            rally_outcomes.append(outcome)

    points = calculate_earned_points(rally_outcomes)
    return {
        'players': players,
        'team': team,
        'rallies': rallies,
        'rally_outcomes': rally_outcomes,
        'points': points,
        'youtube_urls': youtube_urls,
        'set_scores': set_scores,
    }

# ---------------------------------------------------------------------------
# Calculations
# ---------------------------------------------------------------------------


def calculate_rating(data):
    """Compute the overall performance rating for a player or team on a 1–10 scale.

    The rating is action-weighted ("leverage-scaled"): each recorded touch
    contributes its grade weight (WEIGHTS) multiplied by its action's leverage
    weight (ACTION_WEIGHTS), and the sum is divided by the raw touch count.

        weighted = Σ_action Σ_grade  grade_count[grade][action]
                                      * WEIGHTS[grade] * ACTION_WEIGHTS[action]
        raw      = 6.0 + (weighted / total) * 4.0
        rating   = clamp(raw, 1.0, 10.0)

    Dividing by the raw count (not by Σ count*ACTION_WEIGHTS) is deliberate: it
    makes low-leverage actions such as setting contribute *less* to the rating,
    instead of merely re-weighting an average (which would leave a pure-setting
    profile unchanged). Elite terminal performances may reach the 10.0 clamp.

    Args:
        data (dict): A statistics dictionary with at minimum:
            'total' (int): Total number of recorded actions.
            'grade_count' (dict): Cross-tab of grade -> action -> count, as
                produced by _new_stats()/_record() or _row_to_stats().

    Returns:
        float: Rounded performance rating in the inclusive range [1.0, 10.0].
            Returns 0.0 if 'total' is 0 (no recorded actions).
    """
    total = data['total']
    if total == 0:
        return 0.0
    grade_count = data['grade_count']
    weighted = 0.0
    for grade in GRADES:
        for action in ACTIONS:
            weighted += grade_count[grade][action] * WEIGHTS[grade] * ACTION_WEIGHTS[action]
    raw = 6.0 + (weighted / total) * 4.0
    return round(max(1.0, min(10.0, raw)), 1)


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
        'so_bad':  {'attempts': 0, 'kills': 0},
        'trans':   {'attempts': 0, 'kills': 0},
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
