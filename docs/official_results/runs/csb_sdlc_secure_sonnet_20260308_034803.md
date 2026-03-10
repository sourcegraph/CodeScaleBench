# csb_sdlc_secure_sonnet_20260308_034803

## baseline-local-direct

- Valid tasks: `10`
- Mean reward: `0.792`
- Pass rate: `1.000`
- Scorer families: `repo_state_heuristic (7), ir_checklist (2), checklist (1)`
- Output contracts: `answer_json_bridge (10)`

| Task | Status | Reward | Passed | Scorer Family | Output Contract | MCP Ratio | Tool Calls | Trace |
|---|---|---:|---|---|---|---:|---:|---|
| [curl-cve-triage-001](../tasks/csb_sdlc_secure_sonnet_20260308_034803--baseline-local-direct--curl-cve-triage-001--dd5cbefbea.html) | `passed` | 0.940 | `True` | `checklist` | `answer_json_bridge` | 0.000 | 6 | traj, tx |
| [django-audit-trail-implement-001](../tasks/csb_sdlc_secure_sonnet_20260308_034803--baseline-local-direct--django-audit-trail-implement-001--e3d31e4178.html) | `passed` | 1.000 | `True` | `repo_state_heuristic` | `answer_json_bridge` | 0.000 | 50 | traj, tx |
| [django-cross-team-boundary-001](../tasks/csb_sdlc_secure_sonnet_20260308_034803--baseline-local-direct--django-cross-team-boundary-001--f4b2e6adca.html) | `passed` | 1.000 | `True` | `repo_state_heuristic` | `answer_json_bridge` | 0.000 | 49 | traj, tx |
| [django-legacy-dep-vuln-001](../tasks/csb_sdlc_secure_sonnet_20260308_034803--baseline-local-direct--django-legacy-dep-vuln-001--94c53ae7cd.html) | `passed` | 1.000 | `True` | `repo_state_heuristic` | `answer_json_bridge` | 0.000 | 14 | traj, tx |
| [django-repo-scoped-access-001](../tasks/csb_sdlc_secure_sonnet_20260308_034803--baseline-local-direct--django-repo-scoped-access-001--805fc4e5e7.html) | `passed` | 0.700 | `True` | `repo_state_heuristic` | `answer_json_bridge` | 0.000 | 70 | traj, tx |
| [django-role-based-access-001](../tasks/csb_sdlc_secure_sonnet_20260308_034803--baseline-local-direct--django-role-based-access-001--b3e5a07555.html) | `passed` | 1.000 | `True` | `repo_state_heuristic` | `answer_json_bridge` | 0.000 | 67 | traj, tx |
| [flipt-degraded-context-fix-001](../tasks/csb_sdlc_secure_sonnet_20260308_034803--baseline-local-direct--flipt-degraded-context-fix-001--f864c6b415.html) | `passed` | 0.250 | `True` | `repo_state_heuristic` | `answer_json_bridge` | 0.000 | 112 | traj, tx |
| [flipt-repo-scoped-access-001](../tasks/csb_sdlc_secure_sonnet_20260308_034803--baseline-local-direct--flipt-repo-scoped-access-001--b9b4506c79.html) | `passed` | 0.500 | `True` | `repo_state_heuristic` | `answer_json_bridge` | 0.000 | 16 | traj, tx |
| [k8s-rbac-auth-audit-001](../tasks/csb_sdlc_secure_sonnet_20260308_034803--baseline-local-direct--k8s-rbac-auth-audit-001--6677c1b956.html) | `passed` | 0.730 | `True` | `ir_checklist` | `answer_json_bridge` | 0.000 | 33 | traj, tx |
| [kafka-sasl-auth-audit-001](../tasks/csb_sdlc_secure_sonnet_20260308_034803--baseline-local-direct--kafka-sasl-auth-audit-001--869fe725b2.html) | `passed` | 0.800 | `True` | `ir_checklist` | `answer_json_bridge` | 0.000 | 30 | traj, tx |

## mcp-remote-direct

- Valid tasks: `12`
- Mean reward: `0.749`
- Pass rate: `1.000`
- Scorer families: `repo_state_heuristic (9), ir_checklist (2), checklist (1)`
- Output contracts: `answer_json_bridge (12)`

