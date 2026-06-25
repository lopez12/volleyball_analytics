# Volleyball Analytics

A volleyball analytics dashboard that reads match log files and generates static HTML reports, deployed automatically to GitHub Pages via Python + GitHub Actions.

## Features

- 📊 Parse volleyball match logs from `.txt` files
- 📈 Player and team statistics with ratings (1–10 scale)
- 🎯 Phase analysis: Side-Out and Transition efficiency
- 🏆 Break Point and Side-Out point scoring stats
- 🌐 Auto-deployed to GitHub Pages on every push
- 🐍 Pure Python — no JavaScript knowledge required to maintain

## Tech Stack

- **Python 3.12** (standard library only — no dependencies)
- **HTML/CSS** for report styling
- **GitHub Actions** for automated builds and deployment

## Quick Start (local)

```bash
python generate.py
```

This discovers every dataset under `teams/`, writes static HTML to `docs/`, and opens the root selector page in your browser.

## Data Layout

The project supports **multiple teams**, each playing **multiple tournaments** (and friendly matches). Every `(team, tournament)` pair is an independent **dataset** with its own roster, database, and dashboard.

```
teams/
└── <team_slug>/
    └── <tournament_slug>/
        ├── team.json                 # roster + team/tournament metadata
        └── matches/
            ├── 01_<opponent>.txt
            ├── 02_<opponent>.txt
            └── ...
```

- `team_slug` and `tournament_slug` are lowercase, hyphen-separated folder names (e.g. `vodkas`, `atlas-chapalita-cup-2026`).
- Tournament slugs carry a **year suffix** (e.g. `apertura-2026`) so the same competition in different years stays separate.
- Friendly matches go in a dataset whose `type` is `"friendly"` (slug `amistosos`, no year).

The generated output mirrors this layout and is **not committed**:

```
data/<team_slug>/<tournament_slug>/volleyball.db   # SQLite (generated)
data/<team_slug>/<tournament_slug>/*.csv           # CSV export (generated)
docs/<team_slug>/<tournament_slug>/...             # dataset dashboard (generated)
docs/index.html                                    # root team/tournament selector
```

### `team.json` format

```json
{
  "team": "Vodkas",
  "tournament": "Atlas Chapalita Cup",
  "type": "tournament",
  "roster": {
    "7":  { "name": "Gio", "position": "OH" },
    "8":  { "name": "DaniRdz", "position": "MB" }
  }
}
```

| Field | Meaning |
|-------|---------|
| `team` | Display team name (shown on every page). |
| `tournament` | Display competition name (use `"Amistosos"` for friendlies). |
| `type` | `"tournament"` or `"friendly"`. |
| `roster` | Maps player number → `{ "name", "position" }`. Positions: `S`, `OH`, `OPP`, `MB`, `L`. |

Players without a name fall back to `#<number>` in the reports.

## Adding a New Team

1. Create `teams/<team_slug>/<tournament_slug>/team.json` with the roster and metadata.
2. Add match logs under `teams/<team_slug>/<tournament_slug>/matches/`.
3. Run `python generate.py` to preview, then commit and push.

## Adding a New Tournament (new season / competition)

1. Create a new dataset folder for the team: `teams/<team_slug>/<new-tournament-slug>/`.
2. Add its `team.json` (roster may differ from other tournaments) and a `matches/` folder.
3. Run `python generate.py`. The new tournament appears under the team on the root selector.

## Recording a Friendly Match

1. Use (or create) the team's `teams/<team_slug>/amistosos/` dataset with `"type": "friendly"` and `"tournament": "Amistosos"` in `team.json`.
2. Drop the match log in its `matches/` folder.
3. Run `python generate.py`. Friendlies are grouped separately under the team on the root selector and labelled **Amistosos**.

## Adding a New Match

1. Create a `.txt` file in the dataset's `matches/` folder using the naming convention below.
2. Paste the match log (see format below).
3. Run `python generate.py` to preview locally.
4. Commit and push — GitHub Actions rebuilds and publishes the site automatically.

### File naming convention

Match files live inside a dataset's `matches/` folder and are named `NN_<opponent>.txt`:

```
teams/vodkas/atlas-chapalita-cup-2026/matches/
├── 01_atlas.txt
├── 02_arcano.txt
├── 03_teletubbies.txt
└── ...
```

The two-digit prefix controls the order in which matches appear. The prefix is stripped and the team name is prepended automatically, so `01_atlas.txt` for team **Vodkas** becomes **"Vodkas vs Atlas"** in the report.

## Match Log Format

Each line is one rally. Tokens within a line are space-separated.

### Token format

```
[PlayerNumber][Action][Grade]   e.g.  7S#
[Action][Grade]                 e.g.  S#   (team action, no player number)
```

### Actions

| Code | Name | Leverage weight |
|------|------|-----------------|
| `A`  | Ataque (Attack) | 1.3 |
| `B`  | Bloqueo (Block) | 1.2 |
| `S`  | Saque (Serve) | 1.1 |
| `R`  | Recepción de Saque (Reception) | 1.0 |
| `D`  | Defensa (Defense) | 1.0 |
| `E`  | Acomodo (Set) | 0.65 |

