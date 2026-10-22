# Architect Brief - Graded Match Spectator Replay

Date: 2026-10-21
Requested branch: `fix_45`
Status: Ready for developer handoff; implementation blocked until command execution is available.

## Objective

Let spectators watch published, fully graded volleyball sets on YouTube with spoiler-safe, playback-synchronized scores and statistics, and rally navigation that skips dead time.

## Scope

- `analytics.py`: additive set-aware timeline parsing, replay eligibility, and cumulative statistics.
- `renderer.py`: match-report entry point, unavailable explanations, and a pure spectator-page renderer.
- `generate.py`: retain replay payloads from source parsing, render replay pages, and copy the viewer asset.
- New `viewer.js`: read-only YouTube player controller, playback synchronization, navigation, and accessible UI updates.
- `styles.css`: additive viewer layout using existing theme tokens.
- New `tests/test_replay.py`: standard-library unit and integration tests.
- New `tests/viewer_test.js`: dependency-free controller/synchronization tests runnable with Node when available; no npm setup.
- `README.md`: eligibility, spectator usage, limitations, and test commands.
- This brief and its promotion to `ARCHITECT-BRIEF.md` once the implementation branch is safely established.

Generated only: `docs/<team>/<dataset>/<stem>_watch.html`, copied `viewer.js`, and rebuilt report/style assets. Never edit generated files by hand.

Untouched: `teams/**`, `logger/**`, database schema and queries, rating formulas, match-log grammar, and CI workflows. No validation rule changes are needed: stricter eligibility is local to replay.

## Requirements

1. **Safe development workflow.** Inspect the worktree, current branch, local/remote `fix_45`, and remotes before making implementation changes. Preserve unrelated work. Create `fix_45` from the intended base if absent; if it exists, inspect and continue only when it belongs to this task. Do not force-push or reset. Confirm GitHub issue 45 before adding any `Closes #45` reference; the branch name alone is not evidence of issue identity.

2. **Set-aware source model.** Extend the existing parser additively rather than introduce a second grammar parser. Preserve every existing return value and statistic. Add an ordered per-set representation retaining rally tokens, explicit outcome/cause, timestamp, set number, video association, final score, and diagnostics. Exact `---` separators define set boundaries; a single-set file requires none. Metadata preceding the first rally in a set belongs to that set; final-score metadata after rallies and before a separator belongs to that set as well. Conflicting scores or multiple video declarations within a set make association ambiguous and that set ineligible. Empty separator blocks must not shift subsequent video/set associations. Unsupported separator-like lines, duplicate/malformed timing or outcomes, or unknown non-comment content that could conceal a rally must produce replay diagnostics instead of silently certifying completeness. Legacy parsing remains unchanged.

3. **Eligibility is per set.** An eligible set has at least one rally, a supported YouTube URL with a valid 11-character ID, exactly one explicit result per rally, and finite timestamps with `0 <= start <= end`. Consecutive intervals must satisfy `previous.end <= next.start`; equal boundaries and zero-duration rallies are allowed. Every rally must contain graded touches, except a touchless `@won:se` event. Outcome-plus-timestamp-only segmentation records with any other result are ineligible because their grading cannot be established. If a final `@set` score exists, outcome totals must match it. No final score is required: in its absence the page makes no claim of independent score reconciliation. Never sort rallies to repair chronology, guess missing timing, infer outcomes, or change input data. Publish all exclusion reasons in Spanish. A set failing any criterion is excluded as a whole; other eligible sets remain usable.

4. **Deterministic analytics payload.** Analytics provides JSON-compatible eligible-set data with rally start/end, stable set/rally IDs, initial zero snapshot, and one snapshot after each completed rally. Each snapshot contains score, recorded touch totals, aces (`S#`), attack kills (`A#`), point-winning blocks (`B#`), graded errors (all recorded `-` touches, explicitly labeled "Toques con error"), attack efficiency via `calculate_efficiency`, and player rows. Player rows contain number, touches, attack kills, aces, blocks, and rating via `calculate_rating`; names come from dataset configuration at rendering time. Team-only touches affect team totals only. Denominator-zero efficiency and no-touch player ratings display as unavailable, not invented measurements. Do not change existing analytics formulas. Longest completed rally is `end - start`; ties choose the first rally. No completed rally means no longest-rally value.

