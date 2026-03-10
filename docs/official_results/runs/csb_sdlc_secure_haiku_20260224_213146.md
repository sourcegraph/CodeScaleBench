# csb_sdlc_secure_haiku_20260224_213146

## baseline-local-direct

- Valid tasks: `2`
- Mean reward: `0.500`
- Pass rate: `1.000`
- Scorer families: `repo_state_heuristic (2)`
- Output contracts: `answer_json_bridge (2)`

| Task | Status | Reward | Passed | Scorer Family | Output Contract | MCP Ratio | Tool Calls | Trace |
|---|---|---:|---|---|---|---:|---:|---|
| [django-role-based-access-001](../tasks/csb_sdlc_secure_haiku_20260224_213146--baseline-local-direct--django-role-based-access-001--1deafca966.html) | `passed` | 0.200 | `True` | `repo_state_heuristic` | `answer_json_bridge` | 0.000 | 132 | traj, tx |
| [django-sensitive-file-exclusion-001](../tasks/csb_sdlc_secure_haiku_20260224_213146--baseline-local-direct--django-sensitive-file-exclusion-001--7547b5066e.html) | `passed` | 0.800 | `True` | `repo_state_heuristic` | `answer_json_bridge` | 0.000 | 86 | traj, tx |

## mcp-remote-direct

- Valid tasks: `2`
- Mean reward: `0.250`
- Pass rate: `0.500`
- Scorer families: `repo_state_heuristic (2)`
- Output contracts: `answer_json_bridge (2)`

| Task | Status | Reward | Passed | Scorer Family | Output Contract | MCP Ratio | Tool Calls | Trace |
|---|---|---:|---|---|---|---:|---:|---|
| [mcp_django-role-based-access-001_2ERzmK](../tasks/csb_sdlc_secure_haiku_20260224_213146--mcp-remote-direct--mcp_django-role-based-access-001_2ERzmK--e6d8b0898c.html) | `failed` | 0.000 | `False` | `repo_state_heuristic` | `answer_json_bridge` | 0.452 | 84 | traj, tx |
| [mcp_django-sensitive-file-exclusion-001_I216lD](../tasks/csb_sdlc_secure_haiku_20260224_213146--mcp-remote-direct--mcp_django-sensitive-file-exclusion-001_I216lD--4df1998acd.html) | `passed` | 0.500 | `True` | `repo_state_heuristic` | `answer_json_bridge` | 0.352 | 54 | traj, tx |
