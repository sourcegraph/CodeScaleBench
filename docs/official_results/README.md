# Official Results Browser

This bundle is generated from `runs/official/` and includes only valid scored tasks (`passed`/`failed` with numeric reward).

Generated: `2026-02-27T02:23:03.814992+00:00`

## Local Browse

```bash
python3 scripts/export_official_results.py --serve
```

Suite-level views are deduplicated to the latest row per `suite + config + task_name`.
Historical reruns/backfills remain available in `data/official_results.json` under `all_tasks`.

## Suite/Config Summary

| Suite | Config | Valid Tasks | Mean Reward | Pass Rate |
|---|---|---:|---:|---:|
| [ccb_build](suites/ccb_build.md) | `baseline` | 19 | 0.511 | 0.789 |
| [ccb_build](suites/ccb_build.md) | `baseline-local-direct` | 20 | 0.527 | 0.800 |
| [ccb_build](suites/ccb_build.md) | `mcp` | 25 | 0.372 | 0.640 |
| [ccb_build](suites/ccb_build.md) | `mcp-remote-direct` | 25 | 0.372 | 0.640 |
| [ccb_debug](suites/ccb_debug.md) | `baseline` | 20 | 0.670 | 1.000 |
| [ccb_debug](suites/ccb_debug.md) | `baseline-local-direct` | 20 | 0.670 | 1.000 |
| [ccb_debug](suites/ccb_debug.md) | `mcp` | 20 | 0.487 | 0.600 |
| [ccb_debug](suites/ccb_debug.md) | `mcp-remote-direct` | 20 | 0.487 | 0.600 |
| [ccb_design](suites/ccb_design.md) | `baseline` | 13 | 0.770 | 1.000 |
| [ccb_design](suites/ccb_design.md) | `baseline-local-direct` | 20 | 0.753 | 0.950 |
| [ccb_design](suites/ccb_design.md) | `mcp` | 20 | 0.718 | 1.000 |
| [ccb_design](suites/ccb_design.md) | `mcp-remote-direct` | 20 | 0.718 | 1.000 |
| [ccb_document](suites/ccb_document.md) | `baseline` | 14 | 0.904 | 1.000 |
| [ccb_document](suites/ccb_document.md) | `baseline-local-direct` | 20 | 0.847 | 1.000 |
| [ccb_document](suites/ccb_document.md) | `mcp` | 15 | 0.953 | 1.000 |
| [ccb_document](suites/ccb_document.md) | `mcp-remote-direct` | 25 | 0.802 | 1.000 |
| [ccb_fix](suites/ccb_fix.md) | `baseline` | 17 | 0.535 | 0.706 |
| [ccb_fix](suites/ccb_fix.md) | `baseline-local-direct` | 28 | 0.428 | 0.571 |
| [ccb_fix](suites/ccb_fix.md) | `mcp` | 17 | 0.538 | 0.647 |
| [ccb_fix](suites/ccb_fix.md) | `mcp-remote-direct` | 28 | 0.467 | 0.571 |
| [ccb_mcp_compliance](suites/ccb_mcp_compliance.md) | `baseline-local-artifact` | 1 | 0.375 | 1.000 |
| [ccb_mcp_compliance](suites/ccb_mcp_compliance.md) | `baseline-local-direct` | 6 | 0.668 | 1.000 |
| [ccb_mcp_compliance](suites/ccb_mcp_compliance.md) | `mcp-remote-artifact` | 1 | 0.742 | 1.000 |
| [ccb_mcp_compliance](suites/ccb_mcp_compliance.md) | `mcp-remote-direct` | 29 | 0.420 | 0.724 |
| [ccb_mcp_crossorg](suites/ccb_mcp_crossorg.md) | `baseline` | 2 | 0.750 | 1.000 |
| [ccb_mcp_crossorg](suites/ccb_mcp_crossorg.md) | `baseline-local-artifact` | 2 | 0.062 | 0.500 |
| [ccb_mcp_crossorg](suites/ccb_mcp_crossorg.md) | `baseline-local-direct` | 1 | 0.658 | 1.000 |
| [ccb_mcp_crossorg](suites/ccb_mcp_crossorg.md) | `mcp` | 2 | 1.000 | 1.000 |
| [ccb_mcp_crossorg](suites/ccb_mcp_crossorg.md) | `mcp-remote-artifact` | 2 | 0.171 | 0.500 |
| [ccb_mcp_crossorg](suites/ccb_mcp_crossorg.md) | `mcp-remote-direct` | 4 | 0.718 | 1.000 |
| [ccb_mcp_crossrepo](suites/ccb_mcp_crossrepo.md) | `baseline` | 3 | 0.941 | 1.000 |
| [ccb_mcp_crossrepo](suites/ccb_mcp_crossrepo.md) | `baseline-local-artifact` | 2 | 0.000 | 0.000 |
| [ccb_mcp_crossrepo](suites/ccb_mcp_crossrepo.md) | `baseline-local-direct` | 5 | 0.721 | 1.000 |
| [ccb_mcp_crossrepo](suites/ccb_mcp_crossrepo.md) | `mcp` | 3 | 0.899 | 1.000 |
| [ccb_mcp_crossrepo](suites/ccb_mcp_crossrepo.md) | `mcp-remote-artifact` | 2 | 0.287 | 1.000 |
| [ccb_mcp_crossrepo](suites/ccb_mcp_crossrepo.md) | `mcp-remote-direct` | 21 | 0.580 | 0.810 |
| [ccb_mcp_domain](suites/ccb_mcp_domain.md) | `baseline-local-artifact` | 3 | 0.000 | 0.000 |
| [ccb_mcp_domain](suites/ccb_mcp_domain.md) | `baseline-local-direct` | 7 | 0.632 | 1.000 |
| [ccb_mcp_domain](suites/ccb_mcp_domain.md) | `mcp-remote-artifact` | 3 | 0.529 | 1.000 |
| [ccb_mcp_domain](suites/ccb_mcp_domain.md) | `mcp-remote-direct` | 30 | 0.501 | 0.867 |
| [ccb_mcp_incident](suites/ccb_mcp_incident.md) | `baseline` | 1 | 0.500 | 1.000 |
| [ccb_mcp_incident](suites/ccb_mcp_incident.md) | `baseline-local-artifact` | 3 | 0.167 | 0.333 |
| [ccb_mcp_incident](suites/ccb_mcp_incident.md) | `baseline-local-direct` | 7 | 0.714 | 1.000 |
| [ccb_mcp_incident](suites/ccb_mcp_incident.md) | `mcp` | 1 | 1.000 | 1.000 |
| [ccb_mcp_incident](suites/ccb_mcp_incident.md) | `mcp-remote-artifact` | 3 | 0.782 | 1.000 |
| [ccb_mcp_incident](suites/ccb_mcp_incident.md) | `mcp-remote-direct` | 29 | 0.589 | 0.862 |
| [ccb_mcp_migration](suites/ccb_mcp_migration.md) | `baseline-local-direct` | 7 | 0.815 | 1.000 |
| [ccb_mcp_migration](suites/ccb_mcp_migration.md) | `mcp-remote-direct` | 34 | 0.342 | 0.647 |
| [ccb_mcp_onboarding](suites/ccb_mcp_onboarding.md) | `baseline` | 3 | 0.639 | 1.000 |
| [ccb_mcp_onboarding](suites/ccb_mcp_onboarding.md) | `baseline-local-artifact` | 4 | 0.000 | 0.000 |
| [ccb_mcp_onboarding](suites/ccb_mcp_onboarding.md) | `baseline-local-direct` | 4 | 0.524 | 1.000 |
| [ccb_mcp_onboarding](suites/ccb_mcp_onboarding.md) | `mcp` | 3 | 0.778 | 1.000 |
| [ccb_mcp_onboarding](suites/ccb_mcp_onboarding.md) | `mcp-remote-artifact` | 4 | 0.843 | 1.000 |
| [ccb_mcp_onboarding](suites/ccb_mcp_onboarding.md) | `mcp-remote-direct` | 17 | 0.490 | 1.000 |
| [ccb_mcp_org](suites/ccb_mcp_org.md) | `baseline-local-artifact` | 2 | 0.500 | 1.000 |
| [ccb_mcp_org](suites/ccb_mcp_org.md) | `baseline-local-direct` | 3 | 0.404 | 1.000 |
| [ccb_mcp_org](suites/ccb_mcp_org.md) | `mcp-remote-artifact` | 2 | 0.705 | 1.000 |
| [ccb_mcp_org](suites/ccb_mcp_org.md) | `mcp-remote-direct` | 12 | 0.518 | 1.000 |
| [ccb_mcp_platform](suites/ccb_mcp_platform.md) | `baseline` | 1 | 0.928 | 1.000 |
| [ccb_mcp_platform](suites/ccb_mcp_platform.md) | `baseline-local-direct` | 4 | 0.676 | 1.000 |
| [ccb_mcp_platform](suites/ccb_mcp_platform.md) | `mcp` | 1 | 0.928 | 1.000 |
| [ccb_mcp_platform](suites/ccb_mcp_platform.md) | `mcp-remote-direct` | 17 | 0.439 | 0.765 |
| [ccb_mcp_security](suites/ccb_mcp_security.md) | `baseline` | 2 | 0.500 | 1.000 |
| [ccb_mcp_security](suites/ccb_mcp_security.md) | `baseline-local-artifact` | 4 | 0.000 | 0.000 |
| [ccb_mcp_security](suites/ccb_mcp_security.md) | `baseline-local-direct` | 4 | 0.603 | 1.000 |
| [ccb_mcp_security](suites/ccb_mcp_security.md) | `mcp` | 2 | 0.821 | 1.000 |
| [ccb_mcp_security](suites/ccb_mcp_security.md) | `mcp-remote-artifact` | 4 | 0.777 | 1.000 |
| [ccb_mcp_security](suites/ccb_mcp_security.md) | `mcp-remote-direct` | 16 | 0.705 | 1.000 |
| [ccb_secure](suites/ccb_secure.md) | `baseline` | 18 | 0.688 | 0.944 |
| [ccb_secure](suites/ccb_secure.md) | `baseline-local-direct` | 20 | 0.669 | 0.950 |
| [ccb_secure](suites/ccb_secure.md) | `mcp` | 18 | 0.705 | 1.000 |
| [ccb_secure](suites/ccb_secure.md) | `mcp-remote-direct` | 22 | 0.645 | 0.909 |
| [ccb_test](suites/ccb_test.md) | `baseline` | 9 | 0.472 | 0.778 |
| [ccb_test](suites/ccb_test.md) | `baseline-local-direct` | 20 | 0.480 | 0.750 |
| [ccb_test](suites/ccb_test.md) | `mcp` | 8 | 0.555 | 0.625 |
| [ccb_test](suites/ccb_test.md) | `mcp-remote-direct` | 31 | 0.403 | 0.613 |
| [ccb_understand](suites/ccb_understand.md) | `baseline` | 13 | 0.592 | 0.692 |
| [ccb_understand](suites/ccb_understand.md) | `baseline-local-direct` | 20 | 0.660 | 0.800 |
| [ccb_understand](suites/ccb_understand.md) | `mcp` | 13 | 0.841 | 1.000 |
| [ccb_understand](suites/ccb_understand.md) | `mcp-remote-direct` | 20 | 0.851 | 1.000 |

