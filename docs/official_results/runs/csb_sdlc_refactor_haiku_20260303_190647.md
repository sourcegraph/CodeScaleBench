# csb_sdlc_refactor_haiku_20260303_190647

## baseline-local-direct

- Valid tasks: `5`
- Mean reward: `0.677`
- Pass rate: `0.800`
- Scorer families: `repo_state_heuristic (3), ir_checklist (1), semantic_similarity (1)`
- Output contracts: `answer_json_bridge (5)`

| Task | Status | Reward | Passed | Scorer Family | Output Contract | MCP Ratio | Tool Calls | Trace |
|---|---|---:|---|---|---|---:|---:|---|
| [pytorch-optimizer-foreach-refac-001](../tasks/csb_sdlc_refactor_haiku_20260303_190647--baseline-local-direct--pytorch-optimizer-foreach-refac-001--abe147bfa6.html) | `failed` | 0.000 | `None` | `repo_state_heuristic` | `answer_json_bridge` | 0.000 | 40 | traj, tx |
| [kafka-batch-accumulator-refac-001](../tasks/csb_sdlc_refactor_haiku_20260303_190647--baseline-local-direct--kafka-batch-accumulator-refac-001--8c2c920c59.html) | `passed` | 0.630 | `None` | `ir_checklist` | `answer_json_bridge` | 0.000 | 81 | traj, tx |
| [prometheus-query-engine-refac-001](../tasks/csb_sdlc_refactor_haiku_20260303_190647--baseline-local-direct--prometheus-query-engine-refac-001--a21d8ec8d7.html) | `passed` | 0.833 | `None` | `repo_state_heuristic` | `answer_json_bridge` | 0.000 | 27 | traj, tx |
| [python-http-class-naming-refac-001](../tasks/csb_sdlc_refactor_haiku_20260303_190647--baseline-local-direct--python-http-class-naming-refac-001--5179732f20.html) | `passed` | 0.920 | `None` | `semantic_similarity` | `answer_json_bridge` | 0.000 | 80 | traj, tx |
| [terraform-eval-context-refac-001](../tasks/csb_sdlc_refactor_haiku_20260303_190647--baseline-local-direct--terraform-eval-context-refac-001--be364e5489.html) | `passed` | 1.000 | `None` | `repo_state_heuristic` | `answer_json_bridge` | 0.000 | 110 | traj, tx |
