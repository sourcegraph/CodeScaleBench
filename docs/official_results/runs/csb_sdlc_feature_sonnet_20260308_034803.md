# csb_sdlc_feature_sonnet_20260308_034803

## baseline-local-direct

- Valid tasks: `22`
- Mean reward: `0.660`
- Pass rate: `0.955`
- Scorer families: `repo_state_heuristic (16), ir_checklist (3), f1 (2), checklist (1)`
- Output contracts: `answer_json_bridge (21), unspecified (1)`

| Task | Status | Reward | Passed | Scorer Family | Output Contract | MCP Ratio | Tool Calls | Trace |
|---|---|---:|---|---|---|---:|---:|---|
| [k8s-noschedule-taint-feat-001](../tasks/csb_sdlc_feature_sonnet_20260308_034803--baseline-local-direct--k8s-noschedule-taint-feat-001--af77703daa.html) | `failed` | 0.000 | `False` | `repo_state_heuristic` | `answer_json_bridge` | 0.000 | 20 | traj, tx |
| [bustub-hyperloglog-impl-001](../tasks/csb_sdlc_feature_sonnet_20260308_034803--baseline-local-direct--bustub-hyperloglog-impl-001--92d8f53392.html) | `passed` | 0.167 | `True` | `checklist` | `unspecified` | 0.000 | 84 | traj, tx |
| [camel-fix-protocol-feat-001](../tasks/csb_sdlc_feature_sonnet_20260308_034803--baseline-local-direct--camel-fix-protocol-feat-001--40b63c8bdd.html) | `passed` | 0.130 | `True` | `ir_checklist` | `answer_json_bridge` | 0.000 | 58 | traj, tx |
| [cilium-policy-audit-logger-feat-001](../tasks/csb_sdlc_feature_sonnet_20260308_034803--baseline-local-direct--cilium-policy-audit-logger-feat-001--7b92cb52ec.html) | `passed` | 1.000 | `True` | `repo_state_heuristic` | `answer_json_bridge` | 0.000 | 33 | traj, tx |
| [cilium-policy-quota-feat-001](../tasks/csb_sdlc_feature_sonnet_20260308_034803--baseline-local-direct--cilium-policy-quota-feat-001--bcdc73cf33.html) | `passed` | 1.000 | `True` | `repo_state_heuristic` | `answer_json_bridge` | 0.000 | 54 | traj, tx |
| [curl-http3-priority-feat-001](../tasks/csb_sdlc_feature_sonnet_20260308_034803--baseline-local-direct--curl-http3-priority-feat-001--da8d49357e.html) | `passed` | 0.833 | `True` | `repo_state_heuristic` | `answer_json_bridge` | 0.000 | 79 | traj, tx |
| [django-rate-limit-middleware-feat-001](../tasks/csb_sdlc_feature_sonnet_20260308_034803--baseline-local-direct--django-rate-limit-middleware-feat-001--bc36a462af.html) | `passed` | 1.000 | `True` | `repo_state_heuristic` | `answer_json_bridge` | 0.000 | 38 | traj, tx |
| [envoy-custom-header-filter-feat-001](../tasks/csb_sdlc_feature_sonnet_20260308_034803--baseline-local-direct--envoy-custom-header-filter-feat-001--7af4bedcfa.html) | `passed` | 1.000 | `True` | `repo_state_heuristic` | `answer_json_bridge` | 0.000 | 52 | traj, tx |
| [envoy-grpc-server-impl-001](../tasks/csb_sdlc_feature_sonnet_20260308_034803--baseline-local-direct--envoy-grpc-server-impl-001--7f8bedc6ae.html) | `passed` | 0.440 | `True` | `f1` | `answer_json_bridge` | 0.000 | 23 | traj, tx |
| [flink-pricing-window-feat-001](../tasks/csb_sdlc_feature_sonnet_20260308_034803--baseline-local-direct--flink-pricing-window-feat-001--eaefe3c9e2.html) | `passed` | 0.440 | `True` | `ir_checklist` | `answer_json_bridge` | 0.000 | 35 | traj, tx |
| [k8s-runtime-object-impl-001](../tasks/csb_sdlc_feature_sonnet_20260308_034803--baseline-local-direct--k8s-runtime-object-impl-001--fc7a11b546.html) | `passed` | 0.100 | `True` | `f1` | `answer_json_bridge` | 0.000 | 51 | traj, tx |
| [numpy-rolling-median-feat-001](../tasks/csb_sdlc_feature_sonnet_20260308_034803--baseline-local-direct--numpy-rolling-median-feat-001--9e74bbfde6.html) | `passed` | 1.000 | `True` | `repo_state_heuristic` | `answer_json_bridge` | 0.000 | 29 | traj, tx |
| [pandas-merge-asof-indicator-feat-001](../tasks/csb_sdlc_feature_sonnet_20260308_034803--baseline-local-direct--pandas-merge-asof-indicator-feat-001--c3c373127c.html) | `passed` | 0.667 | `True` | `repo_state_heuristic` | `answer_json_bridge` | 0.000 | 33 | traj, tx |
| [postgres-copy-csv-header-feat-001](../tasks/csb_sdlc_feature_sonnet_20260308_034803--baseline-local-direct--postgres-copy-csv-header-feat-001--f16720f094.html) | `passed` | 0.333 | `True` | `repo_state_heuristic` | `answer_json_bridge` | 0.000 | 77 | traj, tx |
| [prometheus-silence-bulk-api-feat-001](../tasks/csb_sdlc_feature_sonnet_20260308_034803--baseline-local-direct--prometheus-silence-bulk-api-feat-001--0e03092b17.html) | `passed` | 0.833 | `True` | `repo_state_heuristic` | `answer_json_bridge` | 0.000 | 48 | traj, tx |
| [pytorch-gradient-noise-feat-001](../tasks/csb_sdlc_feature_sonnet_20260308_034803--baseline-local-direct--pytorch-gradient-noise-feat-001--c45346abef.html) | `passed` | 0.833 | `True` | `repo_state_heuristic` | `answer_json_bridge` | 0.000 | 28 | traj, tx |
| [servo-scrollend-event-feat-001](../tasks/csb_sdlc_feature_sonnet_20260308_034803--baseline-local-direct--servo-scrollend-event-feat-001--b92f3e496d.html) | `passed` | 0.700 | `True` | `repo_state_heuristic` | `answer_json_bridge` | 0.000 | 92 | traj, tx |
| [strata-cds-tranche-feat-001](../tasks/csb_sdlc_feature_sonnet_20260308_034803--baseline-local-direct--strata-cds-tranche-feat-001--4200579c82.html) | `passed` | 0.340 | `True` | `ir_checklist` | `answer_json_bridge` | 0.000 | 127 | traj, tx |
| [tensorrt-mxfp4-quant-feat-001](../tasks/csb_sdlc_feature_sonnet_20260308_034803--baseline-local-direct--tensorrt-mxfp4-quant-feat-001--860ce544cd.html) | `passed` | 1.000 | `True` | `repo_state_heuristic` | `answer_json_bridge` | 0.000 | 111 | traj, tx |
| [terraform-compact-diff-fmt-feat-001](../tasks/csb_sdlc_feature_sonnet_20260308_034803--baseline-local-direct--terraform-compact-diff-fmt-feat-001--3a2c72cbc3.html) | `passed` | 1.000 | `True` | `repo_state_heuristic` | `answer_json_bridge` | 0.000 | 28 | traj, tx |
| [vscode-custom-fold-region-feat-001](../tasks/csb_sdlc_feature_sonnet_20260308_034803--baseline-local-direct--vscode-custom-fold-region-feat-001--a4c68b4aec.html) | `passed` | 1.000 | `True` | `repo_state_heuristic` | `answer_json_bridge` | 0.000 | 74 | traj, tx |
| [vscode-stale-diagnostics-feat-001](../tasks/csb_sdlc_feature_sonnet_20260308_034803--baseline-local-direct--vscode-stale-diagnostics-feat-001--18880a68c3.html) | `passed` | 0.700 | `True` | `repo_state_heuristic` | `answer_json_bridge` | 0.000 | 80 | traj, tx |

