# csb_sdlc_secure_haiku_022326

## baseline-local-direct

- Valid tasks: `10`
- Mean reward: `0.616`
- Pass rate: `0.900`
- Scorer families: `repo_state_heuristic (6), unknown (2), checklist (1), ir_checklist (1)`
- Output contracts: `answer_json_bridge (8), unknown (2)`

| Task | Status | Reward | Passed | Scorer Family | Output Contract | MCP Ratio | Tool Calls | Trace |
|---|---|---:|---|---|---|---:|---:|---|
| [grpcurl-transitive-vuln-001](../tasks/csb_sdlc_secure_haiku_022326--baseline--grpcurl-transitive-vuln-001--f747d8e844.html) | `failed` | 0.000 | `False` | `-` | `-` | 0.000 | 37 | traj, tx |
| [curl-cve-triage-001](../tasks/csb_sdlc_secure_haiku_022326--baseline--curl-cve-triage-001--558070d671.html) | `passed` | 0.940 | `True` | `checklist` | `answer_json_bridge` | 0.000 | 27 | traj, tx |
| [curl-vuln-reachability-001](../tasks/csb_sdlc_secure_haiku_022326--baseline--curl-vuln-reachability-001--9f85f12dce.html) | `passed` | 0.910 | `True` | `-` | `-` | 0.000 | 50 | traj, tx |
| [django-audit-trail-implement-001](../tasks/csb_sdlc_secure_haiku_022326--baseline--django-audit-trail-implement-001--18ed89a786.html) | `passed` | 0.550 | `True` | `repo_state_heuristic` | `answer_json_bridge` | 0.000 | 73 | traj, tx |
| [django-cross-team-boundary-001](../tasks/csb_sdlc_secure_haiku_022326--baseline--django-cross-team-boundary-001--73e1e9ed7e.html) | `passed` | 0.300 | `True` | `repo_state_heuristic` | `answer_json_bridge` | 0.000 | 83 | traj, tx |
| [django-legacy-dep-vuln-001](../tasks/csb_sdlc_secure_haiku_022326--baseline--django-legacy-dep-vuln-001--abeac65887.html) | `passed` | 0.900 | `True` | `repo_state_heuristic` | `answer_json_bridge` | 0.000 | 31 | traj, tx |
| [django-repo-scoped-access-001](../tasks/csb_sdlc_secure_haiku_022326--baseline--django-repo-scoped-access-001--7cbd4187cf.html) | `passed` | 0.500 | `True` | `repo_state_heuristic` | `answer_json_bridge` | 0.000 | 44 | traj, tx |
| [flipt-degraded-context-fix-001](../tasks/csb_sdlc_secure_haiku_022326--baseline--flipt-degraded-context-fix-001--847d63c25c.html) | `passed` | 0.600 | `True` | `repo_state_heuristic` | `answer_json_bridge` | 0.000 | 54 | traj, tx |
| [flipt-repo-scoped-access-001](../tasks/csb_sdlc_secure_haiku_022326--baseline--flipt-repo-scoped-access-001--61d62fda35.html) | `passed` | 0.600 | `True` | `repo_state_heuristic` | `answer_json_bridge` | 0.000 | 26 | traj, tx |
| [kafka-sasl-auth-audit-001](../tasks/csb_sdlc_secure_haiku_022326--baseline--kafka-sasl-auth-audit-001--4a1d1fefa6.html) | `passed` | 0.860 | `True` | `ir_checklist` | `answer_json_bridge` | 0.000 | 57 | traj, tx |

## mcp-remote-direct

- Valid tasks: `18`
- Mean reward: `0.705`
- Pass rate: `1.000`
- Scorer families: `unknown (10), repo_state_heuristic (6), checklist (1), ir_checklist (1)`
- Output contracts: `unknown (10), answer_json_bridge (8)`

