<!-- Thanks for contributing! Fill in the sections below and delete any that don't apply. -->

## Summary

<!-- What does this PR do and why? -->

## Type of change

- [ ] Bug fix
- [ ] Feature / enhancement
- [ ] Match data (new or edited `teams/**/matches/*.txt`)
- [ ] Docs
- [ ] Tooling / CI

## Match-data checklist

<!-- Complete this section only if this PR adds or edits any teams/**/*.txt log. -->

- [ ] Tokens follow the [log grammar](https://github.com/lopez12/volleyball_analytics/blob/main/README.md#match-log-format) — play token `<num?><SREADB><#+!->`, header lines `@set: V-R` / `@youtube:` / `@date:`, and outcome tokens `@won` / `@lost` / `@won:re` / `@won:se`.
- [ ] Every player number appears in the dataset's `team.json` roster.
- [ ] `python validate_logs.py` passes locally with **no ERRORs** (see [Validating logs](https://github.com/lopez12/volleyball_analytics/blob/main/README.md#validating-logs-qa-gate)).
- [ ] `python generate.py` still builds without crashing.

> The PR gate (`.github/workflows/qa.yml`) validates only the match logs **changed in this PR** and then runs a smoke build. ERRORs fail the check; WARNs do not (run `validate_logs.py --strict` if you want warnings to fail too).

## Notes

<!-- Anything reviewers should know: screenshots, follow-ups, backward-compatibility impact. -->
