# csb_sdlc_feature_haiku_20260302_221730

## baseline-local-direct

- Valid tasks: `17`
- Mean reward: `0.481`
- Pass rate: `0.765`
- Scorer families: `repo_state_heuristic (13), ir_checklist (3), f1 (1)`
- Output contracts: `answer_json_bridge (17)`

| Task | Status | Reward | Passed | Scorer Family | Output Contract | MCP Ratio | Tool Calls | Trace |
|---|---|---:|---|---|---|---:|---:|---|
| [django-rate-limit-middleware-feat-001](../tasks/csb_sdlc_feature_haiku_20260302_221730--baseline-local-direct--django-rate-limit-middleware-feat-001--842cec29d4.html) | `failed` | 0.000 | `None` | `repo_state_heuristic` | `answer_json_bridge` | - | - | traj, tx |
| [k8s-noschedule-taint-feat-001](../tasks/csb_sdlc_feature_haiku_20260302_221730--baseline-local-direct--k8s-noschedule-taint-feat-001--ccfb20f341.html) | `failed` | 0.000 | `None` | `repo_state_heuristic` | `answer_json_bridge` | - | - | traj, tx |
| [terraform-compact-diff-fmt-feat-001](../tasks/csb_sdlc_feature_haiku_20260302_221730--baseline-local-direct--terraform-compact-diff-fmt-feat-001--3c88918cbd.html) | `failed` | 0.000 | `None` | `repo_state_heuristic` | `answer_json_bridge` | - | - | traj, tx |
| [vscode-stale-diagnostics-feat-001](../tasks/csb_sdlc_feature_haiku_20260302_221730--baseline-local-direct--vscode-stale-diagnostics-feat-001--18927677c6.html) | `failed` | 0.000 | `None` | `repo_state_heuristic` | `answer_json_bridge` | - | - | traj, tx |
| [camel-fix-protocol-feat-001](../tasks/csb_sdlc_feature_haiku_20260302_221730--baseline-local-direct--camel-fix-protocol-feat-001--a565e26d36.html) | `passed` | 0.320 | `None` | `ir_checklist` | `answer_json_bridge` | 0.000 | 40 | traj, tx |
| [cilium-policy-audit-logger-feat-001](../tasks/csb_sdlc_feature_haiku_20260302_221730--baseline-local-direct--cilium-policy-audit-logger-feat-001--6711125472.html) | `passed` | 1.000 | `None` | `repo_state_heuristic` | `answer_json_bridge` | 0.000 | 97 | traj, tx |
| [cilium-policy-quota-feat-001](../tasks/csb_sdlc_feature_haiku_20260302_221730--baseline-local-direct--cilium-policy-quota-feat-001--af1ff6d63c.html) | `passed` | 1.000 | `None` | `repo_state_heuristic` | `answer_json_bridge` | 0.000 | 63 | traj, tx |
| [curl-http3-priority-feat-001](../tasks/csb_sdlc_feature_haiku_20260302_221730--baseline-local-direct--curl-http3-priority-feat-001--9db8c4c8a2.html) | `passed` | 0.167 | `None` | `repo_state_heuristic` | `answer_json_bridge` | - | - | traj, tx |
| [envoy-custom-header-filter-feat-001](../tasks/csb_sdlc_feature_haiku_20260302_221730--baseline-local-direct--envoy-custom-header-filter-feat-001--11eab754f6.html) | `passed` | 1.000 | `None` | `repo_state_heuristic` | `answer_json_bridge` | 0.000 | 54 | traj, tx |
| [envoy-grpc-server-impl-001](../tasks/csb_sdlc_feature_haiku_20260302_221730--baseline-local-direct--envoy-grpc-server-impl-001--fbc9791b62.html) | `passed` | 0.440 | `None` | `f1` | `answer_json_bridge` | 0.000 | 31 | traj, tx |
| [flink-pricing-window-feat-001](../tasks/csb_sdlc_feature_haiku_20260302_221730--baseline-local-direct--flink-pricing-window-feat-001--415730c847.html) | `passed` | 0.060 | `None` | `ir_checklist` | `answer_json_bridge` | 0.000 | 52 | traj, tx |
| [numpy-rolling-median-feat-001](../tasks/csb_sdlc_feature_haiku_20260302_221730--baseline-local-direct--numpy-rolling-median-feat-001--91aafcf4dc.html) | `passed` | 1.000 | `None` | `repo_state_heuristic` | `answer_json_bridge` | 0.000 | 101 | traj, tx |
| [pandas-merge-asof-indicator-feat-001](../tasks/csb_sdlc_feature_haiku_20260302_221730--baseline-local-direct--pandas-merge-asof-indicator-feat-001--234435a5da.html) | `passed` | 0.667 | `None` | `repo_state_heuristic` | `answer_json_bridge` | 0.000 | 65 | traj, tx |
| [prometheus-silence-bulk-api-feat-001](../tasks/csb_sdlc_feature_haiku_20260302_221730--baseline-local-direct--prometheus-silence-bulk-api-feat-001--167dbee73d.html) | `passed` | 0.833 | `None` | `repo_state_heuristic` | `answer_json_bridge` | 0.000 | 56 | traj, tx |
| [pytorch-gradient-noise-feat-001](../tasks/csb_sdlc_feature_haiku_20260302_221730--baseline-local-direct--pytorch-gradient-noise-feat-001--332cd39d06.html) | `passed` | 0.333 | `None` | `repo_state_heuristic` | `answer_json_bridge` | - | - | traj, tx |
| [strata-cds-tranche-feat-001](../tasks/csb_sdlc_feature_haiku_20260302_221730--baseline-local-direct--strata-cds-tranche-feat-001--4f02142a7a.html) | `passed` | 0.350 | `None` | `ir_checklist` | `answer_json_bridge` | 0.000 | 53 | traj, tx |
| [tensorrt-mxfp4-quant-feat-001](../tasks/csb_sdlc_feature_haiku_20260302_221730--baseline-local-direct--tensorrt-mxfp4-quant-feat-001--3b07db9d49.html) | `passed` | 1.000 | `None` | `repo_state_heuristic` | `answer_json_bridge` | 0.000 | 83 | traj, tx |