| Task | Status | Reward | Passed | Scorer Family | Output Contract | MCP Ratio | Tool Calls | Trace |
|---|---|---:|---|---|---|---:|---:|---|
| [sgonly_curl-cve-triage-001](../tasks/csb_sdlc_secure_haiku_022326--mcp--sgonly_curl-cve-triage-001--5134269ca5.html) | `passed` | 0.940 | `True` | `checklist` | `answer_json_bridge` | 0.889 | 9 | traj, tx |
| [sgonly_curl-vuln-reachability-001](../tasks/csb_sdlc_secure_haiku_022326--mcp--sgonly_curl-vuln-reachability-001--a625388dbb.html) | `passed` | 0.850 | `True` | `-` | `-` | 0.960 | 25 | traj, tx |
| [sgonly_django-audit-trail-implement-001](../tasks/csb_sdlc_secure_haiku_022326--mcp--sgonly_django-audit-trail-implement-001--3cafa01b4f.html) | `passed` | 0.550 | `True` | `repo_state_heuristic` | `answer_json_bridge` | 0.351 | 57 | traj, tx |
| [sgonly_django-cross-team-boundary-001](../tasks/csb_sdlc_secure_haiku_022326--mcp--sgonly_django-cross-team-boundary-001--084acedae5.html) | `passed` | 0.500 | `True` | `repo_state_heuristic` | `answer_json_bridge` | 0.232 | 56 | traj, tx |
| [sgonly_django-csrf-session-audit-001](../tasks/csb_sdlc_secure_haiku_022326--mcp--sgonly_django-csrf-session-audit-001--8304333ba3.html) | `passed` | 0.760 | `True` | `-` | `-` | 0.947 | 19 | traj, tx |
| [sgonly_django-legacy-dep-vuln-001](../tasks/csb_sdlc_secure_haiku_022326--mcp--sgonly_django-legacy-dep-vuln-001--e12946110c.html) | `passed` | 0.650 | `True` | `repo_state_heuristic` | `answer_json_bridge` | 0.227 | 44 | traj, tx |
| [sgonly_django-policy-enforcement-001](../tasks/csb_sdlc_secure_haiku_022326--mcp--sgonly_django-policy-enforcement-001--bc21924b99.html) | `passed` | 0.750 | `True` | `-` | `-` | 0.206 | 63 | traj, tx |
| [sgonly_django-repo-scoped-access-001](../tasks/csb_sdlc_secure_haiku_022326--mcp--sgonly_django-repo-scoped-access-001--f640fc10a3.html) | `passed` | 0.700 | `True` | `repo_state_heuristic` | `answer_json_bridge` | 0.561 | 98 | traj, tx |
| [sgonly_envoy-cve-triage-001](../tasks/csb_sdlc_secure_haiku_022326--mcp--sgonly_envoy-cve-triage-001--82b7700404.html) | `passed` | 1.000 | `True` | `-` | `-` | 0.963 | 27 | traj, tx |
| [sgonly_envoy-vuln-reachability-001](../tasks/csb_sdlc_secure_haiku_022326--mcp--sgonly_envoy-vuln-reachability-001--1cde9fa146.html) | `passed` | 0.560 | `True` | `-` | `-` | 0.923 | 26 | traj, tx |
| [sgonly_flipt-degraded-context-fix-001](../tasks/csb_sdlc_secure_haiku_022326--mcp--sgonly_flipt-degraded-context-fix-001--03de5d4b10.html) | `passed` | 0.250 | `True` | `repo_state_heuristic` | `answer_json_bridge` | 0.333 | 36 | traj, tx |
| [sgonly_flipt-repo-scoped-access-001](../tasks/csb_sdlc_secure_haiku_022326--mcp--sgonly_flipt-repo-scoped-access-001--338ebf11a6.html) | `passed` | 0.600 | `True` | `repo_state_heuristic` | `answer_json_bridge` | 0.184 | 38 | traj, tx |
| [sgonly_golang-net-cve-triage-001](../tasks/csb_sdlc_secure_haiku_022326--mcp--sgonly_golang-net-cve-triage-001--2e1f9b7930.html) | `passed` | 0.800 | `True` | `-` | `-` | 0.852 | 27 | traj, tx |
| [sgonly_grpcurl-transitive-vuln-001](../tasks/csb_sdlc_secure_haiku_022326--mcp--sgonly_grpcurl-transitive-vuln-001--74acbf8b76.html) | `passed` | 0.670 | `True` | `-` | `-` | 0.952 | 21 | traj, tx |
| [sgonly_kafka-sasl-auth-audit-001](../tasks/csb_sdlc_secure_haiku_022326--mcp--sgonly_kafka-sasl-auth-audit-001--77b92ede34.html) | `passed` | 0.760 | `True` | `ir_checklist` | `answer_json_bridge` | 0.960 | 25 | traj, tx |
| [sgonly_kafka-vuln-reachability-001](../tasks/csb_sdlc_secure_haiku_022326--mcp--sgonly_kafka-vuln-reachability-001--738d786f66.html) | `passed` | 0.920 | `True` | `-` | `-` | 0.667 | 18 | traj, tx |
| [sgonly_postgres-client-auth-audit-001](../tasks/csb_sdlc_secure_haiku_022326--mcp--sgonly_postgres-client-auth-audit-001--52e7805e37.html) | `passed` | 0.770 | `True` | `-` | `-` | 0.974 | 38 | traj, tx |
| [sgonly_wish-transitive-vuln-001](../tasks/csb_sdlc_secure_haiku_022326--mcp--sgonly_wish-transitive-vuln-001--5ce290436f.html) | `passed` | 0.660 | `True` | `-` | `-` | 0.938 | 16 | traj, tx |