| Task | Status | Reward | Passed | Scorer Family | Output Contract | MCP Ratio | Tool Calls | Trace |
|---|---|---:|---|---|---|---:|---:|---|
| [mcp_ceph-rgw-auth-secure-001_gjvlon](../tasks/csb_sdlc_secure_sonnet_20260308_034803--mcp-remote-direct--mcp_ceph-rgw-auth-secure-001_gjvlon--b84578406c.html) | `passed` | 1.000 | `True` | `repo_state_heuristic` | `answer_json_bridge` | 0.846 | 26 | traj, tx |
| [mcp_curl-cve-triage-001_bcsa9g](../tasks/csb_sdlc_secure_sonnet_20260308_034803--mcp-remote-direct--mcp_curl-cve-triage-001_bcsa9g--7840053559.html) | `passed` | 0.940 | `True` | `checklist` | `answer_json_bridge` | 0.700 | 10 | traj, tx |
| [mcp_django-audit-trail-implement-001_bzc38r](../tasks/csb_sdlc_secure_sonnet_20260308_034803--mcp-remote-direct--mcp_django-audit-trail-implement-001_bzc38r--b4b2d3ea88.html) | `passed` | 0.750 | `True` | `repo_state_heuristic` | `answer_json_bridge` | 0.544 | 57 | traj, tx |
| [mcp_django-cross-team-boundary-001_sp3qrj](../tasks/csb_sdlc_secure_sonnet_20260308_034803--mcp-remote-direct--mcp_django-cross-team-boundary-001_sp3qrj--d00e097dea.html) | `passed` | 0.500 | `True` | `repo_state_heuristic` | `answer_json_bridge` | 0.450 | 80 | traj, tx |
| [mcp_django-legacy-dep-vuln-001_p6sc64](../tasks/csb_sdlc_secure_sonnet_20260308_034803--mcp-remote-direct--mcp_django-legacy-dep-vuln-001_p6sc64--72a3709ef8.html) | `passed` | 0.750 | `True` | `repo_state_heuristic` | `answer_json_bridge` | 0.350 | 20 | traj, tx |
| [mcp_django-repo-scoped-access-001_apxwao](../tasks/csb_sdlc_secure_sonnet_20260308_034803--mcp-remote-direct--mcp_django-repo-scoped-access-001_apxwao--c87385bce3.html) | `passed` | 0.500 | `True` | `repo_state_heuristic` | `answer_json_bridge` | 0.368 | 68 | traj, tx |
| [mcp_django-role-based-access-001_3it4em](../tasks/csb_sdlc_secure_sonnet_20260308_034803--mcp-remote-direct--mcp_django-role-based-access-001_3it4em--5da40cafd3.html) | `passed` | 1.000 | `True` | `repo_state_heuristic` | `answer_json_bridge` | 0.337 | 83 | traj, tx |
| [mcp_flipt-degraded-context-fix-001_8qcqdk](../tasks/csb_sdlc_secure_sonnet_20260308_034803--mcp-remote-direct--mcp_flipt-degraded-context-fix-001_8qcqdk--ced4e2128c.html) | `passed` | 0.800 | `True` | `repo_state_heuristic` | `answer_json_bridge` | 0.312 | 32 | traj, tx |
| [mcp_flipt-repo-scoped-access-001_aljvmh](../tasks/csb_sdlc_secure_sonnet_20260308_034803--mcp-remote-direct--mcp_flipt-repo-scoped-access-001_aljvmh--33c7967b27.html) | `passed` | 0.250 | `True` | `repo_state_heuristic` | `answer_json_bridge` | 0.152 | 33 | traj, tx |
| [mcp_k8s-rbac-auth-audit-001_cxdopk](../tasks/csb_sdlc_secure_sonnet_20260308_034803--mcp-remote-direct--mcp_k8s-rbac-auth-audit-001_cxdopk--83b751defa.html) | `passed` | 0.750 | `True` | `ir_checklist` | `answer_json_bridge` | 0.923 | 39 | traj, tx |
| [mcp_kafka-sasl-auth-audit-001_ghzmvf](../tasks/csb_sdlc_secure_sonnet_20260308_034803--mcp-remote-direct--mcp_kafka-sasl-auth-audit-001_ghzmvf--e4548546d6.html) | `passed` | 0.750 | `True` | `ir_checklist` | `answer_json_bridge` | 0.900 | 30 | traj, tx |
| [mcp_typescript-type-narrowing-secure-001_0b8mpw](../tasks/csb_sdlc_secure_sonnet_20260308_034803--mcp-remote-direct--mcp_typescript-type-narrowing-secure-001_0b8mpw--78fd5017b9.html) | `passed` | 1.000 | `True` | `repo_state_heuristic` | `answer_json_bridge` | 0.894 | 47 | traj, tx |