5. **Source-to-output integration.** Existing reports are rendered from DB results that do not retain rally arrays. Retain the source-derived replay model by match stem during the normal parse/upsert loop and pass it separately to rendering. Do not reparse in JavaScript or migrate SQLite for transport. Eligible matches get `<stem>_watch.html` and a relative "Ver con estadísticas" report link. Ineligible sets are explained both on the report and, for mixed matches, in the viewer. Matches with no eligible sets get no active viewer link; remove only the exact stale generated watch file for such a known stem if it exists. Copy the viewer asset where the generated page's relative reference resolves. Preserve logger behavior and all existing report content apart from additive replay notices/links.

6. **Spoiler-safe viewer.** Render Spanish UI with embedded YouTube, explicit set selector, scoreboard, current rally/status, team cards, longest-completed-rally replay, player table, rally list, report backlink, and scope label "Estadísticas del set hasta este momento". Desktop places video beside stats; mobile stacks them. Initial state is 0-0 with zero counts. Before a rally's end, its point and touches are not included. At the exact end they are included, including zero-duration events. A snapshot is selected by the greatest rally end not later than current time, never by incrementing counters. Future rally list entries show only set/rally identity and seek controls, not results, final score, or future longest-rally values. Full-match results remain available through the separate report backlink. This is a presentation guarantee, not secrecy of the public embedded data.

7. **Playback and navigation.** Use a thin YouTube IFrame API controller with explicit ready/state/error handling; no dependency on the logger's mutable state. Reconcile snapshots on ready, seeking/state changes, and a bounded timer (at most 250 ms while playing), reading actual player time. Pause, buffering, rewind, repeated seeks, speed changes, and set switches cannot double-count. Switching sets resets visible stats and loads the selected video's own clock at zero. "Siguiente jugada" selects the earliest start strictly greater than actual current time in that set. Disable it when none exists or the player is unavailable. "Repetir jugada" selects the active interval, or the latest completed rally during a gap; disable it before any applicable rally. Longest-rally and list buttons seek to their rally start. Preserve playing/paused intent across seeks, respecting autoplay restrictions. Never automatically cross to another set.

8. **Failure and accessibility behavior.** Before player readiness and during buffering, show explicit synchronization status. API-load failure, video errors, blocked embeds, invalid runtime payload, or unsupported `file://` operation disable synchronized controls and show Spanish explanations with a safe YouTube link. Stale stats must not appear current. Use button semantics, visible focus, associated labels, non-color-only statuses, responsive tables, and a polite live region for score/status changes rather than continuously announcing every poll. Reuse existing theme boot/toggle behavior and CSS tokens. Escape HTML, use DOM text APIs for runtime values, and serialize JSON safely against `</script>` termination. Support only vetted YouTube embed/link hosts and IDs. Existing CSP permits YouTube; do not broaden it speculatively.

9. **Validation and delivery.** Add deterministic tests covering parser compatibility, eligibility reasons, set/video mapping, source-to-render integration, initial/boundary/final snapshots, all team/player formulas, touchless faults, team-only tokens, zero-duration events, ties, backward seeks, navigation and set resets, safe serialization, and unavailable controls. Run `python -m unittest discover -s tests`, `node tests/viewer_test.js` if Node is available, `python validate_logs.py`, `python generate.py` with `CI=1`, `ruff check .`, and `ruff format --check .`. Use actual outputs in the PR, not assumed passes. Verify real YouTube playback, mobile layout, theme and browser-console/CSP behavior when browser tooling is available; otherwise record those checks as outstanding. Obtain reviewer findings before final delivery. Commit only task-owned files in coherent groups, include the required co-author trailer, push `fix_45` without force, and provide a PR body following the repository template. Do not create a PR unless requested separately.

## Constraints

- Python 3.12 standard library; vanilla JavaScript; no framework, bundler, server, or installed runtime package.
- Analytics owns grammar/statistics, renderer owns HTML, generator owns filesystem operations; browser code selects snapshots and controls playback, not statistical formulas.
- Existing optional outcomes/timestamps remain optional globally. Replay disqualification is not a new QA validation failure.
- Existing real logs may be chronologically inconsistent or incomplete despite being graded. Do not silently lower the eligibility bar to make the viewer appear populated.
- Do not edit match data to generate a demonstration. Use synthetic test fixtures for a fully eligible set if necessary.
- Read applicable instructions and integrate existing changes before editing. Stop on conflicting user work.
- Preserve the unrelated current deploy-hardening brief until branch/worktree checks succeed. Then archive its exact contents as `briefs/BRIEF-11-deploy-hardening.md` if that path is absent, explicitly labeling it carried forward rather than claiming it has shipped, and promote this brief to `ARCHITECT-BRIEF.md`. If either destination conflicts, ask before overwriting.

