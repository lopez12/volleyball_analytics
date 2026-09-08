# Architect Brief - Contribution Templates: Issue Forms & PR Template (Phase 8)
Date: 2026-09-07

## Objective
Add GitHub issue templates (bug, feature, match-data log) and a pull-request template under `.github/` so contributions arrive structured, and so match-data PRs point the author at the log grammar and the `validate_logs.py` QA gate before they open the PR.

## Problem
The repository has no `.github/ISSUE_TEMPLATE/` and no `PULL_REQUEST_TEMPLATE.md`. Issues and PRs therefore arrive as free-form prose with no required fields. Two consequences matter here:

1. **Bug/feature triage is manual** — reporters omit the dataset (`teams/<team>/<dataset>`), reproduction steps, or which page/report is wrong, so a maintainer round-trips for basics.
2. **Match-data PRs bypass the QA contract.** The single most common contribution is a new/edited match log (`teams/**/matches/*.txt`). The grammar (`<num?><SREADB><#+!->`, `@set: V-R`, `@youtube:`, `@won`/`@lost`/`@won:re`/`@won:se`) and the roster/validator rules already exist and are enforced by [.github/workflows/qa.yml](../.github/workflows/qa.yml), but nothing tells a contributor to run `python validate_logs.py` *before* pushing. The PR template must make that gate visible up front.

## Scope
- **New:** `.github/ISSUE_TEMPLATE/config.yml` — issue-chooser config (disable blank issues if desired; optional contact links).
- **New:** `.github/ISSUE_TEMPLATE/bug_report.yml` — GitHub Issue Form (YAML) for defects.
- **New:** `.github/ISSUE_TEMPLATE/feature_request.yml` — Issue Form for enhancements.
- **New:** `.github/ISSUE_TEMPLATE/match_data.yml` — Issue Form for reporting a wrong/missing stat or requesting a new dataset/match log.
- **New:** `.github/PULL_REQUEST_TEMPLATE.md` — single default PR template with a match-data checklist.
- **Reference only (do NOT edit):** [README.md](../README.md) log-grammar section, [validate_logs.py](../validate_logs.py), [.github/workflows/qa.yml](../.github/workflows/qa.yml).

## Requirements
1. **Issue-chooser config.** `.github/ISSUE_TEMPLATE/config.yml` sets `blank_issues_enabled: false` and lists the three forms. It MAY add a `contact_links` entry pointing to the README log-grammar section for "how do I write a log?" questions, so that is not filed as a bug.
2. **Bug report form.** `bug_report.yml` is a valid GitHub Issue Form with, at minimum: a short summary; the affected **dataset** (`team/dataset`, e.g. `nova/amistosos`) and match/page if applicable; steps to reproduce; expected vs. actual behavior; and a checkbox confirming the reporter ran the build (`python generate.py`) or checked the published page. Label it `bug`.
3. **Feature request form.** `feature_request.yml` captures: the problem/motivation; the proposed report/page/CLI change; which layer it touches (log grammar, `analytics.py` engine, `db.py`, `renderer.py`/HTML, `logger/` author UI); and backward-compatibility impact on existing logs/datasets. Label it `enhancement`.
4. **Match-data form.** `match_data.yml` captures: the dataset and match file (`teams/<team>/<dataset>/matches/NN_*.txt`); whether this is a *correction* or a *new log/dataset*; the specific stat/rally in question; and a required checkbox acknowledging the log grammar and that `python validate_logs.py` was run locally. Label it `data`.
5. **PR template.** `.github/PULL_REQUEST_TEMPLATE.md` includes: a summary section; a "type of change" set (bug fix / feature / match-data / docs / tooling); and a **match-data checklist** that a contributor ticks when the PR touches `teams/**/*.txt`. The match-data checklist MUST reference, by exact command, that `python validate_logs.py` passes locally and MUST link to the README log-grammar and validator sections.
6. **Grammar accuracy.** Every reference to the grammar in these templates must match the canonical grammar as documented in [README.md](../README.md) and enforced by [validate_logs.py](../validate_logs.py) — play token `<num?><SREADB><#+!->`, header lines `@set: V-R` / `@youtube:` / `@date:` (Brief 7), outcome tokens `@won` / `@lost` / `@won:re` / `@won:se`, roster membership from `team.json`. Do NOT invent, rename, or re-spell tokens; link to the README rather than re-hard-coding the full grammar table.
7. **QA-gate alignment.** The match-data guidance must reflect what [.github/workflows/qa.yml](../.github/workflows/qa.yml) actually enforces: only *changed* `teams/**/*.txt` files are validated on a PR, ERRORs fail the check, WARNs do not (unless `--strict`), and a smoke build (`python generate.py`) must still pass. Do not promise stricter behavior than the gate delivers.

