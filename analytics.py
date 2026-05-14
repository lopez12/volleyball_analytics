"""Volleyball Analytics - Parsing and calculation engine.

Contains all constants, data structures, parsing logic, and statistical
calculations. No knowledge of HTML or SQLite.
"""

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

_RE_PLAYER = re.compile(r'^(\d+)([SREADB])([#+!\-])$')
_RE_TEAM = re.compile(r'^([SREADB])([#+!\-])$')
_RE_ANY = re.compile(r'^(\d*)([SREADB])([#+!\-])$')
_RE_PHASE = re.compile(r'^(\d+)([SREADB])([#+!\-])$|^([SREADB])([#+!\-])$')
_RE_YT = re.compile(r'^https?://(www\.)?(youtube\.com|youtu\.be)/')
_RE_SET = re.compile(r'^@set:\s*(\d+)-(\d+)$', re.IGNORECASE)

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
        - Set score:     '@set: V-R'                 e.g. '@set: 25-18'. Vodkas score
                                                     first, rival score second.
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
                Rallies with no valid tokens are omitted.
            'youtube_urls' (list[str]): Validated YouTube URLs found in
                '@youtube:' lines, in the order they appear in the file.
            'set_scores' (list[tuple[int, int]]): List of (vodkas, rival) score
                tuples, one per '@set:' line, in file order. Empty list if none.
    """
    lines = log_string.strip().splitlines()
    rallies = []
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

    return {'players': players, 'team': team, 'rallies': rallies, 'youtube_urls': youtube_urls, 'set_scores': set_scores}

# ---------------------------------------------------------------------------
# Calculations
# ---------------------------------------------------------------------------


def calculate_rating(data):
    """Compute the overall performance rating for a player or team on a 1–10 scale.

    Formula:
        raw    = 6.0 + (score_sum / total) * 4.0
        rating = clamp(raw, 1.0, 10.0)

    The baseline of 6.0 represents neutral performance. The multiplier of 4.0
    scales the normalised weighted average so that a perfect score (all '#')
    produces 10.0, while consistent errors ('-') approach 1.0.

    Args:
        data (dict): A statistics dictionary with at minimum:
            'total' (int): Total number of recorded actions.
            'score_sum' (float): Cumulative weighted score from _record().

    Returns:
        float: Rounded performance rating in the inclusive range [1.0, 10.0].
            Returns 0.0 if 'total' is 0 (no recorded actions).
    """
    if data['total'] == 0:
        return 0.0
    raw = 6.0 + (data['score_sum'] / data['total']) * 4.0
    return round(max(1.0, min(10.0, raw)), 1)


def calculate_phase_stats(rallies):
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

    Args:
        rallies (list[list[str]]): Output of parse_log()['rallies']. Each
            element is a list of token strings representing one rally.

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
    """Compute Break Point % and Side-Out % by inferring which team won each rally.

    Rally type is determined by the first recognised action token:
        - First action is 'S' (Serve)  → Break Point rally (team is serving).
        - First action is 'R' (Receive) → Side-Out rally (team is receiving).
    Rallies where neither S nor R appears first are skipped.

    Win/loss is determined by _determine_win():
        - Non-final rallies: won if the next rally also starts with 'S'
          (team retained or gained the serve).
        - Final rally: won if its last token has grade '#' (terminal kill).

    Args:
        rallies (list[list[str]]): Output of parse_log()['rallies'].

    Returns:
        dict with two keys:
            'bp' (dict): Break Point stats with 'total' (int) and 'won' (int).
            'so' (dict): Side-Out stats with 'total' (int) and 'won' (int).
    """
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
    """Determine whether the team won the rally at index `r` using context heuristics.

    Heuristic logic (in order):
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

    Returns:
        bool: True if the team is inferred to have won rally `r`, False otherwise.
    """
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
