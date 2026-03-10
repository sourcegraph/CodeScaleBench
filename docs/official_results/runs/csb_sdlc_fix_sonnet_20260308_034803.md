# csb_sdlc_fix_sonnet_20260308_034803

## baseline-local-direct

- Valid tasks: `13`
- Mean reward: `0.547`
- Pass rate: `0.692`
- Scorer families: `diff_similarity (7), ir_checklist (3), test_ratio (2), repo_state_heuristic (1)`
- Output contracts: `answer_json_bridge (13)`

| Task | Status | Reward | Passed | Scorer Family | Output Contract | MCP Ratio | Tool Calls | Trace |
|---|---|---:|---|---|---|---:|---:|---|
| [element-web-unread-indicators-diverge-fix-001](../tasks/csb_sdlc_fix_sonnet_20260308_034803--baseline-local-direct--element-web-unread-indicators-diverge-fix-001--ec0801f11b.html) | `failed` | 0.000 | `False` | `test_ratio` | `answer_json_bridge` | 0.000 | 22 | traj, tx |
| [pytorch-cudnn-version-fix-001](../tasks/csb_sdlc_fix_sonnet_20260308_034803--baseline-local-direct--pytorch-cudnn-version-fix-001--3e8e4822c2.html) | `failed` | 0.000 | `False` | `diff_similarity` | `answer_json_bridge` | 0.000 | 32 | traj, tx |
| [pytorch-release-210-fix-001](../tasks/csb_sdlc_fix_sonnet_20260308_034803--baseline-local-direct--pytorch-release-210-fix-001--4b74d6a463.html) | `failed` | 0.000 | `False` | `diff_similarity` | `answer_json_bridge` | 0.000 | 262 | traj, tx |
| [pytorch-tracer-graph-cleanup-fix-001](../tasks/csb_sdlc_fix_sonnet_20260308_034803--baseline-local-direct--pytorch-tracer-graph-cleanup-fix-001--761bacca8b.html) | `failed` | 0.000 | `False` | `diff_similarity` | `answer_json_bridge` | 0.000 | 139 | traj, tx |
| [django-modelchoice-fk-fix-001](../tasks/csb_sdlc_fix_sonnet_20260308_034803--baseline-local-direct--django-modelchoice-fk-fix-001--a4ab7daabf.html) | `passed` | 0.800 | `True` | `repo_state_heuristic` | `answer_json_bridge` | 0.000 | 101 | traj, tx |
| [django-select-for-update-fix-001](../tasks/csb_sdlc_fix_sonnet_20260308_034803--baseline-local-direct--django-select-for-update-fix-001--eb9fa27581.html) | `passed` | 0.720 | `True` | `ir_checklist` | `answer_json_bridge` | 0.000 | 16 | traj, tx |
| [envoy-dfp-host-leak-fix-001](../tasks/csb_sdlc_fix_sonnet_20260308_034803--baseline-local-direct--envoy-dfp-host-leak-fix-001--a96bcfb4e4.html) | `passed` | 0.788 | `True` | `diff_similarity` | `answer_json_bridge` | 0.000 | 22 | traj, tx |
| [envoy-udp-proxy-cds-fix-001](../tasks/csb_sdlc_fix_sonnet_20260308_034803--baseline-local-direct--envoy-udp-proxy-cds-fix-001--dc4e3f6676.html) | `passed` | 0.745 | `True` | `diff_similarity` | `answer_json_bridge` | 0.000 | 15 | traj, tx |
| [k8s-dra-scheduler-event-fix-001](../tasks/csb_sdlc_fix_sonnet_20260308_034803--baseline-local-direct--k8s-dra-scheduler-event-fix-001--1e7375ed8b.html) | `passed` | 0.750 | `True` | `ir_checklist` | `answer_json_bridge` | 0.000 | 14 | traj, tx |
| [kafka-producer-bufpool-fix-001](../tasks/csb_sdlc_fix_sonnet_20260308_034803--baseline-local-direct--kafka-producer-bufpool-fix-001--5efb03e4d6.html) | `passed` | 0.770 | `True` | `ir_checklist` | `answer_json_bridge` | 0.000 | 36 | traj, tx |
| [pytorch-relu-gelu-fusion-fix-001](../tasks/csb_sdlc_fix_sonnet_20260308_034803--baseline-local-direct--pytorch-relu-gelu-fusion-fix-001--20b33315da.html) | `passed` | 0.613 | `True` | `diff_similarity` | `answer_json_bridge` | 0.000 | 92 | traj, tx |
| [teleport-users-can-delete-fix-001](../tasks/csb_sdlc_fix_sonnet_20260308_034803--baseline-local-direct--teleport-users-can-delete-fix-001--6549d98886.html) | `passed` | 1.000 | `True` | `test_ratio` | `answer_json_bridge` | 0.000 | 16 | traj, tx |
| [terraform-plan-null-unknown-fix-001](../tasks/csb_sdlc_fix_sonnet_20260308_034803--baseline-local-direct--terraform-plan-null-unknown-fix-001--63f456efa5.html) | `passed` | 0.919 | `True` | `diff_similarity` | `answer_json_bridge` | 0.000 | 72 | traj, tx |

## mcp-remote-direct

- Valid tasks: `13`
- Mean reward: `0.491`
- Pass rate: `0.615`
- Scorer families: `diff_similarity (7), ir_checklist (3), test_ratio (2), repo_state_heuristic (1)`
- Output contracts: `answer_json_bridge (13)`