## Constraints
- Use GitHub **Issue Forms** (`.yml` with `name`, `description`, `title`, `labels`, `body:` of typed elements) for the three issue templates — not legacy Markdown issue templates — so fields are structured and machine-triageable. The PR template stays Markdown (`PULL_REQUEST_TEMPLATE.md`), as GitHub does not support PR forms.
- Templates are **documentation/config only.** Do NOT modify `analytics.py`, `db.py`, `renderer.py`, `generate.py`, `validate_logs.py`, the workflows, or any dataset. No engine, schema, HTML, or grammar behavior changes.
- Reference the grammar by **linking to the README**; keep any inline reminder to a short pointer, not a duplicated grammar table, so the templates cannot drift from the single source of truth.
- Use labels that are safe to auto-apply (`bug`, `enhancement`, `data`); do not assume any other labels exist. Do not add assignees or projects.
- File names and paths must match GitHub's expected locations exactly (`.github/ISSUE_TEMPLATE/*.yml`, `.github/ISSUE_TEMPLATE/config.yml`, `.github/PULL_REQUEST_TEMPLATE.md`) or GitHub will silently ignore them.
- Keep language consistent with the repo's mixed EN/ES domain terms (e.g. dataset slugs like `nova/amistosos`); UI copy in the templates is English.

## Decisions (finalized here)
- **Three issue forms, not one.** Bug, feature, and match-data are distinct triage flows with different required fields; a single generic form would recreate the free-form problem for the most common (match-data) case. *(Rejected: one combined template.)*
- **A single default PR template** with a conditional match-data checklist, rather than multiple PR templates behind a query param. GitHub applies one default `PULL_REQUEST_TEMPLATE.md` automatically; a checklist the author fills in is simpler and always shown. *(Rejected: `.github/PULL_REQUEST_TEMPLATE/` multi-file variant — needs `?template=` URLs the author must know.)*
- **Blank issues disabled** so contributors are funneled into a form; the "how do I write a log?" escape hatch is a `contact_links` entry to the README, not a blank issue.
- **Link, don't duplicate, the grammar.** The templates point to the README grammar section and the `validate_logs.py` command; they do not restate the token tables, so they cannot silently diverge from `analytics.py`.

## Out of Scope
- No changes to the log grammar, parser, engine, DB schema, CSV export, renderer, or generated HTML.
- No changes to `validate_logs.py` behavior or to `.github/workflows/*.yml` (the QA gate already exists; templates only *reference* it).
- No `CONTRIBUTING.md`, `CODEOWNERS`, Dependabot, label definitions, or GitHub Discussions setup (each is a separate follow-up if wanted).
- No new automation that auto-runs the validator from an issue/PR body; the QA workflow is the enforcement point.
- No datasets, rosters, or match logs are added or edited.

## Acceptance Criteria
1. `.github/ISSUE_TEMPLATE/config.yml` exists, disables blank issues, and lists the three forms (Req 1).
2. `bug_report.yml`, `feature_request.yml`, and `match_data.yml` exist under `.github/ISSUE_TEMPLATE/`, are valid GitHub Issue Forms (parse without error in the GitHub UI / against the schema), and carry the required fields and labels in Req 2–4.
3. `.github/PULL_REQUEST_TEMPLATE.md` exists with a summary, a type-of-change set, and a match-data checklist that names `python validate_logs.py` and links the README grammar + validator sections (Req 5).
4. Every grammar/token reference in the templates matches the canonical grammar (Req 6); no token is invented or re-spelled, and the full grammar table is linked, not duplicated.
5. Match-data guidance matches the real QA gate (changed-files-only, ERROR-fails / WARN-passes, smoke build) with no over-promised strictness (Req 7).
6. No file outside `.github/ISSUE_TEMPLATE/` and `.github/PULL_REQUEST_TEMPLATE.md` is modified.

## References
- [README.md](../README.md) — log grammar, outcome tokens, and "Validating logs (QA gate)" section (single source of truth to link).
- [validate_logs.py](../validate_logs.py) — validator rules R1–R7 and the `<num?><SREADB><#+!->` play-token grammar.
- [.github/workflows/qa.yml](../.github/workflows/qa.yml) — the PR gate the match-data guidance must mirror (changed-files-only validation + smoke build).
- [briefs/BRIEF-7-match-date.md](BRIEF-7-match-date.md) — precedent for the `@`-header token family referenced in the templates.
- GitHub docs: "Configuring issue templates for your repository" (Issue Forms schema) and "Creating a pull request template".
