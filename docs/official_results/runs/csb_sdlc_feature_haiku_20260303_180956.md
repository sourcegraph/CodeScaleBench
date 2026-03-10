# csb_sdlc_feature_haiku_20260303_180956

## baseline-local-direct

- Valid tasks: `6`
- Mean reward: `0.467`
- Pass rate: `0.667`
- Scorer families: `repo_state_heuristic (3), ir_checklist (2), f1 (1)`
- Output contracts: `answer_json_bridge (6)`

| Task | Status | Reward | Passed | Scorer Family | Output Contract | MCP Ratio | Tool Calls | Trace |
|---|---|---:|---|---|---|---:|---:|---|
| [envoy-grpc-server-impl-001](../tasks/csb_sdlc_feature_haiku_20260303_180956--baseline-local-direct--envoy-grpc-server-impl-001--4b4fae5dc6.html) | `failed` | 0.000 | `False` | `f1` | `answer_json_bridge` | - | - | traj, tx |
| [strata-cds-tranche-feat-001](../tasks/csb_sdlc_feature_haiku_20260303_180956--baseline-local-direct--strata-cds-tranche-feat-001--4844c9d5fe.html) | `failed` | 0.000 | `False` | `ir_checklist` | `answer_json_bridge` | - | - | traj, tx |
| [flink-pricing-window-feat-001](../tasks/csb_sdlc_feature_haiku_20260303_180956--baseline-local-direct--flink-pricing-window-feat-001--140273bc7d.html) | `passed` | 0.470 | `True` | `ir_checklist` | `answer_json_bridge` | 0.000 | 39 | traj, tx |
| [pytorch-gradient-noise-feat-001](../tasks/csb_sdlc_feature_haiku_20260303_180956--baseline-local-direct--pytorch-gradient-noise-feat-001--e539c564d7.html) | `passed` | 0.833 | `True` | `repo_state_heuristic` | `answer_json_bridge` | 0.000 | 24 | traj, tx |
| [tensorrt-mxfp4-quant-feat-001](../tasks/csb_sdlc_feature_haiku_20260303_180956--baseline-local-direct--tensorrt-mxfp4-quant-feat-001--4339a883fa.html) | `passed` | 1.000 | `True` | `repo_state_heuristic` | `answer_json_bridge` | 0.000 | 104 | traj, tx |
| [vscode-stale-diagnostics-feat-001](../tasks/csb_sdlc_feature_haiku_20260303_180956--baseline-local-direct--vscode-stale-diagnostics-feat-001--72b59df700.html) | `passed` | 0.500 | `True` | `repo_state_heuristic` | `answer_json_bridge` | 0.000 | 56 | traj, tx |
