# csb_sdlc_secure_haiku_20260302_224010

## baseline-local-direct

- Valid tasks: `5`
- Mean reward: `0.676`
- Pass rate: `1.000`
- Scorer families: `repo_state_heuristic (2), unknown (2), ir_checklist (1)`
- Output contracts: `answer_json_bridge (3), unknown (2)`

| Task | Status | Reward | Passed | Scorer Family | Output Contract | MCP Ratio | Tool Calls | Trace |
|---|---|---:|---|---|---|---:|---:|---|
| [curl-vuln-reachability-001](../tasks/csb_sdlc_secure_haiku_20260302_224010--baseline-local-direct--curl-vuln-reachability-001--7ad293c8fd.html) | `passed` | 0.850 | `True` | `-` | `-` | 0.000 | 24 | traj, tx |
| [flipt-degraded-context-fix-001](../tasks/csb_sdlc_secure_haiku_20260302_224010--baseline-local-direct--flipt-degraded-context-fix-001--1f1481f3de.html) | `passed` | 0.250 | `True` | `repo_state_heuristic` | `answer_json_bridge` | 0.000 | 116 | traj, tx |
| [flipt-repo-scoped-access-001](../tasks/csb_sdlc_secure_haiku_20260302_224010--baseline-local-direct--flipt-repo-scoped-access-001--48a463c07a.html) | `passed` | 0.850 | `None` | `repo_state_heuristic` | `answer_json_bridge` | 0.000 | 36 | traj, tx |
| [grpcurl-transitive-vuln-001](../tasks/csb_sdlc_secure_haiku_20260302_224010--baseline-local-direct--grpcurl-transitive-vuln-001--15c7685b79.html) | `passed` | 0.670 | `True` | `-` | `-` | 0.000 | 36 | traj, tx |
| [kafka-sasl-auth-audit-001](../tasks/csb_sdlc_secure_haiku_20260302_224010--baseline-local-direct--kafka-sasl-auth-audit-001--3595ea3c21.html) | `passed` | 0.760 | `True` | `ir_checklist` | `answer_json_bridge` | 0.000 | 30 | traj, tx |

## mcp-remote-direct

- Valid tasks: `4`
- Mean reward: `0.627`
- Pass rate: `1.000`
- Scorer families: `checklist (1), ir_checklist (1), repo_state_heuristic (1), unknown (1)`
- Output contracts: `answer_json_bridge (3), unknown (1)`

| Task | Status | Reward | Passed | Scorer Family | Output Contract | MCP Ratio | Tool Calls | Trace |
|---|---|---:|---|---|---|---:|---:|---|
| [mcp_curl-cve-triage-001_x1ddf6](../tasks/csb_sdlc_secure_haiku_20260302_224010--mcp-remote-direct--mcp_curl-cve-triage-001_x1ddf6--3f98de937c.html) | `passed` | 0.940 | `None` | `checklist` | `answer_json_bridge` | 0.818 | 11 | traj, tx |
| [mcp_flipt-repo-scoped-access-001_ledgw0](../tasks/csb_sdlc_secure_haiku_20260302_224010--mcp-remote-direct--mcp_flipt-repo-scoped-access-001_ledgw0--7b75d6a347.html) | `passed` | 0.500 | `None` | `repo_state_heuristic` | `answer_json_bridge` | 0.190 | 42 | traj, tx |
| [mcp_grpcurl-transitive-vuln-001_rzkvha](../tasks/csb_sdlc_secure_haiku_20260302_224010--mcp-remote-direct--mcp_grpcurl-transitive-vuln-001_rzkvha--19473bd155.html) | `passed` | 0.670 | `None` | `-` | `-` | 0.952 | 21 | traj, tx |
| [mcp_kafka-sasl-auth-audit-001_6xs9ox](../tasks/csb_sdlc_secure_haiku_20260302_224010--mcp-remote-direct--mcp_kafka-sasl-auth-audit-001_6xs9ox--6a4b80c256.html) | `passed` | 0.400 | `None` | `ir_checklist` | `answer_json_bridge` | 0.960 | 25 | traj, tx |
