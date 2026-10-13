---
agent: architect
description: 'Scaffold a new ARCHITECT-BRIEF.md for a feature or change, following the house brief format.'
---

Produce a new `ARCHITECT-BRIEF.md` at the repo root for this request:

${input:request:Describe the feature, change, or problem to scope}

Before writing, ground yourself:

- Read `.github/copilot-instructions.md` and `README.md` for the architecture and the match-log grammar.
- Read the current `ARCHITECT-BRIEF.md` and skim `briefs/` so the new brief does not contradict earlier decisions.
- Read the actual code in the modules you expect to touch (`analytics.py`, `db.py`, `renderer.py`, `generate.py`, `logger/app.js`, ...). Do not assume - cite real functions and line numbers.

Then write `ARCHITECT-BRIEF.md` in the house format:

- **Title**, **Date**, and **Issue** (`#<n> - "..."`, omit if none).
- **Objective** - one sentence.
- **Scope** - the exact files/modules in play; nothing outside this list may be touched.
- **Requirements** - numbered, each testable and unambiguous.
- **Constraints** - patterns to follow and what must not change (module layering, single-source grammar, no new dependencies, source-vs-generated, escaping, backward compatibility).
- **Decisions** - every choice the developer must not re-make, with a one-line rationale.
- **Out of Scope** - explicit boundaries to prevent drift.
- **Acceptance Criteria** - mapped 1:1 to Requirements; include the QA gate (`validate_logs.py` with no ERRORs, `python generate.py` builds) when match data or the grammar is involved.
- **References** - file paths and line numbers; link the prior brief if this continues one.

Do not write feature code. Hand the finished brief to the developer agent.
