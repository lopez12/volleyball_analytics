#!/usr/bin/env python3
"""Volleyball Analytics - Match-log format validator (PR QA gate).

Statically validates every ``teams/**/matches/*.txt`` match log against the
canonical grammar defined in ``analytics.py`` and each dataset's ``team.json``
roster, so malformed rallies are caught before merge instead of being silently
dropped by the parser at build time.

Two severities:
    ERROR - fails the gate (non-zero exit).
    WARN  - reported but does not fail (unless ``--strict`` is given).

Rules:
    R1 (ERROR) play-token grammar        - a candidate play token that is not
                                           ``<num?><SREADB><#+!->``.
    R2 (ERROR) roster membership         - a player number absent from team.json.
    R3 (ERROR) ``@set:`` format          - a malformed ``@set: V-R`` line.
    R4 (WARN)  outcome placement         - outcome token not last / duplicated.
    R5 (WARN)  outcome completeness      - a rally with no outcome token in a
                                           file that otherwise uses them.
    R6 (WARN)  ``@youtube:`` URL         - an invalid YouTube URL (link dropped).
    R7 (WARN)  unrecognized line/token   - text the parser silently ignores.
    R8 (WARN)  ``@date:`` format         - a malformed/impossible match date
                                           (dropped; expected ``YYYY-MM-DD``).    R9 (WARN)  ``@t:`` timestamp format    - a malformed per-rally video
                                           timestamp (expected
                                           ``@t:<start>[-<end>]`` in seconds).
Grammar is imported from ``analytics.py`` (single source of truth); it is never
re-hard-coded here.

Usage:
    python validate_logs.py [--strict] [paths ...]

With no paths, the whole repository is validated. ``--strict`` promotes every
warning to an error. Exit code is 1 when any error is present, else 0.
"""

import argparse
import json
import re
import sys
from pathlib import Path

from analytics import (
    ACTIONS, GRADES, _RE_SET, _RE_YT, _parse_outcome_token, _parse_date_token,
    _parse_timestamp_token,
)

TEAMS_ROOT = Path('teams')

# ---------------------------------------------------------------------------
# Grammar derived from analytics.py constants (never hard-coded independently)
# ---------------------------------------------------------------------------
_ACTIONS = ''.join(ACTIONS)
_GRADES = re.escape(''.join(GRADES))
# Strict play token: optional player number + action letter + grade symbol.
PLAY_RE = re.compile(rf'^(\d*)([{_ACTIONS}])([{_GRADES}])$')
# A "team-token shape" (single letter + grade) is enough to look like an
# intended play token even when the letter/grade is wrong (e.g. 'X-', 's#').
TEAM_SHAPE_RE = re.compile(rf'^[A-Za-z][{_GRADES}]$')

# Severity labels.
ERROR = 'ERROR'
WARN = 'WARN'


def _is_candidate(token):
    """Return True if the token looks like an intended play token.

    A candidate is any token that starts with a digit (e.g. '7A#', '12', '253+')
    or has a single-letter + grade shape (e.g. 'S#', 'X-'). Free text such as
    '(Sin', 'SEGUNDO' or '---' is not a candidate and is treated as an ignored
    line (R7) rather than a malformed play token (R1).
    """
    return bool(token[:1].isdigit() or TEAM_SHAPE_RE.match(token))


def _load_roster(team_json_path):
    """Load the roster player-number set from a team.json.

    Returns:
        tuple[set[str] | None, str | None]: (roster_numbers, error_message).
            roster_numbers is None when the file is unreadable or has no valid
            'roster' object, in which case error_message explains why.
    """
    try:
        cfg = json.loads(team_json_path.read_text(encoding='utf-8'))
    except (OSError, ValueError) as exc:
        return None, f'unreadable team.json: {exc}'
    roster = cfg.get('roster')
    if not isinstance(roster, dict):
        return None, "team.json has no valid 'roster' object"
    return set(roster.keys()), None


