# csb_sdlc_design_haiku_20260302_221730

## baseline-local-direct

- Valid tasks: `10`
- Mean reward: `0.811`
- Pass rate: `1.000`
- Scorer families: `ir_checklist (6), unknown (2), repo_state_heuristic (1), semantic_similarity (1)`
- Output contracts: `answer_json_bridge (6), unknown (2), answer_json_native (1), repo_state (1)`

| Task | Status | Reward | Passed | Scorer Family | Output Contract | MCP Ratio | Tool Calls | Trace |
|---|---|---:|---|---|---|---:|---:|---|
| [camel-routing-arch-001](../tasks/csb_sdlc_design_haiku_20260302_221730--baseline-local-direct--camel-routing-arch-001--a1ff06289a.html) | `passed` | 0.880 | `None` | `ir_checklist` | `answer_json_bridge` | 0.000 | 47 | traj, tx |
| [django-orm-query-arch-001](../tasks/csb_sdlc_design_haiku_20260302_221730--baseline-local-direct--django-orm-query-arch-001--0d1f7f306b.html) | `passed` | 0.830 | `None` | `ir_checklist` | `answer_json_bridge` | 0.000 | 58 | traj, tx |
| [django-rate-limit-design-001](../tasks/csb_sdlc_design_haiku_20260302_221730--baseline-local-direct--django-rate-limit-design-001--3ab36eb9ff.html) | `passed` | 1.000 | `None` | `repo_state_heuristic` | `answer_json_native` | 0.000 | 35 | traj, tx |
| [envoy-routeconfig-dep-chain-001](../tasks/csb_sdlc_design_haiku_20260302_221730--baseline-local-direct--envoy-routeconfig-dep-chain-001--d865570d1b.html) | `passed` | 1.000 | `None` | `-` | `-` | - | - | traj |
| [etcd-grpc-api-upgrade-001](../tasks/csb_sdlc_design_haiku_20260302_221730--baseline-local-direct--etcd-grpc-api-upgrade-001--f4e3a59bf0.html) | `passed` | 0.771 | `None` | `semantic_similarity` | `repo_state` | 0.000 | 70 | traj, tx |
| [flink-checkpoint-arch-001](../tasks/csb_sdlc_design_haiku_20260302_221730--baseline-local-direct--flink-checkpoint-arch-001--89328f77fa.html) | `passed` | 0.400 | `None` | `ir_checklist` | `answer_json_bridge` | 0.000 | 39 | traj, tx |
| [flipt-transitive-deps-001](../tasks/csb_sdlc_design_haiku_20260302_221730--baseline-local-direct--flipt-transitive-deps-001--cc7e6c30e9.html) | `passed` | 0.678 | `None` | `-` | `-` | 0.000 | 29 | traj, tx |
| [k8s-crd-lifecycle-arch-001](../tasks/csb_sdlc_design_haiku_20260302_221730--baseline-local-direct--k8s-crd-lifecycle-arch-001--2d046c2eff.html) | `passed` | 0.690 | `None` | `ir_checklist` | `answer_json_bridge` | 0.000 | 49 | traj, tx |
| [kafka-flink-streaming-arch-001](../tasks/csb_sdlc_design_haiku_20260302_221730--baseline-local-direct--kafka-flink-streaming-arch-001--390c577910.html) | `passed` | 0.950 | `None` | `ir_checklist` | `answer_json_bridge` | 0.000 | 31 | traj, tx |
| [postgres-query-exec-arch-001](../tasks/csb_sdlc_design_haiku_20260302_221730--baseline-local-direct--postgres-query-exec-arch-001--e68130d208.html) | `passed` | 0.910 | `None` | `ir_checklist` | `answer_json_bridge` | 0.000 | 56 | traj, tx |

## mcp-remote-direct

- Valid tasks: `9`
- Mean reward: `0.742`
- Pass rate: `1.000`
- Scorer families: `ir_checklist (4), unknown (3), repo_state_heuristic (2)`
- Output contracts: `answer_json_bridge (4), unknown (3), answer_json_native (2)`

| Task | Status | Reward | Passed | Scorer Family | Output Contract | MCP Ratio | Tool Calls | Trace |
|---|---|---:|---|---|---|---:|---:|---|
| [mcp_django-orm-query-arch-001_skuw7m](../tasks/csb_sdlc_design_haiku_20260302_221730--mcp-remote-direct--mcp_django-orm-query-arch-001_skuw7m--065206a869.html) | `passed` | 0.850 | `None` | `ir_checklist` | `answer_json_bridge` | 0.976 | 42 | traj, tx |
| [mcp_django-pre-validate-signal-design-001_qh0sd0](../tasks/csb_sdlc_design_haiku_20260302_221730--mcp-remote-direct--mcp_django-pre-validate-signal-design-001_qh0sd0--3bfa18ce72.html) | `passed` | 0.900 | `None` | `repo_state_heuristic` | `answer_json_native` | 0.479 | 48 | traj, tx |
| [mcp_envoy-routeconfig-dep-chain-001_zwi8mw](../tasks/csb_sdlc_design_haiku_20260302_221730--mcp-remote-direct--mcp_envoy-routeconfig-dep-chain-001_zwi8mw--358bb1864f.html) | `passed` | 0.670 | `None` | `-` | `-` | - | - | traj |
| [mcp_envoy-stream-aggregated-sym-001_eqnvzf](../tasks/csb_sdlc_design_haiku_20260302_221730--mcp-remote-direct--mcp_envoy-stream-aggregated-sym-001_eqnvzf--a15593e453.html) | `passed` | 0.530 | `None` | `-` | `-` | 0.955 | 44 | traj, tx |
| [mcp_flink-checkpoint-arch-001_re1v8p](../tasks/csb_sdlc_design_haiku_20260302_221730--mcp-remote-direct--mcp_flink-checkpoint-arch-001_re1v8p--9f650844c7.html) | `passed` | 0.700 | `None` | `ir_checklist` | `answer_json_bridge` | 0.970 | 33 | traj, tx |
| [mcp_flipt-protobuf-metadata-design-001_ugetfd](../tasks/csb_sdlc_design_haiku_20260302_221730--mcp-remote-direct--mcp_flipt-protobuf-metadata-design-001_ugetfd--60ee2aa4a3.html) | `passed` | 0.750 | `None` | `repo_state_heuristic` | `answer_json_native` | 0.343 | 67 | traj, tx |
| [mcp_k8s-crd-lifecycle-arch-001_1a1dlc](../tasks/csb_sdlc_design_haiku_20260302_221730--mcp-remote-direct--mcp_k8s-crd-lifecycle-arch-001_1a1dlc--3b5530e70a.html) | `passed` | 0.720 | `None` | `ir_checklist` | `answer_json_bridge` | 0.932 | 44 | traj, tx |
| [mcp_k8s-typemeta-dep-chain-001_axq0qp](../tasks/csb_sdlc_design_haiku_20260302_221730--mcp-remote-direct--mcp_k8s-typemeta-dep-chain-001_axq0qp--9dd1c05743.html) | `passed` | 0.670 | `None` | `-` | `-` | - | - | traj |
| [mcp_postgres-query-exec-arch-001_kvrxpy](../tasks/csb_sdlc_design_haiku_20260302_221730--mcp-remote-direct--mcp_postgres-query-exec-arch-001_kvrxpy--8c0eb11da5.html) | `passed` | 0.890 | `None` | `ir_checklist` | `answer_json_bridge` | 0.962 | 26 | traj, tx |
