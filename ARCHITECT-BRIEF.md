# Architect Brief - Graded Match Spectator Replay

Date: 2026-10-21
Branch: `fix_45`
Issue: #45, verified against GitHub on 2026-10-21.
Status: Accepted for developer implementation; command execution is available.

The complete, authoritative requirements, decisions, acceptance criteria and
intended commit sequence are in
[`briefs/BRIEF-13-spectator-replay.md`](briefs/BRIEF-13-spectator-replay.md).
This promotes that queued brief without changing its planning history.
Implement requirements R1–R9 in that document; do not substitute the unrelated
deploy-hardening plan.

The previous root brief is preserved **verbatim**, carried forward rather than
claimed shipped, at
[`briefs/BRIEF-11-deploy-hardening.md`](briefs/BRIEF-11-deploy-hardening.md).
Other pre-existing untracked briefs are not part of this change.

Developer handoff: build additive source-owned per-set timelines and snapshots,
a read-only spoiler-safe YouTube viewer, and generator/report integration.
Preserve legacy parsing, database schema, logger and match data. Validate with
standard-library tests, log validation, smoke generation and available tooling.
Record browser, Node, Ruff and independent-review limitations honestly.