| Task | Status | Reward | Passed | Scorer Family | Output Contract | MCP Ratio | Tool Calls | Trace |
|---|---|---:|---|---|---|---:|---:|---|
| [mcp_django-modelchoice-fk-fix-001_yxxg0b](../tasks/csb_sdlc_fix_sonnet_20260308_034803--mcp-remote-direct--mcp_django-modelchoice-fk-fix-001_yxxg0b--5338e90d95.html) | `failed` | 0.000 | `False` | `repo_state_heuristic` | `answer_json_bridge` | 0.437 | 103 | traj, tx |
| [mcp_element-web-roomheaderbuttons-can-crash-fix-001_rd3iip](../tasks/csb_sdlc_fix_sonnet_20260308_034803--mcp-remote-direct--mcp_element-web-roomheaderbuttons-can-crash-fix-001_rd3iip--cdf37843bd.html) | `failed` | 0.000 | `False` | `test_ratio` | `answer_json_bridge` | 0.154 | 234 | traj, tx |
| [mcp_pytorch-cudnn-version-fix-001_gefviz](../tasks/csb_sdlc_fix_sonnet_20260308_034803--mcp-remote-direct--mcp_pytorch-cudnn-version-fix-001_gefviz--1cee0c48e2.html) | `failed` | 0.000 | `False` | `diff_similarity` | `answer_json_bridge` | 0.614 | 70 | traj, tx |
| [mcp_pytorch-dynamo-keyerror-fix-001_oia6hf](../tasks/csb_sdlc_fix_sonnet_20260308_034803--mcp-remote-direct--mcp_pytorch-dynamo-keyerror-fix-001_oia6hf--6b0e47dff3.html) | `failed` | 0.000 | `False` | `diff_similarity` | `answer_json_bridge` | 0.754 | 57 | traj, tx |
| [mcp_pytorch-tracer-graph-cleanup-fix-001_kkbykk](../tasks/csb_sdlc_fix_sonnet_20260308_034803--mcp-remote-direct--mcp_pytorch-tracer-graph-cleanup-fix-001_kkbykk--2b937bfef6.html) | `failed` | 0.000 | `False` | `diff_similarity` | `answer_json_bridge` | 0.479 | 236 | traj, tx |
| [mcp_django-select-for-update-fix-001_1ggnwt](../tasks/csb_sdlc_fix_sonnet_20260308_034803--mcp-remote-direct--mcp_django-select-for-update-fix-001_1ggnwt--bc85f63088.html) | `passed` | 0.720 | `True` | `ir_checklist` | `answer_json_bridge` | 0.742 | 31 | traj, tx |
| [mcp_envoy-dfp-host-leak-fix-001_q8cb7k](../tasks/csb_sdlc_fix_sonnet_20260308_034803--mcp-remote-direct--mcp_envoy-dfp-host-leak-fix-001_q8cb7k--9551ef4b56.html) | `passed` | 0.818 | `True` | `diff_similarity` | `answer_json_bridge` | 0.595 | 42 | traj, tx |
| [mcp_envoy-udp-proxy-cds-fix-001_vziwb4](../tasks/csb_sdlc_fix_sonnet_20260308_034803--mcp-remote-direct--mcp_envoy-udp-proxy-cds-fix-001_vziwb4--73b68bb0ff.html) | `passed` | 0.706 | `True` | `diff_similarity` | `answer_json_bridge` | 0.379 | 66 | traj, tx |
| [mcp_k8s-dra-scheduler-event-fix-001_aaudip](../tasks/csb_sdlc_fix_sonnet_20260308_034803--mcp-remote-direct--mcp_k8s-dra-scheduler-event-fix-001_aaudip--1e7107e75e.html) | `passed` | 0.760 | `True` | `ir_checklist` | `answer_json_bridge` | 0.895 | 38 | traj, tx |
| [mcp_kafka-producer-bufpool-fix-001_eh8lze](../tasks/csb_sdlc_fix_sonnet_20260308_034803--mcp-remote-direct--mcp_kafka-producer-bufpool-fix-001_eh8lze--e6164029a6.html) | `passed` | 0.720 | `True` | `ir_checklist` | `answer_json_bridge` | 0.788 | 33 | traj, tx |
| [mcp_pytorch-relu-gelu-fusion-fix-001_j507mh](../tasks/csb_sdlc_fix_sonnet_20260308_034803--mcp-remote-direct--mcp_pytorch-relu-gelu-fusion-fix-001_j507mh--098e037883.html) | `passed` | 0.698 | `True` | `diff_similarity` | `answer_json_bridge` | 0.418 | 91 | traj, tx |
| [mcp_teleport-users-can-delete-fix-001_l9z57r](../tasks/csb_sdlc_fix_sonnet_20260308_034803--mcp-remote-direct--mcp_teleport-users-can-delete-fix-001_l9z57r--0f23f940d0.html) | `passed` | 1.000 | `True` | `test_ratio` | `answer_json_bridge` | 0.155 | 71 | traj, tx |
| [mcp_terraform-plan-null-unknown-fix-001_zyp7xk](../tasks/csb_sdlc_fix_sonnet_20260308_034803--mcp-remote-direct--mcp_terraform-plan-null-unknown-fix-001_zyp7xk--0852ee89ff.html) | `passed` | 0.955 | `True` | `diff_similarity` | `answer_json_bridge` | 0.236 | 89 | traj, tx |
