# csb_sdlc_build_haiku_20260227_123839

## baseline-local-direct

- Valid tasks: `8`
- Mean reward: `0.641`
- Pass rate: `1.000`
- Scorer families: `ir_checklist (6), repo_state_heuristic (1), unknown (1)`
- Output contracts: `answer_json_bridge (7), unknown (1)`

| Task | Status | Reward | Passed | Scorer Family | Output Contract | MCP Ratio | Tool Calls | Trace |
|---|---|---:|---|---|---|---:|---:|---|
| [camel-fix-protocol-feat-001](../tasks/csb_sdlc_build_haiku_20260227_123839--baseline-local-direct--camel-fix-protocol-feat-001--b8252e24cf.html) | `passed` | 0.220 | `None` | `ir_checklist` | `answer_json_bridge` | 0.000 | 68 | traj, tx |
| [flink-pricing-window-feat-001](../tasks/csb_sdlc_build_haiku_20260227_123839--baseline-local-direct--flink-pricing-window-feat-001--fae8f7db01.html) | `passed` | 0.480 | `None` | `ir_checklist` | `answer_json_bridge` | 0.000 | 38 | traj, tx |
| [k8s-noschedule-taint-feat-001](../tasks/csb_sdlc_build_haiku_20260227_123839--baseline-local-direct--k8s-noschedule-taint-feat-001--3f5fd55e5f.html) | `passed` | 0.700 | `None` | `repo_state_heuristic` | `answer_json_bridge` | 0.000 | 84 | traj, tx |
| [k8s-score-normalizer-refac-001](../tasks/csb_sdlc_build_haiku_20260227_123839--baseline-local-direct--k8s-score-normalizer-refac-001--1fe8efee43.html) | `passed` | 0.880 | `None` | `ir_checklist` | `answer_json_bridge` | 0.000 | 47 | traj, tx |
| [kafka-batch-accumulator-refac-001](../tasks/csb_sdlc_build_haiku_20260227_123839--baseline-local-direct--kafka-batch-accumulator-refac-001--c2ae35494c.html) | `passed` | 0.790 | `None` | `ir_checklist` | `answer_json_bridge` | 0.000 | 53 | traj, tx |
| [rust-subtype-relation-refac-001](../tasks/csb_sdlc_build_haiku_20260227_123839--baseline-local-direct--rust-subtype-relation-refac-001--e95226c9e9.html) | `passed` | 0.760 | `None` | `-` | `-` | 0.000 | 70 | traj, tx |
| [strata-cds-tranche-feat-001](../tasks/csb_sdlc_build_haiku_20260227_123839--baseline-local-direct--strata-cds-tranche-feat-001--a13c9b6ded.html) | `passed` | 0.590 | `None` | `ir_checklist` | `answer_json_bridge` | 0.000 | 46 | traj, tx |
| [strata-fx-european-refac-001](../tasks/csb_sdlc_build_haiku_20260227_123839--baseline-local-direct--strata-fx-european-refac-001--4c6780797b.html) | `passed` | 0.710 | `None` | `ir_checklist` | `answer_json_bridge` | 0.000 | 36 | traj, tx |

## mcp-remote-direct

- Valid tasks: `7`
- Mean reward: `0.571`
- Pass rate: `1.000`
- Scorer families: `ir_checklist (5), repo_state_heuristic (1), unknown (1)`
- Output contracts: `answer_json_bridge (6), unknown (1)`

| Task | Status | Reward | Passed | Scorer Family | Output Contract | MCP Ratio | Tool Calls | Trace |
|---|---|---:|---|---|---|---:|---:|---|
| [mcp_camel-fix-protocol-feat-001_fWsOdb](../tasks/csb_sdlc_build_haiku_20260227_123839--mcp-remote-direct--mcp_camel-fix-protocol-feat-001_fWsOdb--6fe106ea51.html) | `passed` | 0.340 | `None` | `ir_checklist` | `answer_json_bridge` | 0.239 | 88 | traj, tx |
| [mcp_flink-pricing-window-feat-001_qlRfCm](../tasks/csb_sdlc_build_haiku_20260227_123839--mcp-remote-direct--mcp_flink-pricing-window-feat-001_qlRfCm--a132121b12.html) | `passed` | 0.510 | `None` | `ir_checklist` | `answer_json_bridge` | 0.393 | 61 | traj, tx |
| [mcp_k8s-noschedule-taint-feat-001_A0pm5V](../tasks/csb_sdlc_build_haiku_20260227_123839--mcp-remote-direct--mcp_k8s-noschedule-taint-feat-001_A0pm5V--4fe1bd2167.html) | `passed` | 0.500 | `None` | `repo_state_heuristic` | `answer_json_bridge` | 0.248 | 101 | traj, tx |
| [mcp_k8s-score-normalizer-refac-001_uBneDv](../tasks/csb_sdlc_build_haiku_20260227_123839--mcp-remote-direct--mcp_k8s-score-normalizer-refac-001_uBneDv--30fb8ada52.html) | `passed` | 0.800 | `None` | `ir_checklist` | `answer_json_bridge` | 0.081 | 86 | traj, tx |
| [mcp_kafka-batch-accumulator-refac-001_03s0bF](../tasks/csb_sdlc_build_haiku_20260227_123839--mcp-remote-direct--mcp_kafka-batch-accumulator-refac-001_03s0bF--ec666b9b5f.html) | `passed` | 0.680 | `None` | `ir_checklist` | `answer_json_bridge` | 0.307 | 75 | traj, tx |
| [mcp_rust-subtype-relation-refac-001_cwbXwY](../tasks/csb_sdlc_build_haiku_20260227_123839--mcp-remote-direct--mcp_rust-subtype-relation-refac-001_cwbXwY--4a09937ac7.html) | `passed` | 0.890 | `None` | `-` | `-` | 0.151 | 93 | traj, tx |
| [mcp_strata-cds-tranche-feat-001_ink1qb](../tasks/csb_sdlc_build_haiku_20260227_123839--mcp-remote-direct--mcp_strata-cds-tranche-feat-001_ink1qb--6b1579a173.html) | `passed` | 0.280 | `None` | `ir_checklist` | `answer_json_bridge` | 0.500 | 28 | traj, tx |
