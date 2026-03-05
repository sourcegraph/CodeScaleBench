# Official Results Browser

This bundle is generated from `runs/analysis/` and includes only valid scored tasks (`passed`/`failed` with numeric reward).

Generated: `2026-03-05T21:30:17.060820+00:00`

## Local Browse

```bash
python3 scripts/export_official_results.py --serve
```

Suite-level views are deduplicated to the latest row per `suite + config + task_name`.
Historical reruns/backfills remain available in `data/official_results.json` under `all_tasks`.

## Suite/Config Summary

| Suite | Config | Valid Tasks | Min Required | Mean Reward | Pass Rate | Coverage |
|---|---|---:|---:|---:|---:|---|
| [csb_org_compliance](suites/csb_org_compliance.md) | `baseline-local-artifact` | 18 | 54 | 0.247 | 0.889 | FLAG: below minimum |
| [csb_org_compliance](suites/csb_org_compliance.md) | `mcp-remote-artifact` | 54 | 54 | 0.295 | 0.889 | ok |
| [csb_org_crossorg](suites/csb_org_crossorg.md) | `baseline-local-artifact` | 15 | 45 | 0.196 | 0.667 | FLAG: below minimum |
| [csb_org_crossorg](suites/csb_org_crossorg.md) | `mcp-remote-artifact` | 45 | 45 | 0.200 | 0.667 | ok |
| [csb_org_crossrepo](suites/csb_org_crossrepo.md) | `baseline-local-artifact` | 14 | 42 | 0.312 | 1.000 | FLAG: below minimum |
| [csb_org_crossrepo](suites/csb_org_crossrepo.md) | `mcp-remote-artifact` | 42 | 42 | 0.285 | 0.976 | ok |
| [csb_org_crossrepo_tracing](suites/csb_org_crossrepo_tracing.md) | `baseline-local-artifact` | 22 | 62 | 0.351 | 0.727 | FLAG: below minimum |
| [csb_org_crossrepo_tracing](suites/csb_org_crossrepo_tracing.md) | `mcp-remote-artifact` | 62 | 62 | 0.356 | 0.758 | ok |
| [csb_org_domain](suites/csb_org_domain.md) | `baseline-local-artifact` | 20 | 60 | 0.351 | 0.950 | FLAG: below minimum |
| [csb_org_domain](suites/csb_org_domain.md) | `mcp-remote-artifact` | 60 | 60 | 0.338 | 0.900 | ok |
| [csb_org_incident](suites/csb_org_incident.md) | `baseline-local-artifact` | 20 | 58 | 0.502 | 0.900 | FLAG: below minimum |
| [csb_org_incident](suites/csb_org_incident.md) | `mcp-remote-artifact` | 58 | 58 | 0.569 | 0.948 | ok |
| [csb_org_migration](suites/csb_org_migration.md) | `baseline-local-artifact` | 26 | 77 | 0.325 | 0.846 | FLAG: below minimum |
| [csb_org_migration](suites/csb_org_migration.md) | `mcp-remote-artifact` | 77 | 77 | 0.419 | 0.831 | ok |
| [csb_org_onboarding](suites/csb_org_onboarding.md) | `baseline-local-artifact` | 28 | 81 | 0.718 | 0.929 | FLAG: below minimum |
| [csb_org_onboarding](suites/csb_org_onboarding.md) | `mcp-remote-artifact` | 81 | 81 | 0.752 | 0.951 | ok |
| [csb_org_org](suites/csb_org_org.md) | `baseline-local-artifact` | 15 | 45 | 0.423 | 1.000 | FLAG: below minimum |
| [csb_org_org](suites/csb_org_org.md) | `mcp-remote-artifact` | 45 | 45 | 0.460 | 0.978 | ok |
| [csb_org_platform](suites/csb_org_platform.md) | `baseline-local-artifact` | 18 | 54 | 0.281 | 0.833 | FLAG: below minimum |
| [csb_org_platform](suites/csb_org_platform.md) | `mcp-remote-artifact` | 54 | 54 | 0.267 | 0.963 | ok |
| [csb_org_security](suites/csb_org_security.md) | `baseline-local-artifact` | 24 | 59 | 0.473 | 0.875 | FLAG: below minimum |
| [csb_org_security](suites/csb_org_security.md) | `mcp-remote-artifact` | 59 | 59 | 0.577 | 1.000 | ok |
| [csb_sdlc_debug](suites/csb_sdlc_debug.md) | `baseline-local-direct` | 18 | 20 | 0.588 | 0.944 | FLAG: below minimum |
| [csb_sdlc_debug](suites/csb_sdlc_debug.md) | `mcp-remote-direct` | 36 | 20 | 0.470 | 0.806 | ok |
| [csb_sdlc_design](suites/csb_sdlc_design.md) | `baseline-local-direct` | 14 | 20 | 0.604 | 0.929 | FLAG: below minimum |
| [csb_sdlc_design](suites/csb_sdlc_design.md) | `mcp-remote-direct` | 23 | 20 | 0.751 | 1.000 | ok |
| [csb_sdlc_document](suites/csb_sdlc_document.md) | `baseline-local-direct` | 13 | 20 | 0.833 | 1.000 | FLAG: below minimum |
| [csb_sdlc_document](suites/csb_sdlc_document.md) | `mcp-remote-direct` | 26 | 20 | 0.843 | 1.000 | ok |
| [csb_sdlc_feature](suites/csb_sdlc_feature.md) | `baseline-local-direct` | 23 | 20 | 0.533 | 0.783 | ok |
| [csb_sdlc_feature](suites/csb_sdlc_feature.md) | `mcp-remote-direct` | 30 | 20 | 0.522 | 0.767 | ok |
| [csb_sdlc_fix](suites/csb_sdlc_fix.md) | `baseline-local-direct` | 27 | 25 | 0.515 | 0.667 | ok |
| [csb_sdlc_fix](suites/csb_sdlc_fix.md) | `mcp-remote-direct` | 72 | 25 | 0.574 | 0.736 | ok |
| [csb_sdlc_refactor](suites/csb_sdlc_refactor.md) | `baseline-local-direct` | 16 | 20 | 0.580 | 0.750 | FLAG: below minimum |
| [csb_sdlc_refactor](suites/csb_sdlc_refactor.md) | `mcp-remote-direct` | 16 | 20 | 0.683 | 0.875 | FLAG: below minimum |
| [csb_sdlc_secure](suites/csb_sdlc_secure.md) | `baseline-local-direct` | 12 | 20 | 0.668 | 1.000 | FLAG: below minimum |
| [csb_sdlc_secure](suites/csb_sdlc_secure.md) | `mcp-remote-direct` | 17 | 20 | 0.598 | 0.941 | FLAG: below minimum |
| [csb_sdlc_test](suites/csb_sdlc_test.md) | `baseline-local-direct` | 18 | 20 | 0.549 | 0.833 | FLAG: below minimum |
| [csb_sdlc_test](suites/csb_sdlc_test.md) | `mcp-remote-direct` | 41 | 20 | 0.552 | 0.878 | ok |
| [csb_sdlc_understand](suites/csb_sdlc_understand.md) | `baseline-local-direct` | 10 | 20 | 0.692 | 0.900 | FLAG: below minimum |
| [csb_sdlc_understand](suites/csb_sdlc_understand.md) | `mcp-remote-direct` | 12 | 20 | 0.782 | 1.000 | FLAG: below minimum |

