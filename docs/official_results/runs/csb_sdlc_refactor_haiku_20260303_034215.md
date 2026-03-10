# csb_sdlc_refactor_haiku_20260303_034215

## baseline-local-direct

- Valid tasks: `6`
- Mean reward: `0.889`
- Pass rate: `1.000`
- Scorer families: `repo_state_heuristic (6)`
- Output contracts: `answer_json_bridge (6)`

| Task | Status | Reward | Passed | Scorer Family | Output Contract | MCP Ratio | Tool Calls | Trace |
|---|---|---:|---|---|---|---:|---:|---|
| [django-request-factory-refac-001](../tasks/csb_sdlc_refactor_haiku_20260303_034215--baseline-local-direct--django-request-factory-refac-001--e03cf9b69f.html) | `passed` | 0.833 | `True` | `repo_state_heuristic` | `answer_json_bridge` | 0.000 | 58 | traj, tx |
| [envoy-listener-manager-refac-001](../tasks/csb_sdlc_refactor_haiku_20260303_034215--baseline-local-direct--envoy-listener-manager-refac-001--f2452bf8e7.html) | `passed` | 0.833 | `True` | `repo_state_heuristic` | `answer_json_bridge` | 0.000 | 45 | traj, tx |
| [istio-discovery-server-refac-001](../tasks/csb_sdlc_refactor_haiku_20260303_034215--baseline-local-direct--istio-discovery-server-refac-001--4b9fcff025.html) | `passed` | 1.000 | `True` | `repo_state_heuristic` | `answer_json_bridge` | 0.000 | 23 | traj, tx |
| [kubernetes-scheduler-profile-refac-001](../tasks/csb_sdlc_refactor_haiku_20260303_034215--baseline-local-direct--kubernetes-scheduler-profile-refac-001--c635105e6f.html) | `passed` | 1.000 | `True` | `repo_state_heuristic` | `answer_json_bridge` | 0.000 | 86 | traj, tx |
| [numpy-array-dispatch-refac-001](../tasks/csb_sdlc_refactor_haiku_20260303_034215--baseline-local-direct--numpy-array-dispatch-refac-001--19118abb0f.html) | `passed` | 1.000 | `True` | `repo_state_heuristic` | `answer_json_bridge` | 0.000 | 59 | traj, tx |
| [pandas-index-engine-refac-001](../tasks/csb_sdlc_refactor_haiku_20260303_034215--baseline-local-direct--pandas-index-engine-refac-001--3998a09897.html) | `passed` | 0.667 | `True` | `repo_state_heuristic` | `answer_json_bridge` | 0.000 | 85 | traj, tx |

## mcp-remote-direct

- Valid tasks: `6`
- Mean reward: `0.694`
- Pass rate: `0.833`
- Scorer families: `repo_state_heuristic (6)`
- Output contracts: `answer_json_bridge (6)`

| Task | Status | Reward | Passed | Scorer Family | Output Contract | MCP Ratio | Tool Calls | Trace |
|---|---|---:|---|---|---|---:|---:|---|
| [mcp_numpy-array-dispatch-refac-001_rntjb9](../tasks/csb_sdlc_refactor_haiku_20260303_034215--mcp-remote-direct--mcp_numpy-array-dispatch-refac-001_rntjb9--645ba3a695.html) | `failed` | 0.000 | `False` | `repo_state_heuristic` | `answer_json_bridge` | 0.140 | 57 | traj, tx |
| [mcp_django-request-factory-refac-001_cajocy](../tasks/csb_sdlc_refactor_haiku_20260303_034215--mcp-remote-direct--mcp_django-request-factory-refac-001_cajocy--e0f9bba33e.html) | `passed` | 0.667 | `True` | `repo_state_heuristic` | `answer_json_bridge` | 0.125 | 88 | traj, tx |
| [mcp_envoy-listener-manager-refac-001_teyjyl](../tasks/csb_sdlc_refactor_haiku_20260303_034215--mcp-remote-direct--mcp_envoy-listener-manager-refac-001_teyjyl--e27dbed358.html) | `passed` | 0.833 | `True` | `repo_state_heuristic` | `answer_json_bridge` | 0.381 | 105 | traj, tx |
| [mcp_istio-discovery-server-refac-001_aly3us](../tasks/csb_sdlc_refactor_haiku_20260303_034215--mcp-remote-direct--mcp_istio-discovery-server-refac-001_aly3us--96bf28fc0d.html) | `passed` | 1.000 | `True` | `repo_state_heuristic` | `answer_json_bridge` | 0.239 | 117 | traj, tx |
| [mcp_kubernetes-scheduler-profile-refac-001_m3lzee](../tasks/csb_sdlc_refactor_haiku_20260303_034215--mcp-remote-direct--mcp_kubernetes-scheduler-profile-refac-001_m3lzee--5557479399.html) | `passed` | 1.000 | `True` | `repo_state_heuristic` | `answer_json_bridge` | 0.135 | 52 | traj, tx |
| [mcp_pandas-index-engine-refac-001_0jgrin](../tasks/csb_sdlc_refactor_haiku_20260303_034215--mcp-remote-direct--mcp_pandas-index-engine-refac-001_0jgrin--7b374896c9.html) | `passed` | 0.667 | `True` | `repo_state_heuristic` | `answer_json_bridge` | 0.333 | 54 | traj, tx |