## Decisions

- **Strict eligibility, not heuristic "live" stats:** score correctness matters more than offering replay for every existing log.
- **Equal start/end allowed:** real data contains instantaneous point events; they complete at their timestamp and have recorded duration zero.
- **Touchless support restricted to explicit opponent serve faults:** other outcome-only records cannot reliably distinguish segmentation from completed grading.
- **Per-set stats:** avoids ambiguity around match-wide aggregation and independent video clocks.
- **Precomputed snapshots:** keeps statistical definitions in Python and makes rewind deterministic with a small read-only browser implementation.
- **Dedicated generated watch page:** separates spectator UI from authoring state and final-report spoilers.
- **No automatic skipping in the first release:** manual navigation meets the request without surprise playback transitions.
- **No issue-closing claim before verification:** issue 45 was not accessible during planning.
- **This is a queued brief, not evidence of completion:** its initial placement under `briefs/` preserves the current in-flight root brief while tooling is unavailable.

## Out of Scope

- Live ingestion, broadcasts, grading, timestamp correction, and match-log edits.
- Individual-touch synchronization, inferred opponent/player statistics, exact ball-in-play durations.
- Downloaded clips, exports, automatic skip mode, filter compilations, cross-match reels.
- Momentum charts, point streaks, shareable deep links, and spoiler-toggle/full-summary mode.
- New database schema, new log tokens, expanded global validation rules, or speculative CSP changes.
- Creating or merging a pull request without a separate request; this handoff asks for a pushed branch and filled PR body.

## Acceptance Criteria

1. The developer verifies a safe `fix_45` branch and preserves unrelated work; issue linkage is confirmed or explicitly omitted. (R1)
2. Existing parser outputs and statistics are unchanged; added set data preserves association and ambiguity diagnostics across single/multiple/empty blocks. (R2)
3. Every eligibility condition has positive/negative tests, including touchless segmentation, invalid IDs, nonfinite/negative/overlapping timing, zero-duration events, and mismatched final scores. Mixed matches expose only eligible sets with reasons for exclusions. (R3)
4. Every snapshot agrees with existing analytics on the equivalent rally prefix, including unattributed touches and player ratings; longest-rally ties are stable. (R4)
5. Generated eligible reports link to usable viewer pages/assets; no eligible set means no active link or stale viewer file. No persistence migration or hand-edited output exists. (R5)
6. For rallies `10-15 @won` and `30-38 @lost`, displayed score is 0-0 before 15, 1-0 from 15 to before 38, and 1-1 at/after 38. Rewind to 12 restores 0-0 and zero stats. Future results stay out of visible UI. (R6)
7. From 16 seconds, next seeks to 30; at/after the final start next is disabled. All navigation preserves intent and recomputes stats; switching independent videos resets to the chosen set's beginning. (R7)
8. Player readiness/failures show explicit status; inaccessible controls cannot act, serialization resists script termination, and layouts/themes/keyboard controls work. (R8)
9. Required commands have recorded results, reviewer findings are addressed, logical commits are pushed on `fix_45`, and the filled PR body accurately reports verification gaps. If tooling is unavailable, no completion/push/test claims are made. (R9)

## Intended Commit Sequence

1. `docs: specify graded-match spectator replay` - brief promotion and preservation of prior brief.
2. `feat: build eligible set replay timelines and snapshots` - analytics and targeted Python tests.
3. `feat: add synchronized YouTube spectator player` - renderer, viewer script, styles, controller tests.
4. `feat: integrate spectator replay into generated reports` - generator integration and documentation.
5. `test: cover replay integration and review fixes` - only actual remaining tests/review corrections; omit if already complete in earlier commits.

Every commit ends with:

`Co-authored-by: Copilot <223556219+Copilot@users.noreply.github.com>`

## References

- [Project documentation](../README.md).
- [Project instructions](../.github/copilot-instructions.md).
- [Timestamp foundation](BRIEF-4-timestamps-pre-analysis.md).
- [Logger playback scope, explicitly excluding public reports](BRIEF-6-inapp-playback-compilation.md).
- [Analytics](../analytics.py), [renderers](../renderer.py), and [orchestration](../generate.py).
- [PR template](../.github/PULL_REQUEST_TEMPLATE.md).