<details>
<summary>Run/Config Summary</summary>


| Run | Suite | Config | Valid Tasks | Mean Reward | Pass Rate |
|---|---|---|---:|---:|---:|
| [csb_org/csb_org_compliance](runs/csb_org-csb_org_compliance.md) | `csb_org_compliance` | `baseline-local-artifact` | 54 | 0.280 | 0.889 |
| [csb_org/csb_org_compliance](runs/csb_org-csb_org_compliance.md) | `csb_org_compliance` | `mcp-remote-artifact` | 54 | 0.295 | 0.889 |
| [csb_org/csb_org_crossorg](runs/csb_org-csb_org_crossorg.md) | `csb_org_crossorg` | `baseline-local-artifact` | 45 | 0.175 | 0.667 |
| [csb_org/csb_org_crossorg](runs/csb_org-csb_org_crossorg.md) | `csb_org_crossorg` | `mcp-remote-artifact` | 45 | 0.200 | 0.667 |
| [csb_org/csb_org_crossrepo](runs/csb_org-csb_org_crossrepo.md) | `csb_org_crossrepo` | `baseline-local-artifact` | 42 | 0.309 | 1.000 |
| [csb_org/csb_org_crossrepo](runs/csb_org-csb_org_crossrepo.md) | `csb_org_crossrepo` | `mcp-remote-artifact` | 42 | 0.285 | 0.976 |
| [csb_org/csb_org_crossrepo_tracing](runs/csb_org-csb_org_crossrepo_tracing.md) | `csb_org_crossrepo_tracing` | `baseline-local-artifact` | 63 | 0.324 | 0.683 |
| [csb_org/csb_org_crossrepo_tracing](runs/csb_org-csb_org_crossrepo_tracing.md) | `csb_org_crossrepo_tracing` | `mcp-remote-artifact` | 62 | 0.356 | 0.758 |
| [csb_org/csb_org_domain](runs/csb_org-csb_org_domain.md) | `csb_org_domain` | `baseline-local-artifact` | 60 | 0.355 | 0.933 |
| [csb_org/csb_org_domain](runs/csb_org-csb_org_domain.md) | `csb_org_domain` | `mcp-remote-artifact` | 60 | 0.338 | 0.900 |
| [csb_org/csb_org_incident](runs/csb_org-csb_org_incident.md) | `csb_org_incident` | `baseline-local-artifact` | 58 | 0.487 | 0.862 |
| [csb_org/csb_org_incident](runs/csb_org-csb_org_incident.md) | `csb_org_incident` | `mcp-remote-artifact` | 58 | 0.569 | 0.948 |
| [csb_org/csb_org_migration](runs/csb_org-csb_org_migration.md) | `csb_org_migration` | `baseline-local-artifact` | 77 | 0.381 | 0.870 |
| [csb_org/csb_org_migration](runs/csb_org-csb_org_migration.md) | `csb_org_migration` | `mcp-remote-artifact` | 77 | 0.419 | 0.831 |
| [csb_org/csb_org_onboarding](runs/csb_org-csb_org_onboarding.md) | `csb_org_onboarding` | `baseline-local-artifact` | 81 | 0.737 | 0.926 |
| [csb_org/csb_org_onboarding](runs/csb_org-csb_org_onboarding.md) | `csb_org_onboarding` | `mcp-remote-artifact` | 81 | 0.752 | 0.951 |
| [csb_org/csb_org_org](runs/csb_org-csb_org_org.md) | `csb_org_org` | `baseline-local-artifact` | 45 | 0.403 | 0.956 |
| [csb_org/csb_org_org](runs/csb_org-csb_org_org.md) | `csb_org_org` | `mcp-remote-artifact` | 45 | 0.460 | 0.978 |
| [csb_org/csb_org_platform](runs/csb_org-csb_org_platform.md) | `csb_org_platform` | `baseline-local-artifact` | 54 | 0.295 | 0.926 |
| [csb_org/csb_org_platform](runs/csb_org-csb_org_platform.md) | `csb_org_platform` | `mcp-remote-artifact` | 54 | 0.267 | 0.963 |
| [csb_org/csb_org_security](runs/csb_org-csb_org_security.md) | `csb_org_security` | `baseline-local-artifact` | 60 | 0.504 | 0.883 |
| [csb_org/csb_org_security](runs/csb_org-csb_org_security.md) | `csb_org_security` | `mcp-remote-artifact` | 59 | 0.577 | 1.000 |
| [csb_sdlc/csb_sdlc_debug](runs/csb_sdlc-csb_sdlc_debug.md) | `csb_sdlc_debug` | `baseline-local-direct` | 36 | 0.544 | 0.944 |
| [csb_sdlc/csb_sdlc_debug](runs/csb_sdlc-csb_sdlc_debug.md) | `csb_sdlc_debug` | `mcp-remote-direct` | 36 | 0.470 | 0.806 |
| [csb_sdlc/csb_sdlc_design](runs/csb_sdlc-csb_sdlc_design.md) | `csb_sdlc_design` | `baseline-local-direct` | 23 | 0.690 | 0.957 |
| [csb_sdlc/csb_sdlc_design](runs/csb_sdlc-csb_sdlc_design.md) | `csb_sdlc_design` | `mcp-remote-direct` | 23 | 0.751 | 1.000 |
| [csb_sdlc/csb_sdlc_document](runs/csb_sdlc-csb_sdlc_document.md) | `csb_sdlc_document` | `baseline-local-direct` | 26 | 0.801 | 1.000 |
| [csb_sdlc/csb_sdlc_document](runs/csb_sdlc-csb_sdlc_document.md) | `csb_sdlc_document` | `mcp-remote-direct` | 26 | 0.843 | 1.000 |
| [csb_sdlc/csb_sdlc_feature](runs/csb_sdlc-csb_sdlc_feature.md) | `csb_sdlc_feature` | `baseline-local-direct` | 30 | 0.506 | 0.767 |
| [csb_sdlc/csb_sdlc_feature](runs/csb_sdlc-csb_sdlc_feature.md) | `csb_sdlc_feature` | `mcp-remote-direct` | 30 | 0.522 | 0.767 |
| [csb_sdlc/csb_sdlc_fix](runs/csb_sdlc-csb_sdlc_fix.md) | `csb_sdlc_fix` | `baseline-local-direct` | 72 | 0.521 | 0.694 |
| [csb_sdlc/csb_sdlc_fix](runs/csb_sdlc-csb_sdlc_fix.md) | `csb_sdlc_fix` | `mcp-remote-direct` | 72 | 0.574 | 0.736 |
| [csb_sdlc/csb_sdlc_refactor](runs/csb_sdlc-csb_sdlc_refactor.md) | `csb_sdlc_refactor` | `baseline-local-direct` | 16 | 0.580 | 0.750 |
| [csb_sdlc/csb_sdlc_refactor](runs/csb_sdlc-csb_sdlc_refactor.md) | `csb_sdlc_refactor` | `mcp-remote-direct` | 16 | 0.683 | 0.875 |
| [csb_sdlc/csb_sdlc_secure](runs/csb_sdlc-csb_sdlc_secure.md) | `csb_sdlc_secure` | `baseline-local-direct` | 17 | 0.639 | 1.000 |
| [csb_sdlc/csb_sdlc_secure](runs/csb_sdlc-csb_sdlc_secure.md) | `csb_sdlc_secure` | `mcp-remote-direct` | 17 | 0.598 | 0.941 |
| [csb_sdlc/csb_sdlc_test](runs/csb_sdlc-csb_sdlc_test.md) | `csb_sdlc_test` | `baseline-local-direct` | 41 | 0.574 | 0.878 |
| [csb_sdlc/csb_sdlc_test](runs/csb_sdlc-csb_sdlc_test.md) | `csb_sdlc_test` | `mcp-remote-direct` | 41 | 0.552 | 0.878 |
| [csb_sdlc/csb_sdlc_understand](runs/csb_sdlc-csb_sdlc_understand.md) | `csb_sdlc_understand` | `baseline-local-direct` | 12 | 0.656 | 0.833 |
| [csb_sdlc/csb_sdlc_understand](runs/csb_sdlc-csb_sdlc_understand.md) | `csb_sdlc_understand` | `mcp-remote-direct` | 12 | 0.782 | 1.000 |

</details>

`index.html`, `data/official_results.json`, and `audits/*.json` provide GitHub-auditable artifacts.