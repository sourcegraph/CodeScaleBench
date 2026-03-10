# csb_sdlc_design_haiku_20260228_025547

## baseline-local-direct

- Valid tasks: `9`
- Mean reward: `0.569`
- Pass rate: `1.000`
- Scorer families: `unknown (4), repo_state_heuristic (3), ir_checklist (2)`
- Output contracts: `unknown (4), answer_json_native (3), answer_json_bridge (2)`

| Task | Status | Reward | Passed | Scorer Family | Output Contract | MCP Ratio | Tool Calls | Trace |
|---|---|---:|---|---|---|---:|---:|---|
| [django-orm-query-arch-001](../tasks/csb_sdlc_design_haiku_20260228_025547--baseline-local-direct--django-orm-query-arch-001--7f75ae76ef.html) | `passed` | 0.460 | `True` | `ir_checklist` | `answer_json_bridge` | 0.000 | 32 | traj, tx |
| [django-pre-validate-signal-design-001](../tasks/csb_sdlc_design_haiku_20260228_025547--baseline-local-direct--django-pre-validate-signal-design-001--3b7e888c72.html) | `passed` | 0.450 | `True` | `repo_state_heuristic` | `answer_json_native` | 0.000 | 98 | traj, tx |
| [django-rate-limit-design-001](../tasks/csb_sdlc_design_haiku_20260228_025547--baseline-local-direct--django-rate-limit-design-001--b68dcc93e2.html) | `passed` | 0.050 | `True` | `repo_state_heuristic` | `answer_json_native` | 0.000 | 75 | traj, tx |
| [envoy-routeconfig-dep-chain-001](../tasks/csb_sdlc_design_haiku_20260228_025547--baseline-local-direct--envoy-routeconfig-dep-chain-001--e47e251079.html) | `passed` | 1.000 | `True` | `-` | `-` | 0.000 | 12 | traj, tx |
| [envoy-stream-aggregated-sym-001](../tasks/csb_sdlc_design_haiku_20260228_025547--baseline-local-direct--envoy-stream-aggregated-sym-001--a18dad8b88.html) | `passed` | 0.740 | `True` | `-` | `-` | 0.000 | 42 | traj, tx |
| [flipt-protobuf-metadata-design-001](../tasks/csb_sdlc_design_haiku_20260228_025547--baseline-local-direct--flipt-protobuf-metadata-design-001--fd9e1ee65b.html) | `passed` | 0.480 | `True` | `repo_state_heuristic` | `answer_json_native` | 0.000 | 77 | traj, tx |
| [flipt-transitive-deps-001](../tasks/csb_sdlc_design_haiku_20260228_025547--baseline-local-direct--flipt-transitive-deps-001--12258c1abe.html) | `passed` | 0.533 | `True` | `-` | `-` | 0.000 | 39 | traj, tx |
| [k8s-typemeta-dep-chain-001](../tasks/csb_sdlc_design_haiku_20260228_025547--baseline-local-direct--k8s-typemeta-dep-chain-001--2957ce94b8.html) | `passed` | 0.670 | `True` | `-` | `-` | 0.000 | 19 | traj, tx |
| [postgres-query-exec-arch-001](../tasks/csb_sdlc_design_haiku_20260228_025547--baseline-local-direct--postgres-query-exec-arch-001--e7080153b0.html) | `passed` | 0.740 | `True` | `ir_checklist` | `answer_json_bridge` | 0.000 | 57 | traj, tx |

## mcp-remote-direct

- Valid tasks: `13`
- Mean reward: `0.751`
- Pass rate: `1.000`
- Scorer families: `unknown (8), repo_state_heuristic (3), ir_checklist (2)`
- Output contracts: `unknown (8), answer_json_native (3), answer_json_bridge (2)`

