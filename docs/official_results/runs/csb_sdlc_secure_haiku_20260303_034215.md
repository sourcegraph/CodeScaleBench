# csb_sdlc_secure_haiku_20260303_034215

## baseline-local-direct

- Valid tasks: `4`
- Mean reward: `0.738`
- Pass rate: `1.000`
- Scorer families: `repo_state_heuristic (4)`
- Output contracts: `answer_json_bridge (4)`

| Task | Status | Reward | Passed | Scorer Family | Output Contract | MCP Ratio | Tool Calls | Trace |
|---|---|---:|---|---|---|---:|---:|---|
| [django-audit-trail-implement-001](../tasks/csb_sdlc_secure_haiku_20260303_034215--baseline-local-direct--django-audit-trail-implement-001--21373be4fd.html) | `passed` | 0.750 | `True` | `repo_state_heuristic` | `answer_json_bridge` | 0.000 | 39 | traj, tx |
| [django-cross-team-boundary-001](../tasks/csb_sdlc_secure_haiku_20260303_034215--baseline-local-direct--django-cross-team-boundary-001--5099b9e468.html) | `passed` | 0.500 | `True` | `repo_state_heuristic` | `answer_json_bridge` | 0.000 | 56 | traj, tx |
| [django-legacy-dep-vuln-001](../tasks/csb_sdlc_secure_haiku_20260303_034215--baseline-local-direct--django-legacy-dep-vuln-001--f1648a9eab.html) | `passed` | 1.000 | `True` | `repo_state_heuristic` | `answer_json_bridge` | 0.000 | 32 | traj, tx |
| [django-repo-scoped-access-001](../tasks/csb_sdlc_secure_haiku_20260303_034215--baseline-local-direct--django-repo-scoped-access-001--a6d1ce6d31.html) | `passed` | 0.700 | `True` | `repo_state_heuristic` | `answer_json_bridge` | 0.000 | 71 | traj, tx |

## mcp-remote-direct

- Valid tasks: `4`
- Mean reward: `0.688`
- Pass rate: `1.000`
- Scorer families: `repo_state_heuristic (4)`
- Output contracts: `answer_json_bridge (4)`

| Task | Status | Reward | Passed | Scorer Family | Output Contract | MCP Ratio | Tool Calls | Trace |
|---|---|---:|---|---|---|---:|---:|---|
| [mcp_django-audit-trail-implement-001_vnpld0](../tasks/csb_sdlc_secure_haiku_20260303_034215--mcp-remote-direct--mcp_django-audit-trail-implement-001_vnpld0--0036601ec8.html) | `passed` | 0.550 | `True` | `repo_state_heuristic` | `answer_json_bridge` | 0.236 | 123 | traj, tx |
| [mcp_django-cross-team-boundary-001_kmm7u4](../tasks/csb_sdlc_secure_haiku_20260303_034215--mcp-remote-direct--mcp_django-cross-team-boundary-001_kmm7u4--c7daaa0044.html) | `passed` | 0.500 | `True` | `repo_state_heuristic` | `answer_json_bridge` | 0.153 | 85 | traj, tx |
| [mcp_django-legacy-dep-vuln-001_ey2oju](../tasks/csb_sdlc_secure_haiku_20260303_034215--mcp-remote-direct--mcp_django-legacy-dep-vuln-001_ey2oju--07f8522790.html) | `passed` | 1.000 | `True` | `repo_state_heuristic` | `answer_json_bridge` | 0.170 | 53 | traj, tx |
| [mcp_django-repo-scoped-access-001_ln2iim](../tasks/csb_sdlc_secure_haiku_20260303_034215--mcp-remote-direct--mcp_django-repo-scoped-access-001_ln2iim--0d7ea42d3e.html) | `passed` | 0.700 | `True` | `repo_state_heuristic` | `answer_json_bridge` | 0.476 | 82 | traj, tx |
