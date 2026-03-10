# csb_sdlc_secure_haiku_20260303_142451

## baseline-local-direct

- Valid tasks: `4`
- Mean reward: `0.910`
- Pass rate: `1.000`
- Scorer families: `repo_state_heuristic (3), checklist (1)`
- Output contracts: `answer_json_bridge (4)`

| Task | Status | Reward | Passed | Scorer Family | Output Contract | MCP Ratio | Tool Calls | Trace |
|---|---|---:|---|---|---|---:|---:|---|
| [curl-cve-triage-001](../tasks/csb_sdlc_secure_haiku_20260303_142451--baseline-local-direct--curl-cve-triage-001--59b2eeca11.html) | `passed` | 0.940 | `True` | `checklist` | `answer_json_bridge` | 0.000 | 7 | traj, tx |
| [django-legacy-dep-vuln-001](../tasks/csb_sdlc_secure_haiku_20260303_142451--baseline-local-direct--django-legacy-dep-vuln-001--c154565f2d.html) | `passed` | 1.000 | `True` | `repo_state_heuristic` | `answer_json_bridge` | 0.000 | 29 | traj, tx |
| [django-role-based-access-001](../tasks/csb_sdlc_secure_haiku_20260303_142451--baseline-local-direct--django-role-based-access-001--0d1cb619b1.html) | `passed` | 0.700 | `True` | `repo_state_heuristic` | `answer_json_bridge` | 0.000 | 86 | traj, tx |
| [django-sensitive-file-exclusion-001](../tasks/csb_sdlc_secure_haiku_20260303_142451--baseline-local-direct--django-sensitive-file-exclusion-001--b1c4b5d0ae.html) | `passed` | 1.000 | `True` | `repo_state_heuristic` | `answer_json_bridge` | 0.000 | 76 | traj, tx |
