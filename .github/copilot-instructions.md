# Volleyball Analytics - Copilot Instructions

Repo-wide context for every Copilot session in this workspace. For deeper detail read `README.md`; for match-log authoring see `.github/instructions/match-logs.instructions.md` (auto-applied to `teams/**/*.txt`).

## What this project is

A dependency-free **Python static-site generator** that turns volleyball match logs into HTML dashboards published to GitHub Pages, plus a framework-less **Match Logger** web app for tagging matches.

- `python generate.py` discovers every `(team, tournament)` dataset under `teams/`, parses its match logs, stores results in a per-dataset SQLite DB under `data/`, and renders static HTML under `docs/`. A root selector page links to every dataset.
- **Python 3.12, standard library only.** No third-party packages, no build step, no server. The logger is vanilla HTML/CSS/JS. Output is static.
- **UI text is Spanish; code and comments are English.**

## Architecture (keep the layers separate)

| Module | Owns | Must NOT |
|--------|------|----------|
| `analytics.py` | Constants, the match-log grammar, parsing, all statistics (rating, phase, point, earned points). | know about HTML or SQLite |
| `db.py` | SQLite schema, upserts, query helpers. | emit HTML |
| `renderer.py` | HTML cards + the seven page renderers; shared inline snippets (theme, collapsibles). | do file I/O or SQLite |
| `generate.py` | Orchestration + file I/O: discover datasets, build DBs, render `docs/`, copy `logger/`. | hold parsing or rendering logic |
| `validate_logs.py` | Static match-log validation = the PR QA gate. Imports its grammar from `analytics.py`. | re-define the grammar |
| `logger/` | Client-side Match Logger (`app.js` IIFE, `logger.css`, `index.html`, `datasets.js`). | add a framework or build step |

## Invariants

- **Grammar is single-source.** The match-log grammar lives in `analytics.py` and is enforced by `validate_logs.py`. Add any new token or rule in both - never hard-code it twice.
- **Source vs. generated.** Committed input: `teams/**` (rosters `team.json` + `matches/*.txt`), `styles.css`, `logger/`. Generated and never hand-edited: everything under `data/` and `docs/` - including `docs/logger/`, which `generate.py` copies from `logger/`. Edit the source, then rebuild.
- **No dependencies, no build step.** Python stays standard-library only; the logger stays framework-less; output stays static. Dev tooling (ruff, pre-commit) is allowed but is never imported at runtime.
- **Escape HTML.** Data-derived strings that reach HTML go through `html.escape` (Python) or the logger's `esc()` helper.
- **Backward-compatible logs.** Outcome tokens (`@won` / `@lost` / `@won:re` / `@won:se`) and `@t:` video timestamps are optional, with a heuristic fallback. Old matches must keep building unchanged.
- **One `styles.css`.** It is copied verbatim to every output location and uses `:root` custom properties with `data-theme` light/dark tokens. Use the tokens - no hardcoded colors.

## Match-log grammar (summary)

One line per rally; space-separated, chronological tokens.

- **Play token** `<num?><action><grade>` (a team action omits the number): actions `A` `B` `S` `R` `D` `E`; grades `#` `+` `!` `-`.
- **Special lines:** `---` set separator, `@set: V-R`, optional `@start: V-R` (score at recording start, before the set's first rally; replay scoreboard only), optional `@role: <num>=<POS>[, ...]` (per-set player-rating role override for its `---` block, before the set's first rally), `@youtube: <url>`, `@date: YYYY-MM-DD`, `@t:<start>[-<end>]`.
- **Outcome tokens** (optional, last on a line): `@won`, `@lost`, `@won:re`, `@won:se`.
- **Grade the touch, not the scoreboard:** `#` on a terminal action means it won the point by its own quality; a point from an opponent error is nobody's `#` (grade honestly, mark `@won:re`).

## Rating

- **Shared grade values:** team ratings, player ratings and per-action "Notas" all use `PLAYER_GRADE_VALUES[action][grade]`. `WEIGHTS` feeds only the legacy `score_sum` total, not any rating.
- **Team rating** (`analytics.calculate_rating`): `raw = (Σ_action Σ_grade grade_count[grade][action] * PLAYER_GRADE_VALUES[action][grade]) / total`, then `round(clamp(RATING_CENTER + (raw - TEAM_RATING_RAW_MEAN) * TEAM_RATING_SCALE, 1.0, 10.0), 1)`. Reuses `RATING_CENTER = 7.0`; `TEAM_RATING_RAW_MEAN = 0.114`, `TEAM_RATING_SCALE = 17.6`. No role weights or shrinkage; no touches returns 0.0.
- **Per-action Nota** (`analytics.calculate_action_stats`): each action's plain-touch average `avg` over the same grade values maps to `round(clamp(RATING_CENTER + (avg - ACTION_NOTA_CENTER[action]) * ACTION_NOTA_SCALE[action], 1.0, 10.0), 1)`, without shrinkage. 7.0 means average quality for that action in the calibration data, not a common absolute scale; no attempts keeps `rating = None`.
  - `ACTION_NOTA_CENTER = {'S': 0.206, 'R': 0.023, 'E': 0.071, 'A': 0.1, 'D': 0.069, 'B': 0.155}`.
  - `ACTION_NOTA_SCALE = {'S': 4.8, 'R': 5.3, 'E': 7.3, 'A': 4.3, 'D': 5.8, 'B': 4.0}`.
- **Player rating** (`analytics.calculate_player_rating(stats, position)`): per-action grade values (`PLAYER_GRADE_VALUES`) with shrinkage (`RATING_SHRINK`), mixed by role weights (`ROLE_ACTION_WEIGHTS`). The role is resolved per `---` set block from `@role:` or inferred from the set share in that block (`SETTER_SHARE_LOW`/`HIGH`, roster position as base), then touch-weighted across the match. Setters add an assist term (`ASSIST_WEIGHT`). Fixed scale `RATING_CENTER + (raw - RATING_RAW_MEAN) * RATING_SCALE`, clamped to `[1.0, 10.0]`. The constants are frozen (#56); don't recompute them per dataset.

The team and per-action scale constants were fitted on 2026-11-11 data (#57) and are frozen; never recompute them per dataset.

## Workflow

- **Build / preview:** `python generate.py` (also opens the root selector unless `CI` is set). This is the CI smoke test.
- **Validate match data:** `python validate_logs.py [paths]` - must report no **ERRORs** (`--strict` also fails on WARNs). A player number missing from `team.json` is an ERROR.
- **Lint / format:** `ruff check .` and `ruff format --check .` must pass (config in `ruff.toml`; `ruff check --fix .` / `ruff format .` to fix). Optional: `pre-commit install`.
- **CI:** `.github/workflows/qa.yml` runs a `lint` job (ruff) and a `qa` job that validates the logs (or rosters) changed in a PR - or every log when `analytics.py` / `validate_logs.py` changed - and runs a smoke build; `.github/workflows/build.yml` regenerates `docs/` and deploys to GitHub Pages on push to `main`.

## Agents and the brief workflow

Work flows through three agents in `.github/agents/`:

- **architect** - plans a change and writes `ARCHITECT-BRIEF.md` (the single source of truth). Does not write code.
- **developer** - implements the brief.
- **reviewer** - checks the diff against the brief and runs the QA gate. Does not write feature code.

The current brief lives at `ARCHITECT-BRIEF.md`; completed briefs are archived under `briefs/` as the project's decision history. Both are local, git-ignored planning documents - never commit them. The `/new-brief` prompt scaffolds a brief. When planning, read the current brief and the `briefs/` archive before contradicting past decisions.