def _rel(path):
    """Return a repo-relative, forward-slash path string for reporting."""
    try:
        return path.resolve().relative_to(Path.cwd().resolve()).as_posix()
    except ValueError:
        return path.as_posix()


def validate_file(txt_path, roster):
    """Validate a single match-log file and return a list of issues.

    Args:
        txt_path (Path): Path to a ``matches/*.txt`` log.
        roster (set[str]): Valid player-number keys from the sibling team.json.

    Returns:
        list[tuple]: Issues as ``(line_no, severity, rule_id, message, token)``.
    """
    issues = []
    text = txt_path.read_text(encoding='utf-8')
    lines = text.splitlines()

    # First pass: does this file use the outcome grammar at all? (D4/R5)
    file_uses_outcomes = any(
        _parse_outcome_token(tok)
        for line in lines
        for tok in line.strip().split()
    )

    for line_no, raw in enumerate(lines, start=1):
        trimmed = raw.strip()
        if not trimmed or trimmed == '---':
            continue

        low = trimmed.lower()
        if low.startswith('@youtube:'):
            url = trimmed[9:].strip()
            if not _RE_YT.match(url):
                issues.append((line_no, WARN, 'R6',
                               'invalid YouTube URL (link ignored by parser)', url))
            continue
        if low.startswith('@set:'):
            if not _RE_SET.match(trimmed):
                issues.append((line_no, ERROR, 'R3',
                               'malformed @set: line (expected "@set: V-R")', trimmed))
            continue
        if low.startswith('@date:'):
            if _parse_date_token(trimmed) is None:
                issues.append((line_no, WARN, 'R8',
                               'malformed @date: line (expected "@date: YYYY-MM-DD")',
                               trimmed))
            continue

        tokens = trimmed.split()
        outcome_positions = []
        valid_plays = []       # (token, number) for grammar-valid play tokens
        has_bad_candidate = False
        stray_tokens = []      # non-candidate free text on this line
        ts_positions = []      # positions of '@t:' timestamp metadata tokens

        for idx, token in enumerate(tokens):
            if token[:3].lower() == '@t:':
                # Per-rally video timestamp metadata (Phase 4). Consumed by the
                # parser as timing, never as a play token; WARN when malformed.
                if _parse_timestamp_token(token) is None:
                    issues.append((line_no, WARN, 'R9',
                                   'malformed @t: timestamp token '
                                   '(expected "@t:<start>[-<end>]" in seconds)', token))
                else:
                    ts_positions.append(idx)
                continue
            if _parse_outcome_token(token) is not None:
                outcome_positions.append(idx)
                continue
            if _is_candidate(token):
                m = PLAY_RE.match(token)
                if m:
                    valid_plays.append((token, m.group(1)))
                else:
                    has_bad_candidate = True
                    issues.append((line_no, ERROR, 'R1',
                                   'malformed play token '
                                   '(expected <num?><SREADB><#+!->)', token))
            else:
                stray_tokens.append(token)

        is_rally = bool(outcome_positions or valid_plays or has_bad_candidate or ts_positions)

        if not is_rally:
            # Whole line yields nothing the parser records - it is silently
            # ignored (e.g. '(Sin registro)', '--- SEGUNDO SET ---').
            issues.append((line_no, WARN, 'R7',
                           'line ignored by parser (no valid tokens)', trimmed))
            continue

        # R2 - roster membership for player-tagged tokens.
        for token, number in valid_plays:
            if number and number not in roster:
                issues.append((line_no, ERROR, 'R2',
                               f'player #{number} is not in the team.json roster',
                               token))

        # R7 - stray free-text tokens on an otherwise valid rally line.
        for token in stray_tokens:
            issues.append((line_no, WARN, 'R7',
                           'token ignored by parser', token))

        # R4 - outcome token placement / duplication.
        if outcome_positions:
            if len(outcome_positions) > 1:
                issues.append((line_no, WARN, 'R4',
                               'multiple outcome tokens (only the first is used)',
                               tokens[outcome_positions[1]]))
            # A trailing '@t:' timestamp is legitimately last, so the outcome
            # only needs to be the last non-timestamp token.
            ts_set = set(ts_positions)
            last_idx = len(tokens) - 1
            while last_idx >= 0 and last_idx in ts_set:
                last_idx -= 1
            if outcome_positions[-1] != last_idx:
                issues.append((line_no, WARN, 'R4',
                               'outcome token should be the last token on the line',
                               tokens[outcome_positions[0]]))

        # R5 - outcome completeness (only in files that use the grammar).
        elif file_uses_outcomes:
            issues.append((line_no, WARN, 'R5',
                           'rally has no @won/@lost outcome token '
                           '(file uses outcome grammar)', trimmed))

    return issues


