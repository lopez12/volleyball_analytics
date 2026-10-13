---
description: 'Authoring and grading rules for volleyball match logs.'
applyTo: 'teams/**/*.txt'
---

# Match-Log Authoring Rules

These rules apply when editing any match log under `teams/<team>/<tournament>/matches/*.txt`.
The grammar is defined once in `analytics.py` and enforced by `validate_logs.py`; this file is the human-facing summary. After any edit, run `python validate_logs.py <file>` and fix every **ERROR**.

## Lines and tokens

- One **line = one rally**. Tokens on a line are space-separated and chronological.
- **Play token:** `<num?><action><grade>`, e.g. `7A#`. A team-level action omits the number (`S#`).
- **Actions:** `A` Ataque, `B` Bloqueo, `S` Saque, `R` Recepción, `D` Defensa, `E` Acomodo.
- **Grades:** `#` perfecto, `+` positivo, `!` regular, `-` error.

## Special lines

- `---` on its own line separates sets (resets rally context).
- `@set: V-R` final set score, team first (e.g. `@set: 25-18`).
- `@youtube: https://youtu.be/...` links a video to the current set.
- `@date: YYYY-MM-DD` optional match play date.
- `@t:<start>[-<end>]` optional per-rally video timestamp in seconds (e.g. `@t:3-9`), powering the Match Logger's replay.

## Outcome tokens (optional, but ground truth when present)

Place at most one at the **end** of a rally line:

- `@won` — we scored by our own play (kill / ace / stuff block).
- `@lost` — the opponent scored.
- `@won:re` — we scored, but on a **rival error** (gifted point; credited to no player).
- `@won:se` — opponent **faulted their serve**; a touchless free point (a line with only `@won:se` is valid).

When a rally has no outcome token, the engine falls back to its win heuristic, so older logs keep working. Do not make these tokens mandatory.

## Grade the touch, not the scoreboard

Ask "how well was this ball played?", never "did we win the point?".

- On a **terminal** action (`A`, `S`, `B`): `#` means it *won the point by its own quality* (kill / ace / stuff block); `-` means it *lost* the point (attack error / service fault / blocked back).
- On a **continuation** action (`R`, `E`, `D`): grades are pure execution quality and are never terminal.
- A point won because the **opponent erred** is nobody's `#`. Grade your last touch honestly (`!` / `+`) and mark the rally `@won:re` (or `@won:se` for a serve fault).

This keeps `#` meaning "perfect execution" and never "we happened to win," so attack efficiency and the rating stay honest.

## Roster and validation

- Every player number used in a log must exist in that dataset's `team.json` roster, or `validate_logs.py` raises an **ERROR** (rule R2). Add the player to the roster instead of working around it.
- `validate_logs.py` ERRORs fail the PR gate; WARNs do not (use `--strict` to also fail on warnings). WARNs flag content the parser would silently drop - treat them as real.

```
2R# 25E# 7A#  @won            # real kill, credited to #7
2R# 25E! 7A!  @won:re         # honest execution; point from a rival error; no kill credit
@won:se                       # opponent missed their serve - free point, no touch
8A-           @lost  @t:14-21 # our attack error; rally spans 0:14-0:21 of the set video
20R+ 25E+ 7A+                 # no outcome token - engine uses the win heuristic
```
