<!--
Use this template for every BoxCutter PR. Three sections, in order:
Summary, Test plan, Risk. Keep each tight; reviewer time is the
expensive resource.
-->

## Summary

<!--
What this PR does and why. Reference roadmap IDs (S-NN, B-NN, R-NN, C-NN)
or PLAN_xxx if applicable. One paragraph or a short bullet list.
-->

## Test plan

- [ ] `python tools/check.py` passes locally
- [ ] New tests added (or justified absence: e.g. "fix is covered by existing test_X")
- [ ] Manual verification, if UI/UX behaviour changed (and how)

<!--
For release-gating PRs (those that touch security boundaries, data
integrity, or the release pipeline) ALSO check:
-->

- [ ] `python tools/check.py --strict` passes (only required for releases)

## Risk

<!--
Honest one-paragraph assessment. Backwards-compatibility, migrations,
performance, who could be surprised. Include "low risk" if accurate —
saying so explicitly is more useful than the section being empty.
-->
