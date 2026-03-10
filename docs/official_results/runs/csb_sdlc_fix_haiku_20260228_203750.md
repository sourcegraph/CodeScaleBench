# csb_sdlc_fix_haiku_20260228_203750

## baseline-local-direct

- Valid tasks: `3`
- Mean reward: `0.457`
- Pass rate: `1.000`
- Scorer families: `ir_checklist (1), repo_state_heuristic (1), unknown (1)`
- Output contracts: `answer_json_bridge (2), unknown (1)`

| Task | Status | Reward | Passed | Scorer Family | Output Contract | MCP Ratio | Tool Calls | Trace |
|---|---|---:|---|---|---|---:|---:|---|
| [django-modelchoice-fk-fix-001](../tasks/csb_sdlc_fix_haiku_20260228_203750--baseline-local-direct--django-modelchoice-fk-fix-001--253184a575.html) | `passed` | 0.450 | `True` | `repo_state_heuristic` | `answer_json_bridge` | 0.000 | 142 | traj, tx |
| [django-select-for-update-fix-001](../tasks/csb_sdlc_fix_haiku_20260228_203750--baseline-local-direct--django-select-for-update-fix-001--23b4b4d23e.html) | `passed` | 0.670 | `True` | `ir_checklist` | `answer_json_bridge` | 0.000 | 55 | traj, tx |
| [flipt-eval-latency-fix-001](../tasks/csb_sdlc_fix_haiku_20260228_203750--baseline-local-direct--flipt-eval-latency-fix-001--212ced17d5.html) | `passed` | 0.250 | `True` | `-` | `-` | 0.000 | 34 | traj, tx |
