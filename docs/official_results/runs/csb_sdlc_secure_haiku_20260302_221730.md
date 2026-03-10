# csb_sdlc_secure_haiku_20260302_221730

## baseline-local-direct

- Valid tasks: `10`
- Mean reward: `0.499`
- Pass rate: `0.800`
- Scorer families: `repo_state_heuristic (6), unknown (2), checklist (1), ir_checklist (1)`
- Output contracts: `answer_json_bridge (8), unknown (2)`

| Task | Status | Reward | Passed | Scorer Family | Output Contract | MCP Ratio | Tool Calls | Trace |
|---|---|---:|---|---|---|---:|---:|---|
| [curl-vuln-reachability-001](../tasks/csb_sdlc_secure_haiku_20260302_221730--baseline-local-direct--curl-vuln-reachability-001--3ae2ea47e4.html) | `failed` | 0.000 | `None` | `-` | `-` | - | - | traj, tx |
| [grpcurl-transitive-vuln-001](../tasks/csb_sdlc_secure_haiku_20260302_221730--baseline-local-direct--grpcurl-transitive-vuln-001--617f0cedcb.html) | `failed` | 0.000 | `None` | `-` | `-` | - | - | traj, tx |
| [curl-cve-triage-001](../tasks/csb_sdlc_secure_haiku_20260302_221730--baseline-local-direct--curl-cve-triage-001--4d3f5a9157.html) | `passed` | 0.940 | `None` | `checklist` | `answer_json_bridge` | 0.000 | 9 | traj, tx |
| [django-audit-trail-implement-001](../tasks/csb_sdlc_secure_haiku_20260302_221730--baseline-local-direct--django-audit-trail-implement-001--1dc603eb57.html) | `passed` | 0.800 | `None` | `repo_state_heuristic` | `answer_json_bridge` | 0.000 | 67 | traj, tx |
| [django-cross-team-boundary-001](../tasks/csb_sdlc_secure_haiku_20260302_221730--baseline-local-direct--django-cross-team-boundary-001--f8967023a4.html) | `passed` | 0.300 | `None` | `repo_state_heuristic` | `answer_json_bridge` | 0.000 | 52 | traj, tx |
| [django-repo-scoped-access-001](../tasks/csb_sdlc_secure_haiku_20260302_221730--baseline-local-direct--django-repo-scoped-access-001--3dc3b9ad26.html) | `passed` | 1.000 | `None` | `repo_state_heuristic` | `answer_json_bridge` | 0.000 | 55 | traj, tx |
| [django-role-based-access-001](../tasks/csb_sdlc_secure_haiku_20260302_221730--baseline-local-direct--django-role-based-access-001--492c782000.html) | `passed` | 0.400 | `None` | `repo_state_heuristic` | `answer_json_bridge` | 0.000 | 94 | traj, tx |
| [flipt-degraded-context-fix-001](../tasks/csb_sdlc_secure_haiku_20260302_221730--baseline-local-direct--flipt-degraded-context-fix-001--cbd4c752f4.html) | `passed` | 0.250 | `None` | `repo_state_heuristic` | `answer_json_bridge` | 0.000 | 107 | traj, tx |
| [flipt-repo-scoped-access-001](../tasks/csb_sdlc_secure_haiku_20260302_221730--baseline-local-direct--flipt-repo-scoped-access-001--86b514ae36.html) | `passed` | 0.500 | `None` | `repo_state_heuristic` | `answer_json_bridge` | 0.000 | 32 | traj, tx |
| [kafka-sasl-auth-audit-001](../tasks/csb_sdlc_secure_haiku_20260302_221730--baseline-local-direct--kafka-sasl-auth-audit-001--b58a581de6.html) | `passed` | 0.800 | `None` | `ir_checklist` | `answer_json_bridge` | 0.000 | 30 | traj, tx |

## mcp-remote-direct

- Valid tasks: `8`
- Mean reward: `0.805`
- Pass rate: `1.000`
- Scorer families: `repo_state_heuristic (5), unknown (2), checklist (1)`
- Output contracts: `answer_json_bridge (6), unknown (2)`

| Task | Status | Reward | Passed | Scorer Family | Output Contract | MCP Ratio | Tool Calls | Trace |
|---|---|---:|---|---|---|---:|---:|---|
| [mcp_curl-cve-triage-001_nkn2ep](../tasks/csb_sdlc_secure_haiku_20260302_221730--mcp-remote-direct--mcp_curl-cve-triage-001_nkn2ep--7bfe0003d4.html) | `passed` | 0.940 | `None` | `checklist` | `answer_json_bridge` | 0.833 | 6 | traj, tx |
| [mcp_curl-vuln-reachability-001_bzcvms](../tasks/csb_sdlc_secure_haiku_20260302_221730--mcp-remote-direct--mcp_curl-vuln-reachability-001_bzcvms--7553f336a8.html) | `passed` | 0.710 | `None` | `-` | `-` | 0.892 | 37 | traj, tx |
| [mcp_django-cross-team-boundary-001_oxflgu](../tasks/csb_sdlc_secure_haiku_20260302_221730--mcp-remote-direct--mcp_django-cross-team-boundary-001_oxflgu--f9cacccdb6.html) | `passed` | 0.800 | `None` | `repo_state_heuristic` | `answer_json_bridge` | 0.244 | 78 | traj, tx |
| [mcp_django-legacy-dep-vuln-001_kgnuuj](../tasks/csb_sdlc_secure_haiku_20260302_221730--mcp-remote-direct--mcp_django-legacy-dep-vuln-001_kgnuuj--5d661f00ff.html) | `passed` | 1.000 | `None` | `repo_state_heuristic` | `answer_json_bridge` | 0.262 | 42 | traj, tx |
| [mcp_django-role-based-access-001_3ryxq7](../tasks/csb_sdlc_secure_haiku_20260302_221730--mcp-remote-direct--mcp_django-role-based-access-001_3ryxq7--135938d958.html) | `passed` | 0.900 | `None` | `repo_state_heuristic` | `answer_json_bridge` | 0.323 | 93 | traj, tx |
| [mcp_django-sensitive-file-exclusion-001_c7krv8](../tasks/csb_sdlc_secure_haiku_20260302_221730--mcp-remote-direct--mcp_django-sensitive-file-exclusion-001_c7krv8--5fcc8dd1ef.html) | `passed` | 1.000 | `None` | `repo_state_heuristic` | `answer_json_bridge` | 0.178 | 101 | traj, tx |
| [mcp_flipt-repo-scoped-access-001_prpacb](../tasks/csb_sdlc_secure_haiku_20260302_221730--mcp-remote-direct--mcp_flipt-repo-scoped-access-001_prpacb--a97732e06d.html) | `passed` | 0.500 | `None` | `repo_state_heuristic` | `answer_json_bridge` | 0.212 | 52 | traj, tx |
| [mcp_grpcurl-transitive-vuln-001_6gpxwc](../tasks/csb_sdlc_secure_haiku_20260302_221730--mcp-remote-direct--mcp_grpcurl-transitive-vuln-001_6gpxwc--5fb0f017df.html) | `passed` | 0.590 | `None` | `-` | `-` | 0.952 | 21 | traj, tx |
