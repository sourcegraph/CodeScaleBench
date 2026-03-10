# csb_sdlc_secure_haiku_20260303_141005

## baseline-local-direct

- Valid tasks: `6`
- Mean reward: `0.857`
- Pass rate: `1.000`
- Scorer families: `repo_state_heuristic (5), checklist (1)`
- Output contracts: `answer_json_bridge (6)`

| Task | Status | Reward | Passed | Scorer Family | Output Contract | MCP Ratio | Tool Calls | Trace |
|---|---|---:|---|---|---|---:|---:|---|
| [curl-cve-triage-001](../tasks/csb_sdlc_secure_haiku_20260303_141005--baseline-local-direct--curl-cve-triage-001--594b8d9b17.html) | `passed` | 0.940 | `True` | `checklist` | `answer_json_bridge` | 0.000 | 4 | traj, tx |
| [django-cross-team-boundary-001](../tasks/csb_sdlc_secure_haiku_20260303_141005--baseline-local-direct--django-cross-team-boundary-001--cb151f26c0.html) | `passed` | 0.700 | `True` | `repo_state_heuristic` | `answer_json_bridge` | 0.000 | 61 | traj, tx |
| [django-legacy-dep-vuln-001](../tasks/csb_sdlc_secure_haiku_20260303_141005--baseline-local-direct--django-legacy-dep-vuln-001--c3688a4c2a.html) | `passed` | 1.000 | `True` | `repo_state_heuristic` | `answer_json_bridge` | 0.000 | 36 | traj, tx |
| [django-repo-scoped-access-001](../tasks/csb_sdlc_secure_haiku_20260303_141005--baseline-local-direct--django-repo-scoped-access-001--bb2d85c21a.html) | `passed` | 0.700 | `True` | `repo_state_heuristic` | `answer_json_bridge` | 0.000 | 54 | traj, tx |
| [django-role-based-access-001](../tasks/csb_sdlc_secure_haiku_20260303_141005--baseline-local-direct--django-role-based-access-001--18ba9d9bc4.html) | `passed` | 0.800 | `True` | `repo_state_heuristic` | `answer_json_bridge` | 0.000 | 104 | traj, tx |
| [django-sensitive-file-exclusion-001](../tasks/csb_sdlc_secure_haiku_20260303_141005--baseline-local-direct--django-sensitive-file-exclusion-001--4e6abc856d.html) | `passed` | 1.000 | `True` | `repo_state_heuristic` | `answer_json_bridge` | 0.000 | 94 | traj, tx |