## mcp-remote-direct

- Valid tasks: `11`
- Mean reward: `0.714`
- Pass rate: `0.818`
- Scorer families: `repo_state_heuristic (10), ir_checklist (1)`
- Output contracts: `answer_json_bridge (11)`

| Task | Status | Reward | Passed | Scorer Family | Output Contract | MCP Ratio | Tool Calls | Trace |
|---|---|---:|---|---|---|---:|---:|---|
| [mcp_k8s-noschedule-taint-feat-001_ltxnfq](../tasks/csb_sdlc_feature_haiku_20260302_221730--mcp-remote-direct--mcp_k8s-noschedule-taint-feat-001_ltxnfq--b7768eeac9.html) | `failed` | 0.000 | `None` | `repo_state_heuristic` | `answer_json_bridge` | 0.506 | 89 | traj, tx |
| [mcp_vscode-stale-diagnostics-feat-001_vh8hqh](../tasks/csb_sdlc_feature_haiku_20260302_221730--mcp-remote-direct--mcp_vscode-stale-diagnostics-feat-001_vh8hqh--9c800f909d.html) | `failed` | 0.000 | `None` | `repo_state_heuristic` | `answer_json_bridge` | 0.264 | 72 | traj, tx |
| [mcp_cilium-policy-audit-logger-feat-001_vsfwgx](../tasks/csb_sdlc_feature_haiku_20260302_221730--mcp-remote-direct--mcp_cilium-policy-audit-logger-feat-001_vsfwgx--313838e191.html) | `passed` | 1.000 | `None` | `repo_state_heuristic` | `answer_json_bridge` | 0.295 | 44 | traj, tx |
| [mcp_cilium-policy-quota-feat-001_8vx8ki](../tasks/csb_sdlc_feature_haiku_20260302_221730--mcp-remote-direct--mcp_cilium-policy-quota-feat-001_8vx8ki--bd90e01ad1.html) | `passed` | 1.000 | `None` | `repo_state_heuristic` | `answer_json_bridge` | 0.543 | 35 | traj, tx |
| [mcp_curl-http3-priority-feat-001_bygagd](../tasks/csb_sdlc_feature_haiku_20260302_221730--mcp-remote-direct--mcp_curl-http3-priority-feat-001_bygagd--6a2885f206.html) | `passed` | 0.833 | `None` | `repo_state_heuristic` | `answer_json_bridge` | 0.290 | 100 | traj, tx |
| [mcp_django-rate-limit-middleware-feat-001_r1vj9z](../tasks/csb_sdlc_feature_haiku_20260302_221730--mcp-remote-direct--mcp_django-rate-limit-middleware-feat-001_r1vj9z--91bc93043a.html) | `passed` | 1.000 | `None` | `repo_state_heuristic` | `answer_json_bridge` | 0.217 | 83 | traj, tx |
| [mcp_envoy-custom-header-filter-feat-001_ifbwlj](../tasks/csb_sdlc_feature_haiku_20260302_221730--mcp-remote-direct--mcp_envoy-custom-header-filter-feat-001_ifbwlj--5ad9ee5ae1.html) | `passed` | 1.000 | `None` | `repo_state_heuristic` | `answer_json_bridge` | 0.571 | 56 | traj, tx |
| [mcp_flink-pricing-window-feat-001_nbo2dj](../tasks/csb_sdlc_feature_haiku_20260302_221730--mcp-remote-direct--mcp_flink-pricing-window-feat-001_nbo2dj--050d07ba06.html) | `passed` | 0.490 | `None` | `ir_checklist` | `answer_json_bridge` | 0.617 | 47 | traj, tx |
| [mcp_pytorch-gradient-noise-feat-001_wog8hf](../tasks/csb_sdlc_feature_haiku_20260302_221730--mcp-remote-direct--mcp_pytorch-gradient-noise-feat-001_wog8hf--8d3207722a.html) | `passed` | 0.833 | `None` | `repo_state_heuristic` | `answer_json_bridge` | 0.295 | 61 | traj, tx |
| [mcp_tensorrt-mxfp4-quant-feat-001_oagjk2](../tasks/csb_sdlc_feature_haiku_20260302_221730--mcp-remote-direct--mcp_tensorrt-mxfp4-quant-feat-001_oagjk2--3eb7f8f3af.html) | `passed` | 0.700 | `None` | `repo_state_heuristic` | `answer_json_bridge` | 0.414 | 29 | traj, tx |
| [mcp_terraform-compact-diff-fmt-feat-001_hhaj1c](../tasks/csb_sdlc_feature_haiku_20260302_221730--mcp-remote-direct--mcp_terraform-compact-diff-fmt-feat-001_hhaj1c--aa1f823a26.html) | `passed` | 1.000 | `None` | `repo_state_heuristic` | `answer_json_bridge` | 0.514 | 37 | traj, tx |