def _iter_match_files(paths):
    """Yield (txt_path, team_json_path) pairs to validate.

    Args:
        paths (list[str]): Explicit files/dirs to validate. Empty -> whole repo.

    Yields:
        tuple[Path, Path | None]: A match .txt file and its dataset team.json
            (None when no sibling team.json can be located).
    """
    if paths:
        targets = []
        for p in paths:
            path = Path(p)
            if path.is_dir():
                targets.extend(sorted(path.rglob('*.txt')))
            elif path.suffix == '.txt':
                targets.append(path)
        for txt in targets:
            yield txt, _find_team_json(txt)
        return

    # Whole-repo mode: mirror generate.py's dataset discovery.
    if not TEAMS_ROOT.is_dir():
        return
    for team_dir in sorted(p for p in TEAMS_ROOT.iterdir() if p.is_dir()):
        for ds_dir in sorted(p for p in team_dir.iterdir() if p.is_dir()):
            team_json = ds_dir / 'team.json'
            if not team_json.exists():
                continue
            matches_dir = ds_dir / 'matches'
            if not matches_dir.is_dir():
                continue
            for txt in sorted(matches_dir.glob('*.txt')):
                yield txt, team_json


def _find_team_json(txt_path):
    """Walk up from a match .txt to find the dataset's team.json, or None."""
    for parent in txt_path.resolve().parents:
        candidate = parent / 'team.json'
        if candidate.exists():
            return candidate
    return None


def main(argv=None):
    """CLI entry point. Returns the process exit code (0 ok, 1 on errors)."""
    parser = argparse.ArgumentParser(
        description='Validate volleyball match-log .txt files.')
    parser.add_argument('paths', nargs='*',
                        help='files or directories to validate '
                             '(default: whole repository)')
    parser.add_argument('--strict', action='store_true',
                        help='promote warnings to errors')
    args = parser.parse_args(argv)

    roster_cache = {}
    files_report = {}       # rel_path -> list of issues
    total_errors = 0
    total_warnings = 0
    files_checked = 0

    for txt_path, team_json in _iter_match_files(args.paths):
        files_checked += 1
        rel = _rel(txt_path)
        issues = []

        if team_json is None:
            issues.append((0, ERROR, 'R2',
                           'no team.json found for this match file', ''))
            roster = set()
        else:
            key = str(team_json.resolve())
            if key not in roster_cache:
                roster_cache[key] = _load_roster(team_json)
            roster, roster_err = roster_cache[key]
            if roster is None:
                issues.append((0, ERROR, 'R2',
                               f'{roster_err} ({_rel(team_json)})', ''))
                roster = set()

        issues.extend(validate_file(txt_path, roster))
        if issues:
            files_report[rel] = issues

    # Emit the grouped report.
    for rel in sorted(files_report):
        print(rel)
        for line_no, severity, rule, message, token in sorted(files_report[rel]):
            effective = ERROR if (args.strict and severity == WARN) else severity
            if effective == ERROR:
                total_errors += 1
            else:
                total_warnings += 1
            loc = f'{rel}:{line_no}'
            token_note = f" (token: '{token}')" if token else ''
            print(f'  {loc}: [{effective}] {rule} {message}{token_note}')
        print()

    print(f'{total_errors} error(s), {total_warnings} warning(s) '
          f'across {files_checked} file(s) checked.')
    return 1 if total_errors else 0


if __name__ == '__main__':
    sys.exit(main())
