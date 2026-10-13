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
- **No dependencies, no build step.** Python stays standard-library only; the logger stays framework-less; output stays static.
- **Escape HTML.** Data-derived strings that reach HTML go through `html.escape` (Python) or the logger's `esc()` helper.
- **Backward-compatible logs.** Outcome tokens (`@won` / `@lost` / `@won:re` / `@won:se`) and `@t:` video timestamps are optional, with a heuristic fallback. Old matches must keep building unchanged.
- **One `styles.css`.** It is copied verbatim to every output location and uses `:root` custom properties with `data-theme` light/dark tokens. Use the tokens - no hardcoded colors.

## Match-log grammar (summary)

One line per rally; space-separated, chronological tokens.

- **Play token** `<num?><action><grade>` (a team action omits the number): actions `A` `B` `S` `R` `D` `E`; grades `#` `+` `!` `-`.
- **Special lines:** `---` set separator, `@set: V-R`, `@youtube: <url>`, `@date: YYYY-MM-DD`, `@t:<start>[-<end>]`.
- **Outcome tokens** (optional, last on a line): `@won`, `@lost`, `@won:re`, `@won:se`.
- **Grade the touch, not the scoreboard:** `#` on a terminal action means it won the point by its own quality; a point from an opponent error is nobody's `#` (grade honestly, mark `@won:re`).

## Rating

`analytics.calculate_rating`: sum each touch's `WEIGHTS[grade] * ACTION_WEIGHTS[action]`, then `raw = 6.0 + (weighted / total) * 4.0`, clamped to `[1.0, 10.0]`. Dividing by the raw touch count (not the weighted count) makes low-leverage actions like setting contribute less. `ACTION_WEIGHTS['E'] = 0.65` is the primary tuning dial.

## Workflow

- **Build / preview:** `python generate.py` (also opens the root selector). This is the CI smoke test.
- **Validate match data:** `python validate_logs.py [paths]` - must report no **ERRORs** (`--strict` also fails on WARNs). A player number missing from `team.json` is an ERROR.
- **CI:** `.github/workflows/qa.yml` validates the logs changed in a PR and runs a smoke build; `.github/workflows/build.yml` regenerates `docs/` and deploys to GitHub Pages on push to `main`.

## Agents and the brief workflow

Work flows through three agents in `.github/agents/`:

- **architect** - plans a change and writes `ARCHITECT-BRIEF.md` (the single source of truth). Does not write code.
- **developer** - implements the brief.
- **reviewer** - checks the diff against the brief and runs the QA gate. Does not write feature code.

The current brief lives at `ARCHITECT-BRIEF.md`; completed briefs are archived under `briefs/` as the project's decision history. The `/new-brief` prompt scaffolds a brief. When planning, read the current brief and the `briefs/` archive before contradicting past decisions.
