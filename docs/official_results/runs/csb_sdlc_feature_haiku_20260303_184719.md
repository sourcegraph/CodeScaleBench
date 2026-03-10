# csb_sdlc_feature_haiku_20260303_184719

## baseline-local-direct

- Valid tasks: `8`
- Mean reward: `0.540`
- Pass rate: `0.625`
- Scorer families: `repo_state_heuristic (6), checklist (1), ir_checklist (1)`
- Output contracts: `answer_json_bridge (7), unspecified (1)`

| Task | Status | Reward | Passed | Scorer Family | Output Contract | MCP Ratio | Tool Calls | Trace |
|---|---|---:|---|---|---|---:|---:|---|
| [bustub-hyperloglog-impl-001](../tasks/csb_sdlc_feature_haiku_20260303_184719--baseline-local-direct--bustub-hyperloglog-impl-001--b672e95f1a.html) | `failed` | 0.000 | `False` | `checklist` | `unspecified` | - | - | traj, tx |
| [cilium-policy-quota-feat-001](../tasks/csb_sdlc_feature_haiku_20260303_184719--baseline-local-direct--cilium-policy-quota-feat-001--2b7183485a.html) | `failed` | 0.000 | `False` | `repo_state_heuristic` | `answer_json_bridge` | - | - | traj, tx |
| [k8s-noschedule-taint-feat-001](../tasks/csb_sdlc_feature_haiku_20260303_184719--baseline-local-direct--k8s-noschedule-taint-feat-001--aeab81e0cd.html) | `failed` | 0.000 | `False` | `repo_state_heuristic` | `answer_json_bridge` | - | - | traj, tx |
| [camel-fix-protocol-feat-001](../tasks/csb_sdlc_feature_haiku_20260303_184719--baseline-local-direct--camel-fix-protocol-feat-001--8c8cc6fa13.html) | `passed` | 0.320 | `True` | `ir_checklist` | `answer_json_bridge` | 0.000 | 38 | traj, tx |
| [cilium-policy-audit-logger-feat-001](../tasks/csb_sdlc_feature_haiku_20260303_184719--baseline-local-direct--cilium-policy-audit-logger-feat-001--9fceb96db3.html) | `passed` | 1.000 | `True` | `repo_state_heuristic` | `answer_json_bridge` | 0.000 | 54 | traj, tx |
| [django-rate-limit-middleware-feat-001](../tasks/csb_sdlc_feature_haiku_20260303_184719--baseline-local-direct--django-rate-limit-middleware-feat-001--ddc3d340e7.html) | `passed` | 1.000 | `True` | `repo_state_heuristic` | `answer_json_bridge` | 0.000 | 114 | traj, tx |
| [envoy-custom-header-filter-feat-001](../tasks/csb_sdlc_feature_haiku_20260303_184719--baseline-local-direct--envoy-custom-header-filter-feat-001--65a40742be.html) | `passed` | 1.000 | `True` | `repo_state_heuristic` | `answer_json_bridge` | 0.000 | 61 | traj, tx |
| [terraform-compact-diff-fmt-feat-001](../tasks/csb_sdlc_feature_haiku_20260303_184719--baseline-local-direct--terraform-compact-diff-fmt-feat-001--a6e7d41e31.html) | `passed` | 1.000 | `True` | `repo_state_heuristic` | `answer_json_bridge` | 0.000 | 54 | traj, tx |

## mcp-remote-direct

- Valid tasks: `7`
- Mean reward: `0.571`
- Pass rate: `0.571`
- Scorer families: `repo_state_heuristic (6), ir_checklist (1)`
- Output contracts: `answer_json_bridge (7)`

| Task | Status | Reward | Passed | Scorer Family | Output Contract | MCP Ratio | Tool Calls | Trace |
|---|---|---:|---|---|---|---:|---:|---|
| [mcp_camel-fix-protocol-feat-001_rftkty](../tasks/csb_sdlc_feature_haiku_20260303_184719--mcp-remote-direct--mcp_camel-fix-protocol-feat-001_rftkty--c78a1f02c6.html) | `failed` | 0.000 | `False` | `ir_checklist` | `answer_json_bridge` | - | - | traj, tx |
| [mcp_django-rate-limit-middleware-feat-001_fekly4](../tasks/csb_sdlc_feature_haiku_20260303_184719--mcp-remote-direct--mcp_django-rate-limit-middleware-feat-001_fekly4--e38c8dd622.html) | `failed` | 0.000 | `False` | `repo_state_heuristic` | `answer_json_bridge` | - | - | traj, tx |
| [mcp_servo-scrollend-event-feat-001_zjzglk](../tasks/csb_sdlc_feature_haiku_20260303_184719--mcp-remote-direct--mcp_servo-scrollend-event-feat-001_zjzglk--aa78b59232.html) | `failed` | 0.000 | `False` | `repo_state_heuristic` | `answer_json_bridge` | - | - | traj, tx |
| [mcp_cilium-policy-audit-logger-feat-001_pyjxh6](../tasks/csb_sdlc_feature_haiku_20260303_184719--mcp-remote-direct--mcp_cilium-policy-audit-logger-feat-001_pyjxh6--63db41bf0c.html) | `passed` | 1.000 | `True` | `repo_state_heuristic` | `answer_json_bridge` | 0.092 | 109 | traj, tx |
| [mcp_cilium-policy-quota-feat-001_on1ylt](../tasks/csb_sdlc_feature_haiku_20260303_184719--mcp-remote-direct--mcp_cilium-policy-quota-feat-001_on1ylt--1f014287d2.html) | `passed` | 1.000 | `True` | `repo_state_heuristic` | `answer_json_bridge` | 0.488 | 43 | traj, tx |
| [mcp_envoy-custom-header-filter-feat-001_nzjmyz](../tasks/csb_sdlc_feature_haiku_20260303_184719--mcp-remote-direct--mcp_envoy-custom-header-filter-feat-001_nzjmyz--dd62600a2e.html) | `passed` | 1.000 | `True` | `repo_state_heuristic` | `answer_json_bridge` | 0.409 | 44 | traj, tx |
| [mcp_terraform-compact-diff-fmt-feat-001_l6yvaj](../tasks/csb_sdlc_feature_haiku_20260303_184719--mcp-remote-direct--mcp_terraform-compact-diff-fmt-feat-001_l6yvaj--1a715f6061.html) | `passed` | 1.000 | `True` | `repo_state_heuristic` | `answer_json_bridge` | 0.512 | 41 | traj, tx |