<details>
<summary>Run/Config Summary</summary>


| Run | Suite | Config | Valid Tasks | Mean Reward | Pass Rate |
|---|---|---|---:|---:|---:|
| [build_haiku_20260223_124805](runs/build_haiku_20260223_124805.md) | `ccb_build` | `baseline-local-direct` | 19 | 0.511 | 0.789 |
| [build_haiku_20260223_124805](runs/build_haiku_20260223_124805.md) | `ccb_build` | `mcp-remote-direct` | 25 | 0.372 | 0.640 |
| [ccb_build_haiku_022326](runs/ccb_build_haiku_022326.md) | `ccb_build` | `baseline` | 19 | 0.511 | 0.789 |
| [ccb_build_haiku_022326](runs/ccb_build_haiku_022326.md) | `ccb_build` | `mcp` | 25 | 0.372 | 0.640 |
| [ccb_build_haiku_20260225_234223](runs/ccb_build_haiku_20260225_234223.md) | `ccb_build` | `baseline-local-direct` | 1 | 0.820 | 1.000 |
| [ccb_build_haiku_20260226_015500_backfill](runs/ccb_build_haiku_20260226_015500_backfill.md) | `ccb_build` | `baseline-local-direct` | 1 | 0.820 | 1.000 |
| [ccb_debug_haiku_022326](runs/ccb_debug_haiku_022326.md) | `ccb_debug` | `baseline` | 20 | 0.670 | 1.000 |
| [ccb_debug_haiku_022326](runs/ccb_debug_haiku_022326.md) | `ccb_debug` | `mcp` | 20 | 0.487 | 0.600 |
| [ccb_design_haiku_022326](runs/ccb_design_haiku_022326.md) | `ccb_design` | `baseline` | 13 | 0.770 | 1.000 |
| [ccb_design_haiku_022326](runs/ccb_design_haiku_022326.md) | `ccb_design` | `mcp` | 20 | 0.718 | 1.000 |
| [ccb_design_haiku_20260225_234223](runs/ccb_design_haiku_20260225_234223.md) | `ccb_design` | `baseline-local-direct` | 7 | 0.723 | 0.857 |
| [ccb_design_haiku_20260226_015500_backfill](runs/ccb_design_haiku_20260226_015500_backfill.md) | `ccb_design` | `baseline-local-direct` | 7 | 0.723 | 0.857 |
| [ccb_document_haiku_022326](runs/ccb_document_haiku_022326.md) | `ccb_document` | `baseline` | 14 | 0.904 | 1.000 |
| [ccb_document_haiku_022326](runs/ccb_document_haiku_022326.md) | `ccb_document` | `mcp` | 15 | 0.953 | 1.000 |
| [ccb_document_haiku_20260224_174311](runs/ccb_document_haiku_20260224_174311.md) | `ccb_document` | `baseline-local-direct` | 5 | 0.658 | 1.000 |
| [ccb_document_haiku_20260224_174311](runs/ccb_document_haiku_20260224_174311.md) | `ccb_document` | `mcp-remote-direct` | 5 | 0.720 | 1.000 |
| [ccb_document_haiku_20260226_015500_backfill](runs/ccb_document_haiku_20260226_015500_backfill.md) | `ccb_document` | `baseline-local-direct` | 1 | 1.000 | 1.000 |
| [ccb_fix_haiku_022326](runs/ccb_fix_haiku_022326.md) | `ccb_fix` | `baseline` | 17 | 0.535 | 0.706 |
| [ccb_fix_haiku_022326](runs/ccb_fix_haiku_022326.md) | `ccb_fix` | `mcp` | 17 | 0.538 | 0.647 |
| [ccb_fix_haiku_20260224_203138](runs/ccb_fix_haiku_20260224_203138.md) | `ccb_fix` | `baseline-local-direct` | 1 | 0.710 | 1.000 |
| [ccb_fix_haiku_20260224_203138](runs/ccb_fix_haiku_20260224_203138.md) | `ccb_fix` | `mcp-remote-direct` | 1 | 0.740 | 1.000 |
| [ccb_fix_haiku_20260226_015500_backfill](runs/ccb_fix_haiku_20260226_015500_backfill.md) | `ccb_fix` | `baseline-local-direct` | 2 | 0.235 | 0.500 |
| [ccb_fix_haiku_20260226_015500_backfill](runs/ccb_fix_haiku_20260226_015500_backfill.md) | `ccb_fix` | `mcp-remote-direct` | 1 | 0.667 | 1.000 |
| [ccb_mcp_compliance_haiku_20260224_181919](runs/ccb_mcp_compliance_haiku_20260224_181919.md) | `ccb_mcp_compliance` | `mcp-remote-artifact` | 1 | 0.742 | 1.000 |
| [ccb_mcp_compliance_haiku_20260225_011700](runs/ccb_mcp_compliance_haiku_20260225_011700.md) | `ccb_mcp_compliance` | `baseline-local-artifact` | 1 | 0.375 | 1.000 |
| [ccb_mcp_compliance_haiku_20260226_035515_variance](runs/ccb_mcp_compliance_haiku_20260226_035515_variance.md) | `ccb_mcp_compliance` | `baseline-local-direct` | 1 | 0.386 | 1.000 |
| [ccb_mcp_compliance_haiku_20260226_035515_variance](runs/ccb_mcp_compliance_haiku_20260226_035515_variance.md) | `ccb_mcp_compliance` | `mcp-remote-direct` | 3 | 0.489 | 1.000 |
| [ccb_mcp_compliance_haiku_20260226_035617](runs/ccb_mcp_compliance_haiku_20260226_035617.md) | `ccb_mcp_compliance` | `baseline-local-direct` | 1 | 0.327 | 1.000 |
| [ccb_mcp_compliance_haiku_20260226_035617](runs/ccb_mcp_compliance_haiku_20260226_035617.md) | `ccb_mcp_compliance` | `mcp-remote-direct` | 6 | 0.324 | 0.667 |
| [ccb_mcp_compliance_haiku_20260226_035622_variance](runs/ccb_mcp_compliance_haiku_20260226_035622_variance.md) | `ccb_mcp_compliance` | `baseline-local-direct` | 1 | 0.373 | 1.000 |
| [ccb_mcp_compliance_haiku_20260226_035622_variance](runs/ccb_mcp_compliance_haiku_20260226_035622_variance.md) | `ccb_mcp_compliance` | `mcp-remote-direct` | 6 | 0.394 | 0.667 |
| [ccb_mcp_compliance_haiku_20260226_035628_variance](runs/ccb_mcp_compliance_haiku_20260226_035628_variance.md) | `ccb_mcp_compliance` | `baseline-local-direct` | 1 | 0.302 | 1.000 |
| [ccb_mcp_compliance_haiku_20260226_035628_variance](runs/ccb_mcp_compliance_haiku_20260226_035628_variance.md) | `ccb_mcp_compliance` | `mcp-remote-direct` | 6 | 0.365 | 0.667 |
| [ccb_mcp_compliance_haiku_20260226_035633_variance](runs/ccb_mcp_compliance_haiku_20260226_035633_variance.md) | `ccb_mcp_compliance` | `baseline-local-direct` | 1 | 0.356 | 1.000 |
| [ccb_mcp_compliance_haiku_20260226_035633_variance](runs/ccb_mcp_compliance_haiku_20260226_035633_variance.md) | `ccb_mcp_compliance` | `mcp-remote-direct` | 6 | 0.426 | 0.667 |
| [ccb_mcp_compliance_haiku_20260226_205845](runs/ccb_mcp_compliance_haiku_20260226_205845.md) | `ccb_mcp_compliance` | `baseline-local-direct` | 3 | 0.700 | 1.000 |
| [ccb_mcp_compliance_haiku_20260226_211341](runs/ccb_mcp_compliance_haiku_20260226_211341.md) | `ccb_mcp_compliance` | `baseline-local-direct` | 2 | 0.000 | 0.000 |
| [ccb_mcp_compliance_haiku_20260226_214446](runs/ccb_mcp_compliance_haiku_20260226_214446.md) | `ccb_mcp_compliance` | `baseline-local-direct` | 2 | 0.778 | 1.000 |
| [ccb_mcp_compliance_haiku_20260226_221038](runs/ccb_mcp_compliance_haiku_20260226_221038.md) | `ccb_mcp_compliance` | `mcp-remote-direct` | 2 | 0.833 | 1.000 |
| [ccb_mcp_crossorg_haiku_022126](runs/ccb_mcp_crossorg_haiku_022126.md) | `ccb_mcp_crossorg` | `baseline` | 2 | 0.750 | 1.000 |
| [ccb_mcp_crossorg_haiku_022126](runs/ccb_mcp_crossorg_haiku_022126.md) | `ccb_mcp_crossorg` | `mcp` | 2 | 1.000 | 1.000 |
| [ccb_mcp_crossorg_haiku_20260224_181919](runs/ccb_mcp_crossorg_haiku_20260224_181919.md) | `ccb_mcp_crossorg` | `mcp-remote-artifact` | 2 | 0.171 | 0.500 |
| [ccb_mcp_crossorg_haiku_20260225_011700](runs/ccb_mcp_crossorg_haiku_20260225_011700.md) | `ccb_mcp_crossorg` | `baseline-local-artifact` | 2 | 0.062 | 0.500 |
| [ccb_mcp_crossorg_haiku_20260226_035617](runs/ccb_mcp_crossorg_haiku_20260226_035617.md) | `ccb_mcp_crossorg` | `mcp-remote-direct` | 1 | 0.800 | 1.000 |
| [ccb_mcp_crossorg_haiku_20260226_035622_variance](runs/ccb_mcp_crossorg_haiku_20260226_035622_variance.md) | `ccb_mcp_crossorg` | `mcp-remote-direct` | 1 | 0.680 | 1.000 |
| [ccb_mcp_crossorg_haiku_20260226_035628_variance](runs/ccb_mcp_crossorg_haiku_20260226_035628_variance.md) | `ccb_mcp_crossorg` | `mcp-remote-direct` | 1 | 0.680 | 1.000 |
| [ccb_mcp_crossorg_haiku_20260226_035633_variance](runs/ccb_mcp_crossorg_haiku_20260226_035633_variance.md) | `ccb_mcp_crossorg` | `mcp-remote-direct` | 1 | 0.711 | 1.000 |
| [ccb_mcp_crossorg_haiku_20260226_205845](runs/ccb_mcp_crossorg_haiku_20260226_205845.md) | `ccb_mcp_crossorg` | `baseline-local-direct` | 1 | 0.658 | 1.000 |
| [ccb_mcp_crossrepo_haiku_20260226_035617](runs/ccb_mcp_crossrepo_haiku_20260226_035617.md) | `ccb_mcp_crossrepo` | `mcp-remote-direct` | 1 | 0.767 | 1.000 |
| [ccb_mcp_crossrepo_haiku_20260226_035622_variance](runs/ccb_mcp_crossrepo_haiku_20260226_035622_variance.md) | `ccb_mcp_crossrepo` | `mcp-remote-direct` | 1 | 0.644 | 1.000 |
| [ccb_mcp_crossrepo_haiku_20260226_035628_variance](runs/ccb_mcp_crossrepo_haiku_20260226_035628_variance.md) | `ccb_mcp_crossrepo` | `mcp-remote-direct` | 1 | 0.767 | 1.000 |
| [ccb_mcp_crossrepo_haiku_20260226_035633_variance](runs/ccb_mcp_crossrepo_haiku_20260226_035633_variance.md) | `ccb_mcp_crossrepo` | `mcp-remote-direct` | 1 | 0.850 | 1.000 |
| [ccb_mcp_crossrepo_haiku_20260226_205845](runs/ccb_mcp_crossrepo_haiku_20260226_205845.md) | `ccb_mcp_crossrepo` | `baseline-local-direct` | 1 | 0.867 | 1.000 |
| [ccb_mcp_crossrepo_tracing_haiku_022126](runs/ccb_mcp_crossrepo_tracing_haiku_022126.md) | `ccb_mcp_crossrepo` | `baseline` | 3 | 0.941 | 1.000 |
| [ccb_mcp_crossrepo_tracing_haiku_022126](runs/ccb_mcp_crossrepo_tracing_haiku_022126.md) | `ccb_mcp_crossrepo` | `mcp` | 3 | 0.899 | 1.000 |
| [ccb_mcp_crossrepo_tracing_haiku_20260224_181919](runs/ccb_mcp_crossrepo_tracing_haiku_20260224_181919.md) | `ccb_mcp_crossrepo` | `mcp-remote-artifact` | 2 | 0.287 | 1.000 |
| [ccb_mcp_crossrepo_tracing_haiku_20260225_011700](runs/ccb_mcp_crossrepo_tracing_haiku_20260225_011700.md) | `ccb_mcp_crossrepo` | `baseline-local-artifact` | 2 | 0.000 | 0.000 |
| [ccb_mcp_crossrepo_tracing_haiku_20260226_035617](runs/ccb_mcp_crossrepo_tracing_haiku_20260226_035617.md) | `ccb_mcp_crossrepo` | `mcp-remote-direct` | 4 | 0.501 | 0.750 |
| [ccb_mcp_crossrepo_tracing_haiku_20260226_035622_variance](runs/ccb_mcp_crossrepo_tracing_haiku_20260226_035622_variance.md) | `ccb_mcp_crossrepo` | `mcp-remote-direct` | 4 | 0.572 | 0.750 |
| [ccb_mcp_crossrepo_tracing_haiku_20260226_035628_variance](runs/ccb_mcp_crossrepo_tracing_haiku_20260226_035628_variance.md) | `ccb_mcp_crossrepo` | `mcp-remote-direct` | 4 | 0.567 | 0.750 |
| [ccb_mcp_crossrepo_tracing_haiku_20260226_035633_variance](runs/ccb_mcp_crossrepo_tracing_haiku_20260226_035633_variance.md) | `ccb_mcp_crossrepo` | `mcp-remote-direct` | 4 | 0.446 | 0.750 |
| [ccb_mcp_crossrepo_tracing_haiku_20260226_205845](runs/ccb_mcp_crossrepo_tracing_haiku_20260226_205845.md) | `ccb_mcp_crossrepo` | `baseline-local-direct` | 4 | 0.542 | 0.750 |
| [ccb_mcp_crossrepo_tracing_haiku_20260226_214446](runs/ccb_mcp_crossrepo_tracing_haiku_20260226_214446.md) | `ccb_mcp_crossrepo` | `baseline-local-direct` | 1 | 0.571 | 1.000 |
| [ccb_mcp_crossrepo_tracing_haiku_20260226_221038](runs/ccb_mcp_crossrepo_tracing_haiku_20260226_221038.md) | `ccb_mcp_crossrepo` | `mcp-remote-direct` | 1 | 0.800 | 1.000 |
| [ccb_mcp_domain_haiku_20260224_181919](runs/ccb_mcp_domain_haiku_20260224_181919.md) | `ccb_mcp_domain` | `mcp-remote-artifact` | 3 | 0.529 | 1.000 |
| [ccb_mcp_domain_haiku_20260225_011700](runs/ccb_mcp_domain_haiku_20260225_011700.md) | `ccb_mcp_domain` | `baseline-local-artifact` | 3 | 0.000 | 0.000 |
| [ccb_mcp_domain_haiku_20260226_035617](runs/ccb_mcp_domain_haiku_20260226_035617.md) | `ccb_mcp_domain` | `baseline-local-direct` | 1 | 0.000 | 0.000 |
| [ccb_mcp_domain_haiku_20260226_035617](runs/ccb_mcp_domain_haiku_20260226_035617.md) | `ccb_mcp_domain` | `mcp-remote-direct` | 7 | 0.479 | 0.857 |
| [ccb_mcp_domain_haiku_20260226_035622_variance](runs/ccb_mcp_domain_haiku_20260226_035622_variance.md) | `ccb_mcp_domain` | `baseline-local-direct` | 1 | 0.000 | 0.000 |
| [ccb_mcp_domain_haiku_20260226_035622_variance](runs/ccb_mcp_domain_haiku_20260226_035622_variance.md) | `ccb_mcp_domain` | `mcp-remote-direct` | 7 | 0.435 | 0.857 |
| [ccb_mcp_domain_haiku_20260226_035628_variance](runs/ccb_mcp_domain_haiku_20260226_035628_variance.md) | `ccb_mcp_domain` | `baseline-local-direct` | 1 | 0.000 | 0.000 |
| [ccb_mcp_domain_haiku_20260226_035628_variance](runs/ccb_mcp_domain_haiku_20260226_035628_variance.md) | `ccb_mcp_domain` | `mcp-remote-direct` | 7 | 0.537 | 0.857 |
| [ccb_mcp_domain_haiku_20260226_035633_variance](runs/ccb_mcp_domain_haiku_20260226_035633_variance.md) | `ccb_mcp_domain` | `baseline-local-direct` | 1 | 0.000 | 0.000 |
| [ccb_mcp_domain_haiku_20260226_035633_variance](runs/ccb_mcp_domain_haiku_20260226_035633_variance.md) | `ccb_mcp_domain` | `mcp-remote-direct` | 7 | 0.465 | 0.857 |
| [ccb_mcp_domain_haiku_20260226_205845](runs/ccb_mcp_domain_haiku_20260226_205845.md) | `ccb_mcp_domain` | `baseline-local-direct` | 6 | 0.604 | 1.000 |
| [ccb_mcp_domain_haiku_20260226_222632](runs/ccb_mcp_domain_haiku_20260226_222632.md) | `ccb_mcp_domain` | `baseline-local-direct` | 1 | 0.800 | 1.000 |
| [ccb_mcp_domain_haiku_20260226_222632](runs/ccb_mcp_domain_haiku_20260226_222632.md) | `ccb_mcp_domain` | `mcp-remote-direct` | 1 | 0.800 | 1.000 |
| [ccb_mcp_domain_haiku_20260226_224414](runs/ccb_mcp_domain_haiku_20260226_224414.md) | `ccb_mcp_domain` | `baseline-local-direct` | 1 | 0.800 | 1.000 |
| [ccb_mcp_domain_haiku_20260226_224414](runs/ccb_mcp_domain_haiku_20260226_224414.md) | `ccb_mcp_domain` | `mcp-remote-direct` | 1 | 0.800 | 1.000 |
| [ccb_mcp_incident_haiku_022126](runs/ccb_mcp_incident_haiku_022126.md) | `ccb_mcp_incident` | `baseline` | 1 | 0.500 | 1.000 |
| [ccb_mcp_incident_haiku_022126](runs/ccb_mcp_incident_haiku_022126.md) | `ccb_mcp_incident` | `mcp` | 1 | 1.000 | 1.000 |
| [ccb_mcp_incident_haiku_20260224_181919](runs/ccb_mcp_incident_haiku_20260224_181919.md) | `ccb_mcp_incident` | `mcp-remote-artifact` | 3 | 0.782 | 1.000 |
| [ccb_mcp_incident_haiku_20260225_011700](runs/ccb_mcp_incident_haiku_20260225_011700.md) | `ccb_mcp_incident` | `baseline-local-artifact` | 3 | 0.167 | 0.333 |
| [ccb_mcp_incident_haiku_20260226_035617](runs/ccb_mcp_incident_haiku_20260226_035617.md) | `ccb_mcp_incident` | `mcp-remote-direct` | 7 | 0.646 | 0.857 |
| [ccb_mcp_incident_haiku_20260226_035622_variance](runs/ccb_mcp_incident_haiku_20260226_035622_variance.md) | `ccb_mcp_incident` | `baseline-local-direct` | 1 | 0.000 | 0.000 |
| [ccb_mcp_incident_haiku_20260226_035622_variance](runs/ccb_mcp_incident_haiku_20260226_035622_variance.md) | `ccb_mcp_incident` | `mcp-remote-direct` | 7 | 0.542 | 0.857 |
| [ccb_mcp_incident_haiku_20260226_035628_variance](runs/ccb_mcp_incident_haiku_20260226_035628_variance.md) | `ccb_mcp_incident` | `baseline-local-direct` | 1 | 0.000 | 0.000 |
| [ccb_mcp_incident_haiku_20260226_035628_variance](runs/ccb_mcp_incident_haiku_20260226_035628_variance.md) | `ccb_mcp_incident` | `mcp-remote-direct` | 7 | 0.567 | 0.857 |
| [ccb_mcp_incident_haiku_20260226_035633_variance](runs/ccb_mcp_incident_haiku_20260226_035633_variance.md) | `ccb_mcp_incident` | `baseline-local-direct` | 1 | 0.000 | 0.000 |
| [ccb_mcp_incident_haiku_20260226_035633_variance](runs/ccb_mcp_incident_haiku_20260226_035633_variance.md) | `ccb_mcp_incident` | `mcp-remote-direct` | 7 | 0.573 | 0.857 |
| [ccb_mcp_incident_haiku_20260226_205845](runs/ccb_mcp_incident_haiku_20260226_205845.md) | `ccb_mcp_incident` | `baseline-local-direct` | 6 | 0.722 | 1.000 |
| [ccb_mcp_incident_haiku_20260226_224414](runs/ccb_mcp_incident_haiku_20260226_224414.md) | `ccb_mcp_incident` | `baseline-local-direct` | 1 | 0.667 | 1.000 |
| [ccb_mcp_incident_haiku_20260226_224414](runs/ccb_mcp_incident_haiku_20260226_224414.md) | `ccb_mcp_incident` | `mcp-remote-direct` | 1 | 0.800 | 1.000 |
| [ccb_mcp_migration_haiku_20260226_035617](runs/ccb_mcp_migration_haiku_20260226_035617.md) | `ccb_mcp_migration` | `baseline-local-direct` | 2 | 0.944 | 1.000 |
| [ccb_mcp_migration_haiku_20260226_035617](runs/ccb_mcp_migration_haiku_20260226_035617.md) | `ccb_mcp_migration` | `mcp-remote-direct` | 7 | 0.221 | 0.571 |
| [ccb_mcp_migration_haiku_20260226_035622_variance](runs/ccb_mcp_migration_haiku_20260226_035622_variance.md) | `ccb_mcp_migration` | `baseline-local-direct` | 2 | 0.944 | 1.000 |
| [ccb_mcp_migration_haiku_20260226_035622_variance](runs/ccb_mcp_migration_haiku_20260226_035622_variance.md) | `ccb_mcp_migration` | `mcp-remote-direct` | 7 | 0.241 | 0.571 |
| [ccb_mcp_migration_haiku_20260226_035628_variance](runs/ccb_mcp_migration_haiku_20260226_035628_variance.md) | `ccb_mcp_migration` | `baseline-local-direct` | 2 | 0.944 | 1.000 |
| [ccb_mcp_migration_haiku_20260226_035628_variance](runs/ccb_mcp_migration_haiku_20260226_035628_variance.md) | `ccb_mcp_migration` | `mcp-remote-direct` | 7 | 0.228 | 0.571 |
| [ccb_mcp_migration_haiku_20260226_035633_variance](runs/ccb_mcp_migration_haiku_20260226_035633_variance.md) | `ccb_mcp_migration` | `baseline-local-direct` | 2 | 1.000 | 1.000 |
| [ccb_mcp_migration_haiku_20260226_035633_variance](runs/ccb_mcp_migration_haiku_20260226_035633_variance.md) | `ccb_mcp_migration` | `mcp-remote-direct` | 7 | 0.248 | 0.571 |
| [ccb_mcp_migration_haiku_20260226_205845](runs/ccb_mcp_migration_haiku_20260226_205845.md) | `ccb_mcp_migration` | `baseline-local-direct` | 5 | 0.024 | 0.400 |
| [ccb_mcp_migration_haiku_20260226_214446](runs/ccb_mcp_migration_haiku_20260226_214446.md) | `ccb_mcp_migration` | `baseline-local-direct` | 3 | 0.930 | 1.000 |
| [ccb_mcp_migration_haiku_20260226_221038](runs/ccb_mcp_migration_haiku_20260226_221038.md) | `ccb_mcp_migration` | `mcp-remote-direct` | 3 | 0.917 | 1.000 |
| [ccb_mcp_migration_haiku_20260226_231458](runs/ccb_mcp_migration_haiku_20260226_231458.md) | `ccb_mcp_migration` | `baseline-local-direct` | 3 | 0.639 | 1.000 |
| [ccb_mcp_migration_haiku_20260226_231458](runs/ccb_mcp_migration_haiku_20260226_231458.md) | `ccb_mcp_migration` | `mcp-remote-direct` | 3 | 0.771 | 1.000 |
| [ccb_mcp_onboarding_haiku_022126](runs/ccb_mcp_onboarding_haiku_022126.md) | `ccb_mcp_onboarding` | `baseline` | 3 | 0.639 | 1.000 |
| [ccb_mcp_onboarding_haiku_022126](runs/ccb_mcp_onboarding_haiku_022126.md) | `ccb_mcp_onboarding` | `mcp` | 3 | 0.778 | 1.000 |
| [ccb_mcp_onboarding_haiku_20260224_181919](runs/ccb_mcp_onboarding_haiku_20260224_181919.md) | `ccb_mcp_onboarding` | `mcp-remote-artifact` | 4 | 0.843 | 1.000 |
| [ccb_mcp_onboarding_haiku_20260225_011700](runs/ccb_mcp_onboarding_haiku_20260225_011700.md) | `ccb_mcp_onboarding` | `baseline-local-artifact` | 4 | 0.000 | 0.000 |
| [ccb_mcp_onboarding_haiku_20260226_035617](runs/ccb_mcp_onboarding_haiku_20260226_035617.md) | `ccb_mcp_onboarding` | `mcp-remote-direct` | 4 | 0.501 | 1.000 |
| [ccb_mcp_onboarding_haiku_20260226_035622_variance](runs/ccb_mcp_onboarding_haiku_20260226_035622_variance.md) | `ccb_mcp_onboarding` | `mcp-remote-direct` | 4 | 0.452 | 1.000 |
| [ccb_mcp_onboarding_haiku_20260226_035628_variance](runs/ccb_mcp_onboarding_haiku_20260226_035628_variance.md) | `ccb_mcp_onboarding` | `mcp-remote-direct` | 4 | 0.550 | 1.000 |
| [ccb_mcp_onboarding_haiku_20260226_035633_variance](runs/ccb_mcp_onboarding_haiku_20260226_035633_variance.md) | `ccb_mcp_onboarding` | `mcp-remote-direct` | 4 | 0.472 | 1.000 |
| [ccb_mcp_onboarding_haiku_20260226_205845](runs/ccb_mcp_onboarding_haiku_20260226_205845.md) | `ccb_mcp_onboarding` | `baseline-local-direct` | 3 | 0.540 | 1.000 |
| [ccb_mcp_onboarding_haiku_20260226_231458](runs/ccb_mcp_onboarding_haiku_20260226_231458.md) | `ccb_mcp_onboarding` | `baseline-local-direct` | 1 | 0.473 | 1.000 |
| [ccb_mcp_onboarding_haiku_20260226_231458](runs/ccb_mcp_onboarding_haiku_20260226_231458.md) | `ccb_mcp_onboarding` | `mcp-remote-direct` | 1 | 0.432 | 1.000 |
| [ccb_mcp_org_haiku_20260224_181919](runs/ccb_mcp_org_haiku_20260224_181919.md) | `ccb_mcp_org` | `mcp-remote-artifact` | 2 | 0.705 | 1.000 |
| [ccb_mcp_org_haiku_20260225_011700](runs/ccb_mcp_org_haiku_20260225_011700.md) | `ccb_mcp_org` | `baseline-local-artifact` | 2 | 0.500 | 1.000 |
| [ccb_mcp_org_haiku_20260226_035617](runs/ccb_mcp_org_haiku_20260226_035617.md) | `ccb_mcp_org` | `mcp-remote-direct` | 3 | 0.503 | 1.000 |
| [ccb_mcp_org_haiku_20260226_035622_variance](runs/ccb_mcp_org_haiku_20260226_035622_variance.md) | `ccb_mcp_org` | `mcp-remote-direct` | 3 | 0.557 | 1.000 |
| [ccb_mcp_org_haiku_20260226_035628_variance](runs/ccb_mcp_org_haiku_20260226_035628_variance.md) | `ccb_mcp_org` | `mcp-remote-direct` | 3 | 0.497 | 1.000 |
| [ccb_mcp_org_haiku_20260226_035633_variance](runs/ccb_mcp_org_haiku_20260226_035633_variance.md) | `ccb_mcp_org` | `mcp-remote-direct` | 3 | 0.515 | 1.000 |
| [ccb_mcp_org_haiku_20260226_205845](runs/ccb_mcp_org_haiku_20260226_205845.md) | `ccb_mcp_org` | `baseline-local-direct` | 3 | 0.404 | 1.000 |
| [ccb_mcp_platform_haiku_022126](runs/ccb_mcp_platform_haiku_022126.md) | `ccb_mcp_platform` | `baseline` | 1 | 0.928 | 1.000 |
| [ccb_mcp_platform_haiku_022126](runs/ccb_mcp_platform_haiku_022126.md) | `ccb_mcp_platform` | `mcp` | 1 | 0.928 | 1.000 |
| [ccb_mcp_platform_haiku_20260226_035617](runs/ccb_mcp_platform_haiku_20260226_035617.md) | `ccb_mcp_platform` | `baseline-local-direct` | 2 | 0.744 | 1.000 |
| [ccb_mcp_platform_haiku_20260226_035617](runs/ccb_mcp_platform_haiku_20260226_035617.md) | `ccb_mcp_platform` | `mcp-remote-direct` | 4 | 0.408 | 0.750 |
| [ccb_mcp_platform_haiku_20260226_035622_variance](runs/ccb_mcp_platform_haiku_20260226_035622_variance.md) | `ccb_mcp_platform` | `baseline-local-direct` | 2 | 0.728 | 1.000 |
| [ccb_mcp_platform_haiku_20260226_035622_variance](runs/ccb_mcp_platform_haiku_20260226_035622_variance.md) | `ccb_mcp_platform` | `mcp-remote-direct` | 4 | 0.429 | 0.750 |
| [ccb_mcp_platform_haiku_20260226_035628_variance](runs/ccb_mcp_platform_haiku_20260226_035628_variance.md) | `ccb_mcp_platform` | `baseline-local-direct` | 2 | 0.744 | 1.000 |
| [ccb_mcp_platform_haiku_20260226_035628_variance](runs/ccb_mcp_platform_haiku_20260226_035628_variance.md) | `ccb_mcp_platform` | `mcp-remote-direct` | 4 | 0.476 | 0.750 |
| [ccb_mcp_platform_haiku_20260226_035633_variance](runs/ccb_mcp_platform_haiku_20260226_035633_variance.md) | `ccb_mcp_platform` | `baseline-local-direct` | 2 | 0.717 | 1.000 |
| [ccb_mcp_platform_haiku_20260226_035633_variance](runs/ccb_mcp_platform_haiku_20260226_035633_variance.md) | `ccb_mcp_platform` | `mcp-remote-direct` | 4 | 0.414 | 0.750 |
| [ccb_mcp_platform_haiku_20260226_205845](runs/ccb_mcp_platform_haiku_20260226_205845.md) | `ccb_mcp_platform` | `baseline-local-direct` | 2 | 0.292 | 0.500 |
| [ccb_mcp_platform_haiku_20260226_214446](runs/ccb_mcp_platform_haiku_20260226_214446.md) | `ccb_mcp_platform` | `baseline-local-direct` | 1 | 0.632 | 1.000 |
| [ccb_mcp_platform_haiku_20260226_221038](runs/ccb_mcp_platform_haiku_20260226_221038.md) | `ccb_mcp_platform` | `mcp-remote-direct` | 1 | 0.556 | 1.000 |
| [ccb_mcp_security_haiku_022126](runs/ccb_mcp_security_haiku_022126.md) | `ccb_mcp_security` | `baseline` | 2 | 0.500 | 1.000 |
| [ccb_mcp_security_haiku_022126](runs/ccb_mcp_security_haiku_022126.md) | `ccb_mcp_security` | `mcp` | 2 | 0.821 | 1.000 |
| [ccb_mcp_security_haiku_20260224_181919](runs/ccb_mcp_security_haiku_20260224_181919.md) | `ccb_mcp_security` | `mcp-remote-artifact` | 4 | 0.777 | 1.000 |
| [ccb_mcp_security_haiku_20260225_011700](runs/ccb_mcp_security_haiku_20260225_011700.md) | `ccb_mcp_security` | `baseline-local-artifact` | 4 | 0.000 | 0.000 |
| [ccb_mcp_security_haiku_20260226_035617](runs/ccb_mcp_security_haiku_20260226_035617.md) | `ccb_mcp_security` | `baseline-local-direct` | 1 | 0.433 | 1.000 |
| [ccb_mcp_security_haiku_20260226_035617](runs/ccb_mcp_security_haiku_20260226_035617.md) | `ccb_mcp_security` | `mcp-remote-direct` | 4 | 0.744 | 1.000 |
| [ccb_mcp_security_haiku_20260226_035622_variance](runs/ccb_mcp_security_haiku_20260226_035622_variance.md) | `ccb_mcp_security` | `baseline-local-direct` | 1 | 0.514 | 1.000 |
| [ccb_mcp_security_haiku_20260226_035622_variance](runs/ccb_mcp_security_haiku_20260226_035622_variance.md) | `ccb_mcp_security` | `mcp-remote-direct` | 4 | 0.578 | 1.000 |
| [ccb_mcp_security_haiku_20260226_035628_variance](runs/ccb_mcp_security_haiku_20260226_035628_variance.md) | `ccb_mcp_security` | `baseline-local-direct` | 1 | 0.367 | 1.000 |
| [ccb_mcp_security_haiku_20260226_035628_variance](runs/ccb_mcp_security_haiku_20260226_035628_variance.md) | `ccb_mcp_security` | `mcp-remote-direct` | 4 | 0.767 | 1.000 |
| [ccb_mcp_security_haiku_20260226_035633_variance](runs/ccb_mcp_security_haiku_20260226_035633_variance.md) | `ccb_mcp_security` | `baseline-local-direct` | 1 | 0.586 | 1.000 |
| [ccb_mcp_security_haiku_20260226_035633_variance](runs/ccb_mcp_security_haiku_20260226_035633_variance.md) | `ccb_mcp_security` | `mcp-remote-direct` | 4 | 0.731 | 1.000 |
| [ccb_mcp_security_haiku_20260226_205845](runs/ccb_mcp_security_haiku_20260226_205845.md) | `ccb_mcp_security` | `baseline-local-direct` | 3 | 0.682 | 1.000 |
| [ccb_secure_haiku_022326](runs/ccb_secure_haiku_022326.md) | `ccb_secure` | `baseline` | 18 | 0.688 | 0.944 |
| [ccb_secure_haiku_022326](runs/ccb_secure_haiku_022326.md) | `ccb_secure` | `mcp` | 18 | 0.705 | 1.000 |
| [ccb_secure_haiku_20260224_213146](runs/ccb_secure_haiku_20260224_213146.md) | `ccb_secure` | `baseline-local-direct` | 2 | 0.500 | 1.000 |
| [ccb_secure_haiku_20260224_213146](runs/ccb_secure_haiku_20260224_213146.md) | `ccb_secure` | `mcp-remote-direct` | 2 | 0.250 | 0.500 |
| [ccb_test_haiku_022326](runs/ccb_test_haiku_022326.md) | `ccb_test` | `baseline` | 9 | 0.472 | 0.778 |
| [ccb_test_haiku_022326](runs/ccb_test_haiku_022326.md) | `ccb_test` | `mcp` | 8 | 0.555 | 0.625 |
| [ccb_test_haiku_20260224_180149](runs/ccb_test_haiku_20260224_180149.md) | `ccb_test` | `baseline-local-direct` | 11 | 0.486 | 0.727 |
| [ccb_test_haiku_20260224_180149](runs/ccb_test_haiku_20260224_180149.md) | `ccb_test` | `mcp-remote-direct` | 11 | 0.387 | 0.727 |
| [ccb_test_haiku_20260226_015500_backfill](runs/ccb_test_haiku_20260226_015500_backfill.md) | `ccb_test` | `baseline-local-direct` | 1 | 0.370 | 1.000 |
| [ccb_test_haiku_20260226_015500_backfill](runs/ccb_test_haiku_20260226_015500_backfill.md) | `ccb_test` | `mcp-remote-direct` | 1 | 0.900 | 1.000 |
| [ccb_understand_haiku_022426](runs/ccb_understand_haiku_022426.md) | `ccb_understand` | `baseline` | 13 | 0.592 | 0.692 |
| [ccb_understand_haiku_022426](runs/ccb_understand_haiku_022426.md) | `ccb_understand` | `mcp` | 13 | 0.841 | 1.000 |
| [debug_haiku_20260223_154724](runs/debug_haiku_20260223_154724.md) | `ccb_debug` | `baseline-local-direct` | 20 | 0.670 | 1.000 |
| [debug_haiku_20260223_154724](runs/debug_haiku_20260223_154724.md) | `ccb_debug` | `mcp-remote-direct` | 20 | 0.487 | 0.600 |
| [design_haiku_20260223_124652](runs/design_haiku_20260223_124652.md) | `ccb_design` | `baseline-local-direct` | 13 | 0.770 | 1.000 |
| [design_haiku_20260223_124652](runs/design_haiku_20260223_124652.md) | `ccb_design` | `mcp-remote-direct` | 20 | 0.718 | 1.000 |
| [document_haiku_20260223_164240](runs/document_haiku_20260223_164240.md) | `ccb_document` | `baseline-local-direct` | 19 | 0.851 | 1.000 |
| [document_haiku_20260223_164240](runs/document_haiku_20260223_164240.md) | `ccb_document` | `mcp-remote-direct` | 20 | 0.822 | 1.000 |
| [document_haiku_20260226_013910](runs/document_haiku_20260226_013910.md) | `ccb_document` | `baseline-local-direct` | 1 | 1.000 | 1.000 |
| [fix_haiku_20260223_171232](runs/fix_haiku_20260223_171232.md) | `ccb_fix` | `baseline-local-direct` | 24 | 0.379 | 0.500 |
| [fix_haiku_20260223_171232](runs/fix_haiku_20260223_171232.md) | `ccb_fix` | `mcp-remote-direct` | 22 | 0.451 | 0.545 |
| [fix_haiku_20260224_011821](runs/fix_haiku_20260224_011821.md) | `ccb_fix` | `baseline-local-direct` | 3 | 0.000 | 0.000 |
| [fix_haiku_20260224_011821](runs/fix_haiku_20260224_011821.md) | `ccb_fix` | `mcp-remote-direct` | 3 | 0.260 | 0.333 |
| [fix_haiku_20260226_024454](runs/fix_haiku_20260226_024454.md) | `ccb_fix` | `baseline-local-direct` | 3 | 0.000 | 0.000 |
| [fix_haiku_20260226_024454](runs/fix_haiku_20260226_024454.md) | `ccb_fix` | `mcp-remote-direct` | 3 | 0.000 | 0.000 |
| [fix_haiku_20260226_new3tasks](runs/fix_haiku_20260226_new3tasks.md) | `ccb_fix` | `baseline-local-direct` | 3 | 0.727 | 1.000 |
| [fix_haiku_20260226_new3tasks](runs/fix_haiku_20260226_new3tasks.md) | `ccb_fix` | `mcp-remote-direct` | 3 | 0.801 | 1.000 |
| [secure_haiku_20260223_232545](runs/secure_haiku_20260223_232545.md) | `ccb_secure` | `baseline-local-direct` | 20 | 0.669 | 0.950 |
| [secure_haiku_20260223_232545](runs/secure_haiku_20260223_232545.md) | `ccb_secure` | `mcp-remote-direct` | 18 | 0.705 | 1.000 |
| [secure_haiku_20260224_011825](runs/secure_haiku_20260224_011825.md) | `ccb_secure` | `mcp-remote-direct` | 2 | 0.500 | 0.500 |
| [test_haiku_20260223_235732](runs/test_haiku_20260223_235732.md) | `ccb_test` | `baseline-local-direct` | 10 | 0.492 | 0.800 |
| [test_haiku_20260223_235732](runs/test_haiku_20260223_235732.md) | `ccb_test` | `mcp-remote-direct` | 19 | 0.495 | 0.684 |
| [test_haiku_20260224_011816](runs/test_haiku_20260224_011816.md) | `ccb_test` | `baseline-local-direct` | 11 | 0.295 | 0.545 |
| [test_haiku_20260224_011816](runs/test_haiku_20260224_011816.md) | `ccb_test` | `mcp-remote-direct` | 11 | 0.262 | 0.455 |
| [understand_haiku_20260224_001815](runs/understand_haiku_20260224_001815.md) | `ccb_understand` | `baseline-local-direct` | 20 | 0.533 | 0.650 |
| [understand_haiku_20260224_001815](runs/understand_haiku_20260224_001815.md) | `ccb_understand` | `mcp-remote-direct` | 20 | 0.679 | 0.850 |
| [understand_haiku_20260225_211346](runs/understand_haiku_20260225_211346.md) | `ccb_understand` | `baseline-local-direct` | 7 | 0.789 | 1.000 |
| [understand_haiku_20260225_211346](runs/understand_haiku_20260225_211346.md) | `ccb_understand` | `mcp-remote-direct` | 7 | 0.870 | 1.000 |

</details>

`index.html`, `data/official_results.json`, and `audits/*.json` provide GitHub-auditable artifacts.