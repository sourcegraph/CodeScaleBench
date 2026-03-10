# csb_sdlc_secure_haiku_20260307_001927

## baseline-local-direct

- Valid tasks: `1`
- Mean reward: `0.800`
- Pass rate: `1.000`
- Scorer families: `ir_checklist (1)`
- Output contracts: `answer_json_bridge (1)`

| Task | Status | Reward | Passed | Scorer Family | Output Contract | MCP Ratio | Tool Calls | Trace |
|---|---|---:|---|---|---|---:|---:|---|
| [k8s-rbac-auth-audit-001](../tasks/csb_sdlc_secure_haiku_20260307_001927--baseline-local-direct--k8s-rbac-auth-audit-001--f77a6fbf84.html) | `passed` | 0.800 | `True` | `ir_checklist` | `answer_json_bridge` | 0.000 | 29 | traj, tx |

## mcp-remote-direct

- Valid tasks: `3`
- Mean reward: `0.937`
- Pass rate: `1.000`
- Scorer families: `repo_state_heuristic (2), ir_checklist (1)`
- Output contracts: `answer_json_bridge (3)`

| Task | Status | Reward | Passed | Scorer Family | Output Contract | MCP Ratio | Tool Calls | Trace |
|---|---|---:|---|---|---|---:|---:|---|
| [mcp_ceph-rgw-auth-secure-001_vaxvpc](../tasks/csb_sdlc_secure_haiku_20260307_001927--mcp-remote-direct--mcp_ceph-rgw-auth-secure-001_vaxvpc--3ef6962a70.html) | `passed` | 1.000 | `True` | `repo_state_heuristic` | `answer_json_bridge` | 0.947 | 19 | traj, tx |
| [mcp_k8s-rbac-auth-audit-001_nzjrmi](../tasks/csb_sdlc_secure_haiku_20260307_001927--mcp-remote-direct--mcp_k8s-rbac-auth-audit-001_nzjrmi--e343638dbb.html) | `passed` | 0.810 | `True` | `ir_checklist` | `answer_json_bridge` | 0.958 | 24 | traj, tx |
| [mcp_typescript-type-narrowing-secure-001_htjwqy](../tasks/csb_sdlc_secure_haiku_20260307_001927--mcp-remote-direct--mcp_typescript-type-narrowing-secure-001_htjwqy--c5a8468156.html) | `passed` | 1.000 | `True` | `repo_state_heuristic` | `answer_json_bridge` | 0.898 | 98 | traj, tx |