## mcp-remote-direct

- Valid tasks: `20`
- Mean reward: `0.629`
- Pass rate: `0.900`
- Scorer families: `repo_state_heuristic (15), ir_checklist (3), f1 (2)`
- Output contracts: `answer_json_bridge (20)`

| Task | Status | Reward | Passed | Scorer Family | Output Contract | MCP Ratio | Tool Calls | Trace |
|---|---|---:|---|---|---|---:|---:|---|
| [mcp_k8s-noschedule-taint-feat-001_e92mqm](../tasks/csb_sdlc_feature_sonnet_20260308_034803--mcp-remote-direct--mcp_k8s-noschedule-taint-feat-001_e92mqm--c766926c05.html) | `failed` | 0.000 | `False` | `repo_state_heuristic` | `answer_json_bridge` | 0.604 | 48 | traj, tx |
| [mcp_vscode-stale-diagnostics-feat-001_20akoa](../tasks/csb_sdlc_feature_sonnet_20260308_034803--mcp-remote-direct--mcp_vscode-stale-diagnostics-feat-001_20akoa--b5be4f7909.html) | `failed` | 0.000 | `False` | `repo_state_heuristic` | `answer_json_bridge` | 0.792 | 53 | traj, tx |
| [mcp_camel-fix-protocol-feat-001_opqnga](../tasks/csb_sdlc_feature_sonnet_20260308_034803--mcp-remote-direct--mcp_camel-fix-protocol-feat-001_opqnga--9e518dba60.html) | `passed` | 0.120 | `True` | `ir_checklist` | `answer_json_bridge` | 0.584 | 89 | traj, tx |
| [mcp_cilium-policy-audit-logger-feat-001_ae6rf2](../tasks/csb_sdlc_feature_sonnet_20260308_034803--mcp-remote-direct--mcp_cilium-policy-audit-logger-feat-001_ae6rf2--8192af3fd9.html) | `passed` | 1.000 | `True` | `repo_state_heuristic` | `answer_json_bridge` | 0.405 | 42 | traj, tx |
| [mcp_cilium-policy-quota-feat-001_ucrcts](../tasks/csb_sdlc_feature_sonnet_20260308_034803--mcp-remote-direct--mcp_cilium-policy-quota-feat-001_ucrcts--0182215d9e.html) | `passed` | 1.000 | `True` | `repo_state_heuristic` | `answer_json_bridge` | 0.394 | 33 | traj, tx |
| [mcp_curl-http3-priority-feat-001_etstyk](../tasks/csb_sdlc_feature_sonnet_20260308_034803--mcp-remote-direct--mcp_curl-http3-priority-feat-001_etstyk--250ac980d5.html) | `passed` | 0.833 | `True` | `repo_state_heuristic` | `answer_json_bridge` | 0.606 | 71 | traj, tx |
| [mcp_django-rate-limit-middleware-feat-001_dawpz7](../tasks/csb_sdlc_feature_sonnet_20260308_034803--mcp-remote-direct--mcp_django-rate-limit-middleware-feat-001_dawpz7--8e728ff2bb.html) | `passed` | 1.000 | `True` | `repo_state_heuristic` | `answer_json_bridge` | 0.429 | 28 | traj, tx |
| [mcp_envoy-custom-header-filter-feat-001_bhfize](../tasks/csb_sdlc_feature_sonnet_20260308_034803--mcp-remote-direct--mcp_envoy-custom-header-filter-feat-001_bhfize--aa1dac80bf.html) | `passed` | 1.000 | `True` | `repo_state_heuristic` | `answer_json_bridge` | 0.556 | 36 | traj, tx |
| [mcp_envoy-grpc-server-impl-001_zinpuy](../tasks/csb_sdlc_feature_sonnet_20260308_034803--mcp-remote-direct--mcp_envoy-grpc-server-impl-001_zinpuy--fd6c77c2b9.html) | `passed` | 0.440 | `True` | `f1` | `answer_json_bridge` | 0.818 | 22 | traj, tx |
| [mcp_flink-pricing-window-feat-001_x1uluh](../tasks/csb_sdlc_feature_sonnet_20260308_034803--mcp-remote-direct--mcp_flink-pricing-window-feat-001_x1uluh--8e6d2b0197.html) | `passed` | 0.440 | `True` | `ir_checklist` | `answer_json_bridge` | 0.636 | 33 | traj, tx |
| [mcp_k8s-runtime-object-impl-001_8cfwyz](../tasks/csb_sdlc_feature_sonnet_20260308_034803--mcp-remote-direct--mcp_k8s-runtime-object-impl-001_8cfwyz--fae81be2d3.html) | `passed` | 0.110 | `True` | `f1` | `answer_json_bridge` | 0.947 | 152 | traj, tx |
| [mcp_numpy-rolling-median-feat-001_kfiyv7](../tasks/csb_sdlc_feature_sonnet_20260308_034803--mcp-remote-direct--mcp_numpy-rolling-median-feat-001_kfiyv7--07584d8f00.html) | `passed` | 1.000 | `True` | `repo_state_heuristic` | `answer_json_bridge` | 0.164 | 67 | traj, tx |
| [mcp_pandas-merge-asof-indicator-feat-001_ntc0yh](../tasks/csb_sdlc_feature_sonnet_20260308_034803--mcp-remote-direct--mcp_pandas-merge-asof-indicator-feat-001_ntc0yh--64186fd60e.html) | `passed` | 0.667 | `True` | `repo_state_heuristic` | `answer_json_bridge` | 0.360 | 86 | traj, tx |
| [mcp_postgres-copy-csv-header-feat-001_avoker](../tasks/csb_sdlc_feature_sonnet_20260308_034803--mcp-remote-direct--mcp_postgres-copy-csv-header-feat-001_avoker--56eb05b74b.html) | `passed` | 0.333 | `True` | `repo_state_heuristic` | `answer_json_bridge` | 0.185 | 162 | traj, tx |
| [mcp_prometheus-silence-bulk-api-feat-001_3w863m](../tasks/csb_sdlc_feature_sonnet_20260308_034803--mcp-remote-direct--mcp_prometheus-silence-bulk-api-feat-001_3w863m--f008a7a7d7.html) | `passed` | 0.833 | `True` | `repo_state_heuristic` | `answer_json_bridge` | 0.500 | 72 | traj, tx |
| [mcp_pytorch-gradient-noise-feat-001_weenko](../tasks/csb_sdlc_feature_sonnet_20260308_034803--mcp-remote-direct--mcp_pytorch-gradient-noise-feat-001_weenko--8b5a14eed5.html) | `passed` | 0.833 | `True` | `repo_state_heuristic` | `answer_json_bridge` | 0.296 | 27 | traj, tx |
| [mcp_strata-cds-tranche-feat-001_ukyl1q](../tasks/csb_sdlc_feature_sonnet_20260308_034803--mcp-remote-direct--mcp_strata-cds-tranche-feat-001_ukyl1q--f022c96421.html) | `passed` | 0.310 | `True` | `ir_checklist` | `answer_json_bridge` | 0.458 | 59 | traj, tx |
| [mcp_tensorrt-mxfp4-quant-feat-001_olucvz](../tasks/csb_sdlc_feature_sonnet_20260308_034803--mcp-remote-direct--mcp_tensorrt-mxfp4-quant-feat-001_olucvz--ea0cb748b7.html) | `passed` | 1.000 | `True` | `repo_state_heuristic` | `answer_json_bridge` | 0.534 | 73 | traj, tx |
| [mcp_terraform-compact-diff-fmt-feat-001_jwzg36](../tasks/csb_sdlc_feature_sonnet_20260308_034803--mcp-remote-direct--mcp_terraform-compact-diff-fmt-feat-001_jwzg36--5671fd4150.html) | `passed` | 1.000 | `True` | `repo_state_heuristic` | `answer_json_bridge` | 0.488 | 43 | traj, tx |
| [mcp_vscode-custom-fold-region-feat-001_39qgeb](../tasks/csb_sdlc_feature_sonnet_20260308_034803--mcp-remote-direct--mcp_vscode-custom-fold-region-feat-001_39qgeb--56be6ea590.html) | `passed` | 0.667 | `True` | `repo_state_heuristic` | `answer_json_bridge` | 0.409 | 44 | traj, tx |