The **leverage weight** (`ACTION_WEIGHTS` in `analytics.py`) scales how much each
action contributes to the rating. Terminal, point-scoring actions (attack,
block) count for more; setting is a low-risk continuation and is discounted so
the rating no longer favours setters simply because they touch the ball most.
`ACTION_WEIGHTS['E']` (0.65) is the primary tuning dial — lower it to discount
setting further, raise it to reward playmaking.

### Grades

| Code | Name | Rating weight |
|------|------|--------------|
| `#`  | Perfecto (Perfect)  | +1.0 |
| `+`  | Positivo (Positive) | +0.4 |
| `!`  | Regular (Regular)   | −0.3 |
| `-`  | Error (Error)       | −1.0 |

### Special lines

- `---` — set separator (resets rally context)
- `@youtube: https://youtu.be/...` — links a YouTube video to this set

### Example log

```
7S# 10R! 2E+ 7A-
25R+ 2E+ 25A#
8S-
@youtube: https://youtu.be/example
---
2R# 25E+ 20A+
```

## Exporting Data to CSV

To export every dataset's match data to CSV files (readable in Excel or Google Sheets):

```bash
python export_csv.py
```

For each dataset, three files are written next to its database in `data/<team_slug>/<tournament_slug>/`:

| File | Contents |
|------|----------|
| `matches.csv` | One row per match — title, date, YouTube URLs |
| `team_match_stats.csv` | Aggregated team stats for every match |
| `player_match_stats.csv` | Per-player stats for every match |

> **Note:** Run `python generate.py` first to make sure the databases are up to date before exporting.

## Project Structure

```
volleyball_analytics/
├── analytics.py                 # Parsing + calculations + load_team_config()
├── db.py                        # SQLite persistence (one DB per dataset)
├── renderer.py                  # HTML page builders
├── generate.py                  # Orchestrator: discover datasets → DB → HTML
├── export_csv.py                # Export each dataset's tables to CSV files
├── styles.css                   # Shared CSS for all generated pages
├── teams/                       # COMMITTED source data
│   └── <team>/<tournament>/
│       ├── team.json            # roster + metadata
│       └── matches/NN_*.txt     # match logs (prefix controls order)
├── .github/workflows/build.yml  # GitHub Actions: build + deploy on push
├── data/                        # GENERATED databases + CSVs (not committed)
│   └── <team>/<tournament>/volleyball.db
├── docs/                        # GENERATED static site (not committed)
│   ├── index.html               # root team/tournament selector
│   └── <team>/<tournament>/...  # per-dataset dashboard
└── README.md
```

The `docs/` folder and the per-dataset `data/**/*.db` and `data/**/*.csv` files are generated automatically and are **not committed** to the repo. Only the `teams/` source tree is committed.

## Deployment to GitHub Pages

**One-time setup:**

1. Push this repository to GitHub
2. Go to **Settings → Pages → Source**
3. Select **"GitHub Actions"** (not "Deploy from a branch")
4. Your site will be live at `https://yourusername.github.io/volleyball_analytics`

After that, every `git push` to `main` triggers an automatic rebuild.

## How It Works

1. `generate.py` discovers every dataset folder under `teams/` that contains a `team.json`
2. For each dataset it parses the `matches/*.txt` logs into a dedicated `data/<team>/<tournament>/volleyball.db`
3. `parse_log()` tokenizes lines into rallies and records per-player and team stats
4. `calculate_rating()` computes an action-weighted 1–10 rating:
   `6.0 + 4.0 × (Σ grade_count × grade_weight × action_weight) / total`, then
   clamped to `[1.0, 10.0]`. Dividing by the raw touch count (not by the weighted
   count) is what makes low-leverage actions such as setting contribute less.
   `calculate_efficiency()` derives per-skill metrics: attack efficiency
   `(A# − A-) / A_tot`, reception positivity, serve ace/error %, set positivity,
   and block kills. (Attack efficiency still counts rival-error points as kills
   until the Phase 2 grade-integrity work lands.)
5. `calculate_phase_stats()` tracks Side-Out and Transition kill sequences
6. `calculate_point_stats()` infers Break Point / Side-Out outcomes from rally order
7. Static HTML is written to `docs/<team>/<tournament>/`, and a root `docs/index.html` selector links to every dataset

Datasets with no valid match data (e.g. a brand-new team folder) are skipped automatically. All data stays in the repository. No server, no external services.

## Troubleshooting

### GitHub Pages not updating?

- Go to the **Actions** tab in GitHub and check the latest workflow run for errors
- Make sure Pages source is set to **GitHub Actions**, not a branch

### A match is skipped during generation?

The script prints `Skipped (no data): filename.txt` if a file contains no valid tokens. Check the log format.

### Browser opens but styles are missing?

Make sure `styles.css` is in the repo root — `generate.py` copies it to `docs/` on each run.

## License

MIT License