| Task | Status | Reward | Passed | Scorer Family | Output Contract | MCP Ratio | Tool Calls | Trace |
|---|---|---:|---|---|---|---:|---:|---|
| [mcp_django-modeladmin-impact-001_1Q2fNL](../tasks/csb_sdlc_design_haiku_20260228_025547--mcp-remote-direct--mcp_django-modeladmin-impact-001_1Q2fNL--e664f78999.html) | `passed` | 1.000 | `True` | `-` | `-` | 0.929 | 28 | traj, tx |
| [mcp_django-orm-query-arch-001_6Ntzcs](../tasks/csb_sdlc_design_haiku_20260228_025547--mcp-remote-direct--mcp_django-orm-query-arch-001_6Ntzcs--9c95ce0b7d.html) | `passed` | 0.880 | `True` | `ir_checklist` | `answer_json_bridge` | 0.951 | 41 | traj, tx |
| [mcp_django-pre-validate-signal-design-001_oGZYof](../tasks/csb_sdlc_design_haiku_20260228_025547--mcp-remote-direct--mcp_django-pre-validate-signal-design-001_oGZYof--9dda440fc5.html) | `passed` | 0.900 | `True` | `repo_state_heuristic` | `answer_json_native` | 0.412 | 68 | traj, tx |
| [mcp_django-rate-limit-design-001_gfYegS](../tasks/csb_sdlc_design_haiku_20260228_025547--mcp-remote-direct--mcp_django-rate-limit-design-001_gfYegS--4fff428c1d.html) | `passed` | 0.900 | `True` | `repo_state_heuristic` | `answer_json_native` | 0.211 | 71 | traj, tx |
| [mcp_envoy-routeconfig-dep-chain-001_yTp2Rn](../tasks/csb_sdlc_design_haiku_20260228_025547--mcp-remote-direct--mcp_envoy-routeconfig-dep-chain-001_yTp2Rn--2407f5c505.html) | `passed` | 0.670 | `True` | `-` | `-` | 0.917 | 12 | traj, tx |
| [mcp_envoy-stream-aggregated-sym-001_RqIhtU](../tasks/csb_sdlc_design_haiku_20260228_025547--mcp-remote-direct--mcp_envoy-stream-aggregated-sym-001_RqIhtU--e62497f3e2.html) | `passed` | 0.670 | `True` | `-` | `-` | 0.956 | 45 | traj, tx |
| [mcp_flipt-protobuf-metadata-design-001_VTUIt4](../tasks/csb_sdlc_design_haiku_20260228_025547--mcp-remote-direct--mcp_flipt-protobuf-metadata-design-001_VTUIt4--9560e3dd96.html) | `passed` | 0.750 | `True` | `repo_state_heuristic` | `answer_json_native` | 0.333 | 66 | traj, tx |
| [mcp_flipt-transitive-deps-001_TV5FV0](../tasks/csb_sdlc_design_haiku_20260228_025547--mcp-remote-direct--mcp_flipt-transitive-deps-001_TV5FV0--c7c92f6603.html) | `passed` | 0.648 | `True` | `-` | `-` | 0.977 | 44 | traj, tx |
| [mcp_k8s-sharedinformer-sym-001_r1uWY5](../tasks/csb_sdlc_design_haiku_20260228_025547--mcp-remote-direct--mcp_k8s-sharedinformer-sym-001_r1uWY5--ea213b8e18.html) | `passed` | 0.710 | `True` | `-` | `-` | 0.977 | 44 | traj, tx |
| [mcp_k8s-typemeta-dep-chain-001_uTlaTc](../tasks/csb_sdlc_design_haiku_20260228_025547--mcp-remote-direct--mcp_k8s-typemeta-dep-chain-001_uTlaTc--574926ad55.html) | `passed` | 0.670 | `True` | `-` | `-` | 0.700 | 10 | traj, tx |
| [mcp_postgres-query-exec-arch-001_A0vfQ4](../tasks/csb_sdlc_design_haiku_20260228_025547--mcp-remote-direct--mcp_postgres-query-exec-arch-001_A0vfQ4--c400a3e2fa.html) | `passed` | 1.000 | `True` | `ir_checklist` | `answer_json_bridge` | 0.878 | 41 | traj, tx |
| [mcp_quantlib-barrier-pricing-arch-001_4uwsVP](../tasks/csb_sdlc_design_haiku_20260228_025547--mcp-remote-direct--mcp_quantlib-barrier-pricing-arch-001_4uwsVP--b266525fa1.html) | `passed` | 0.890 | `True` | `-` | `-` | 0.962 | 26 | traj, tx |
| [mcp_terraform-provider-iface-sym-001_JJ1WXA](../tasks/csb_sdlc_design_haiku_20260228_025547--mcp-remote-direct--mcp_terraform-provider-iface-sym-001_JJ1WXA--35f6cec5e6.html) | `passed` | 0.080 | `True` | `-` | `-` | 0.971 | 34 | traj, tx |
