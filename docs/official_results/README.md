# Official Results Browser

This bundle is generated from `runs/official/` and includes only valid scored tasks (`passed`/`failed` with numeric reward).

Generated: `2026-03-02T04:18:08.444959+00:00`

## Local Browse

```bash
python3 scripts/export_official_results.py --serve
```

Suite-level views are deduplicated to the latest row per `suite + config + task_name`.
Historical reruns/backfills remain available in `data/official_results.json` under `all_tasks`.

## Suite/Config Summary

| Suite | Config | Valid Tasks | Min Required | Mean Reward | Pass Rate | Coverage |
|---|---|---:|---:|---:|---:|---|
| [ccb_build](suites/ccb_build.md) | `baseline-local-direct` | 23 | 23 | 0.601 | 0.826 | ok |
| [ccb_build](suites/ccb_build.md) | `mcp-remote-direct` | 20 | 23 | 0.592 | 0.800 | FLAG: below minimum |
| [ccb_debug](suites/ccb_debug.md) | `baseline-local-direct` | 20 | 20 | 0.688 | 1.000 | ok |
| [ccb_debug](suites/ccb_debug.md) | `mcp-remote-direct` | 31 | 20 | 0.508 | 0.774 | ok |
| [ccb_design](suites/ccb_design.md) | `baseline-local-direct` | 20 | 20 | 0.770 | 1.000 | ok |
| [ccb_design](suites/ccb_design.md) | `mcp-remote-direct` | 33 | 20 | 0.720 | 0.970 | ok |
| [ccb_document](suites/ccb_document.md) | `baseline-local-direct` | 20 | 20 | 0.845 | 1.000 | ok |
| [ccb_document](suites/ccb_document.md) | `mcp-remote-direct` | 44 | 20 | 0.875 | 1.000 | ok |
| [ccb_feature](suites/ccb_feature.md) | `baseline-local-direct` | 23 | 20 | 0.599 | 0.870 | ok |
| [ccb_feature](suites/ccb_feature.md) | `mcp-remote-direct` | 34 | 20 | 0.524 | 0.794 | ok |
| [ccb_fix](suites/ccb_fix.md) | `baseline-local-direct` | 26 | 25 | 0.496 | 0.654 | ok |
| [ccb_fix](suites/ccb_fix.md) | `mcp-remote-direct` | 98 | 25 | 0.570 | 0.714 | ok |
| [ccb_mcp_compliance](suites/ccb_mcp_compliance.md) | `baseline-local-artifact` | 1 | 54 | 0.375 | 1.000 | FLAG: below minimum |
| [ccb_mcp_compliance](suites/ccb_mcp_compliance.md) | `baseline-local-direct` | 21 | 54 | 0.318 | 0.810 | FLAG: below minimum |
| [ccb_mcp_compliance](suites/ccb_mcp_compliance.md) | `mcp-remote-artifact` | 1 | 54 | 0.742 | 1.000 | FLAG: below minimum |
| [ccb_mcp_compliance](suites/ccb_mcp_compliance.md) | `mcp-remote-direct` | 54 | 54 | 0.394 | 0.889 | ok |
| [ccb_mcp_crossorg](suites/ccb_mcp_crossorg.md) | `baseline-local-artifact` | 4 | 21 | 0.406 | 0.750 | FLAG: below minimum |
| [ccb_mcp_crossorg](suites/ccb_mcp_crossorg.md) | `baseline-local-direct` | 17 | 21 | 0.170 | 0.647 | FLAG: below minimum |
| [ccb_mcp_crossorg](suites/ccb_mcp_crossorg.md) | `mcp-remote-artifact` | 4 | 21 | 0.586 | 0.750 | FLAG: below minimum |
| [ccb_mcp_crossorg](suites/ccb_mcp_crossorg.md) | `mcp-remote-direct` | 21 | 21 | 0.344 | 0.762 | ok |
| [ccb_mcp_crossrepo](suites/ccb_mcp_crossrepo.md) | `baseline-local-artifact` | 5 | 81 | 0.565 | 0.600 | FLAG: below minimum |
| [ccb_mcp_crossrepo](suites/ccb_mcp_crossrepo.md) | `baseline-local-direct` | 42 | 81 | 0.296 | 0.762 | FLAG: below minimum |
| [ccb_mcp_crossrepo](suites/ccb_mcp_crossrepo.md) | `mcp-remote-artifact` | 5 | 81 | 0.654 | 1.000 | FLAG: below minimum |
| [ccb_mcp_crossrepo](suites/ccb_mcp_crossrepo.md) | `mcp-remote-direct` | 81 | 81 | 0.369 | 0.815 | ok |
| [ccb_mcp_domain](suites/ccb_mcp_domain.md) | `baseline-local-artifact` | 3 | 49 | 0.000 | 0.000 | FLAG: below minimum |
| [ccb_mcp_domain](suites/ccb_mcp_domain.md) | `baseline-local-direct` | 20 | 49 | 0.351 | 0.900 | FLAG: below minimum |
| [ccb_mcp_domain](suites/ccb_mcp_domain.md) | `mcp-remote-artifact` | 3 | 49 | 0.529 | 1.000 | FLAG: below minimum |
| [ccb_mcp_domain](suites/ccb_mcp_domain.md) | `mcp-remote-direct` | 49 | 49 | 0.396 | 0.898 | ok |
| [ccb_mcp_incident](suites/ccb_mcp_incident.md) | `baseline-local-artifact` | 4 | 49 | 0.250 | 0.500 | FLAG: below minimum |
| [ccb_mcp_incident](suites/ccb_mcp_incident.md) | `baseline-local-direct` | 20 | 49 | 0.448 | 0.800 | FLAG: below minimum |
| [ccb_mcp_incident](suites/ccb_mcp_incident.md) | `mcp-remote-artifact` | 4 | 49 | 0.837 | 1.000 | FLAG: below minimum |
| [ccb_mcp_incident](suites/ccb_mcp_incident.md) | `mcp-remote-direct` | 49 | 49 | 0.586 | 0.939 | ok |
| [ccb_mcp_migration](suites/ccb_mcp_migration.md) | `baseline-local-direct` | 26 | 61 | 0.400 | 0.846 | FLAG: below minimum |
| [ccb_mcp_migration](suites/ccb_mcp_migration.md) | `mcp-remote-direct` | 61 | 61 | 0.495 | 0.869 | ok |
| [ccb_mcp_onboarding](suites/ccb_mcp_onboarding.md) | `baseline-local-artifact` | 5 | 78 | 0.200 | 0.200 | FLAG: below minimum |
| [ccb_mcp_onboarding](suites/ccb_mcp_onboarding.md) | `baseline-local-direct` | 28 | 78 | 0.724 | 0.929 | FLAG: below minimum |
| [ccb_mcp_onboarding](suites/ccb_mcp_onboarding.md) | `mcp-remote-artifact` | 5 | 78 | 0.875 | 1.000 | FLAG: below minimum |
| [ccb_mcp_onboarding](suites/ccb_mcp_onboarding.md) | `mcp-remote-direct` | 78 | 78 | 0.788 | 0.974 | ok |
| [ccb_mcp_org](suites/ccb_mcp_org.md) | `baseline-local-artifact` | 2 | 47 | 0.500 | 1.000 | FLAG: below minimum |
| [ccb_mcp_org](suites/ccb_mcp_org.md) | `baseline-local-direct` | 20 | 47 | 0.364 | 0.950 | FLAG: below minimum |
| [ccb_mcp_org](suites/ccb_mcp_org.md) | `mcp-remote-artifact` | 2 | 47 | 0.705 | 1.000 | FLAG: below minimum |
| [ccb_mcp_org](suites/ccb_mcp_org.md) | `mcp-remote-direct` | 47 | 47 | 0.315 | 0.702 | ok |
| [ccb_mcp_platform](suites/ccb_mcp_platform.md) | `baseline-local-direct` | 21 | 50 | 0.311 | 0.952 | FLAG: below minimum |
| [ccb_mcp_platform](suites/ccb_mcp_platform.md) | `mcp-remote-direct` | 50 | 50 | 0.316 | 0.960 | ok |
| [ccb_mcp_security](suites/ccb_mcp_security.md) | `baseline-local-artifact` | 25 | 39 | 0.283 | 0.720 | FLAG: below minimum |
| [ccb_mcp_security](suites/ccb_mcp_security.md) | `baseline-local-direct` | 16 | 39 | 0.596 | 0.875 | FLAG: below minimum |
| [ccb_mcp_security](suites/ccb_mcp_security.md) | `mcp-remote-artifact` | 26 | 39 | 0.563 | 1.000 | FLAG: below minimum |
| [ccb_mcp_security](suites/ccb_mcp_security.md) | `mcp-remote-direct` | 39 | 39 | 0.726 | 1.000 | ok |
| [ccb_refactor](suites/ccb_refactor.md) | `baseline-local-direct` | 20 | 20 | 0.804 | 0.950 | ok |
| [ccb_refactor](suites/ccb_refactor.md) | `mcp-remote-direct` | 20 | 20 | 0.703 | 1.000 | ok |
| [ccb_secure](suites/ccb_secure.md) | `baseline-local-direct` | 20 | 20 | 0.712 | 1.000 | ok |
| [ccb_secure](suites/ccb_secure.md) | `mcp-remote-direct` | 24 | 20 | 0.707 | 0.958 | ok |
| [ccb_test](suites/ccb_test.md) | `baseline-local-direct` | 20 | 20 | 0.482 | 0.750 | ok |
| [ccb_test](suites/ccb_test.md) | `mcp-remote-direct` | 53 | 20 | 0.503 | 0.792 | ok |
| [ccb_understand](suites/ccb_understand.md) | `baseline-local-direct` | 34 | 20 | 0.902 | 0.971 | ok |
| [ccb_understand](suites/ccb_understand.md) | `mcp-remote-direct` | 48 | 20 | 0.873 | 0.979 | ok |

<details>
<summary>Run/Config Summary</summary>


| Run | Suite | Config | Valid Tasks | Mean Reward | Pass Rate |
|---|---|---|---:|---:|---:|
| [ccb_build_haiku_20260227_025524](runs/ccb_build_haiku_20260227_025524.md) | `ccb_build` | `baseline-local-direct` | 3 | 0.513 | 1.000 |
| [ccb_build_haiku_20260227_034711](runs/ccb_build_haiku_20260227_034711.md) | `ccb_build` | `baseline-local-direct` | 1 | 0.500 | 1.000 |
| [ccb_build_haiku_20260227_123839](runs/ccb_build_haiku_20260227_123839.md) | `ccb_build` | `baseline-local-direct` | 8 | 0.641 | 1.000 |
| [ccb_build_haiku_20260227_123839](runs/ccb_build_haiku_20260227_123839.md) | `ccb_build` | `mcp-remote-direct` | 7 | 0.571 | 1.000 |
| [ccb_build_haiku_20260228_025547](runs/ccb_build_haiku_20260228_025547.md) | `ccb_build` | `baseline-local-direct` | 13 | 0.554 | 0.692 |
| [ccb_build_haiku_20260228_025547](runs/ccb_build_haiku_20260228_025547.md) | `ccb_build` | `mcp-remote-direct` | 10 | 0.595 | 0.700 |
| [ccb_build_haiku_20260228_124521](runs/ccb_build_haiku_20260228_124521.md) | `ccb_build` | `mcp-remote-direct` | 1 | 0.880 | 1.000 |
| [ccb_build_haiku_20260228_160517](runs/ccb_build_haiku_20260228_160517.md) | `ccb_build` | `baseline-local-direct` | 1 | 1.000 | 1.000 |
| [ccb_build_haiku_20260228_161037](runs/ccb_build_haiku_20260228_161037.md) | `ccb_build` | `baseline-local-direct` | 1 | 1.000 | 1.000 |
| [ccb_build_haiku_20260228_161037](runs/ccb_build_haiku_20260228_161037.md) | `ccb_build` | `mcp-remote-direct` | 1 | 1.000 | 1.000 |
| [ccb_build_haiku_20260228_161452](runs/ccb_build_haiku_20260228_161452.md) | `ccb_build` | `baseline-local-direct` | 1 | 1.000 | 1.000 |
| [ccb_build_haiku_20260228_161452](runs/ccb_build_haiku_20260228_161452.md) | `ccb_build` | `mcp-remote-direct` | 1 | 0.000 | 0.000 |
| [ccb_debug_haiku_20260228_025547](runs/ccb_debug_haiku_20260228_025547.md) | `ccb_debug` | `baseline-local-direct` | 5 | 0.500 | 1.000 |
| [ccb_debug_haiku_20260228_025547](runs/ccb_debug_haiku_20260228_025547.md) | `ccb_debug` | `mcp-remote-direct` | 5 | 0.000 | 0.000 |
| [ccb_debug_haiku_20260228_051032](runs/ccb_debug_haiku_20260228_051032.md) | `ccb_debug` | `baseline-local-direct` | 3 | 0.900 | 1.000 |
| [ccb_debug_haiku_20260228_123206](runs/ccb_debug_haiku_20260228_123206.md) | `ccb_debug` | `baseline-local-direct` | 2 | 0.300 | 1.000 |
| [ccb_debug_haiku_20260301_230240](runs/ccb_debug_haiku_20260301_230240.md) | `ccb_debug` | `baseline-local-direct` | 2 | 0.500 | 1.000 |
| [ccb_debug_haiku_20260301_230240](runs/ccb_debug_haiku_20260301_230240.md) | `ccb_debug` | `mcp-remote-direct` | 2 | 0.500 | 1.000 |
| [ccb_debug_haiku_20260302_004746](runs/ccb_debug_haiku_20260302_004746.md) | `ccb_debug` | `baseline-local-direct` | 2 | 0.750 | 1.000 |
| [ccb_debug_haiku_20260302_004746](runs/ccb_debug_haiku_20260302_004746.md) | `ccb_debug` | `mcp-remote-direct` | 2 | 0.500 | 1.000 |
| [ccb_debug_haiku_20260302_013712](runs/ccb_debug_haiku_20260302_013712.md) | `ccb_debug` | `baseline-local-direct` | 1 | 0.500 | 1.000 |
| [ccb_debug_haiku_20260302_013713](runs/ccb_debug_haiku_20260302_013713.md) | `ccb_debug` | `mcp-remote-direct` | 1 | 0.500 | 1.000 |
| [ccb_debug_haiku_20260302_022552](runs/ccb_debug_haiku_20260302_022552.md) | `ccb_debug` | `baseline-local-direct` | 1 | 0.500 | 1.000 |
| [ccb_debug_haiku_20260302_022553](runs/ccb_debug_haiku_20260302_022553.md) | `ccb_debug` | `mcp-remote-direct` | 1 | 0.500 | 1.000 |
| [ccb_design_haiku_022326](runs/ccb_design_haiku_022326.md) | `ccb_design` | `baseline-local-direct` | 13 | 0.770 | 1.000 |
| [ccb_design_haiku_022326](runs/ccb_design_haiku_022326.md) | `ccb_design` | `mcp-remote-direct` | 20 | 0.718 | 1.000 |
| [ccb_design_haiku_20260225_234223](runs/ccb_design_haiku_20260225_234223.md) | `ccb_design` | `baseline-local-direct` | 7 | 0.723 | 0.857 |
| [ccb_design_haiku_20260226_015500_backfill](runs/ccb_design_haiku_20260226_015500_backfill.md) | `ccb_design` | `baseline-local-direct` | 7 | 0.723 | 0.857 |
| [ccb_design_haiku_20260228_025547](runs/ccb_design_haiku_20260228_025547.md) | `ccb_design` | `baseline-local-direct` | 13 | 0.598 | 1.000 |
| [ccb_design_haiku_20260228_025547](runs/ccb_design_haiku_20260228_025547.md) | `ccb_design` | `mcp-remote-direct` | 13 | 0.751 | 1.000 |
| [ccb_document_haiku_022326](runs/ccb_document_haiku_022326.md) | `ccb_document` | `baseline-local-direct` | 14 | 0.904 | 1.000 |
| [ccb_document_haiku_022326](runs/ccb_document_haiku_022326.md) | `ccb_document` | `mcp-remote-direct` | 15 | 0.953 | 1.000 |
| [ccb_document_haiku_20260224_174311](runs/ccb_document_haiku_20260224_174311.md) | `ccb_document` | `baseline-local-direct` | 5 | 0.658 | 1.000 |
| [ccb_document_haiku_20260224_174311](runs/ccb_document_haiku_20260224_174311.md) | `ccb_document` | `mcp-remote-direct` | 5 | 0.720 | 1.000 |
| [ccb_document_haiku_20260226_015500_backfill](runs/ccb_document_haiku_20260226_015500_backfill.md) | `ccb_document` | `baseline-local-direct` | 1 | 1.000 | 1.000 |
| [ccb_document_haiku_20260228_025547](runs/ccb_document_haiku_20260228_025547.md) | `ccb_document` | `baseline-local-direct` | 18 | 0.879 | 1.000 |
| [ccb_document_haiku_20260228_025547](runs/ccb_document_haiku_20260228_025547.md) | `ccb_document` | `mcp-remote-direct` | 18 | 0.887 | 1.000 |
| [ccb_document_haiku_20260228_124521](runs/ccb_document_haiku_20260228_124521.md) | `ccb_document` | `mcp-remote-direct` | 1 | 1.000 | 1.000 |
| [ccb_feature_haiku_20260301_212230](runs/ccb_feature_haiku_20260301_212230.md) | `ccb_feature` | `baseline-local-direct` | 3 | 0.500 | 0.667 |
| [ccb_feature_haiku_20260301_212230](runs/ccb_feature_haiku_20260301_212230.md) | `ccb_feature` | `mcp-remote-direct` | 3 | 0.500 | 0.667 |
| [ccb_feature_haiku_20260301_230003](runs/ccb_feature_haiku_20260301_230003.md) | `ccb_feature` | `baseline-local-direct` | 4 | 0.358 | 0.750 |
| [ccb_feature_haiku_20260301_230003](runs/ccb_feature_haiku_20260301_230003.md) | `ccb_feature` | `mcp-remote-direct` | 4 | 0.407 | 0.750 |
| [ccb_feature_haiku_20260302_004743](runs/ccb_feature_haiku_20260302_004743.md) | `ccb_feature` | `baseline-local-direct` | 3 | 0.444 | 0.667 |
| [ccb_feature_haiku_20260302_004743](runs/ccb_feature_haiku_20260302_004743.md) | `ccb_feature` | `mcp-remote-direct` | 3 | 0.500 | 0.667 |
| [ccb_feature_haiku_20260302_005828](runs/ccb_feature_haiku_20260302_005828.md) | `ccb_feature` | `baseline-local-direct` | 3 | 0.222 | 0.667 |
| [ccb_feature_haiku_20260302_005828](runs/ccb_feature_haiku_20260302_005828.md) | `ccb_feature` | `mcp-remote-direct` | 3 | 0.500 | 0.667 |
| [ccb_feature_haiku_20260302_005948](runs/ccb_feature_haiku_20260302_005948.md) | `ccb_feature` | `mcp-remote-direct` | 1 | 0.140 | 1.000 |
| [ccb_feature_haiku_20260302_022544](runs/ccb_feature_haiku_20260302_022544.md) | `ccb_feature` | `baseline-local-direct` | 1 | 0.000 | 0.000 |
| [ccb_fix_haiku_20260228_185835](runs/ccb_fix_haiku_20260228_185835.md) | `ccb_fix` | `baseline-local-direct` | 25 | 0.471 | 0.640 |
| [ccb_fix_haiku_20260228_185835](runs/ccb_fix_haiku_20260228_185835.md) | `ccb_fix` | `mcp-remote-direct` | 25 | 0.592 | 0.720 |
| [ccb_fix_haiku_20260228_203750](runs/ccb_fix_haiku_20260228_203750.md) | `ccb_fix` | `baseline-local-direct` | 3 | 0.457 | 1.000 |
| [ccb_fix_haiku_20260228_205741](runs/ccb_fix_haiku_20260228_205741.md) | `ccb_fix` | `baseline-local-direct` | 25 | 0.440 | 0.600 |
| [ccb_fix_haiku_20260228_205741](runs/ccb_fix_haiku_20260228_205741.md) | `ccb_fix` | `mcp-remote-direct` | 25 | 0.536 | 0.680 |
| [ccb_fix_haiku_20260228_230722](runs/ccb_fix_haiku_20260228_230722.md) | `ccb_fix` | `baseline-local-direct` | 20 | 0.510 | 0.650 |
| [ccb_fix_haiku_20260228_230722](runs/ccb_fix_haiku_20260228_230722.md) | `ccb_fix` | `mcp-remote-direct` | 20 | 0.593 | 0.750 |
| [ccb_fix_haiku_20260301_173337](runs/ccb_fix_haiku_20260301_173337.md) | `ccb_fix` | `baseline-local-direct` | 9 | 0.597 | 0.889 |
| [ccb_fix_haiku_20260301_173337](runs/ccb_fix_haiku_20260301_173337.md) | `ccb_fix` | `mcp-remote-direct` | 5 | 0.646 | 1.000 |
| [ccb_fix_haiku_20260301_173342](runs/ccb_fix_haiku_20260301_173342.md) | `ccb_fix` | `mcp-remote-direct` | 8 | 0.621 | 0.625 |
| [ccb_fix_haiku_20260301_212230](runs/ccb_fix_haiku_20260301_212230.md) | `ccb_fix` | `baseline-local-direct` | 1 | 0.000 | 0.000 |
| [ccb_fix_haiku_20260301_212230](runs/ccb_fix_haiku_20260301_212230.md) | `ccb_fix` | `mcp-remote-direct` | 1 | 0.000 | 0.000 |
| [ccb_fix_haiku_20260301_214459](runs/ccb_fix_haiku_20260301_214459.md) | `ccb_fix` | `baseline-local-direct` | 1 | 0.500 | 1.000 |
| [ccb_fix_haiku_20260301_214459](runs/ccb_fix_haiku_20260301_214459.md) | `ccb_fix` | `mcp-remote-direct` | 1 | 0.500 | 1.000 |
| [ccb_fix_haiku_20260301_230003](runs/ccb_fix_haiku_20260301_230003.md) | `ccb_fix` | `baseline-local-direct` | 1 | 0.667 | 1.000 |
| [ccb_fix_haiku_20260301_230048](runs/ccb_fix_haiku_20260301_230048.md) | `ccb_fix` | `baseline-local-direct` | 3 | 0.413 | 0.667 |
| [ccb_fix_haiku_20260301_230048](runs/ccb_fix_haiku_20260301_230048.md) | `ccb_fix` | `mcp-remote-direct` | 1 | 0.500 | 1.000 |
| [ccb_fix_haiku_20260301_230240](runs/ccb_fix_haiku_20260301_230240.md) | `ccb_fix` | `baseline-local-direct` | 3 | 0.537 | 0.667 |
| [ccb_fix_haiku_20260301_230240](runs/ccb_fix_haiku_20260301_230240.md) | `ccb_fix` | `mcp-remote-direct` | 3 | 0.667 | 0.667 |
| [ccb_fix_haiku_20260302_005828](runs/ccb_fix_haiku_20260302_005828.md) | `ccb_fix` | `baseline-local-direct` | 1 | 0.500 | 1.000 |
| [ccb_fix_haiku_20260302_005828](runs/ccb_fix_haiku_20260302_005828.md) | `ccb_fix` | `mcp-remote-direct` | 1 | 0.500 | 1.000 |
| [ccb_fix_haiku_20260302_005945](runs/ccb_fix_haiku_20260302_005945.md) | `ccb_fix` | `baseline-local-direct` | 2 | 0.191 | 0.500 |
| [ccb_fix_haiku_20260302_013712](runs/ccb_fix_haiku_20260302_013712.md) | `ccb_fix` | `baseline-local-direct` | 2 | 0.333 | 0.500 |
| [ccb_fix_haiku_20260302_013713](runs/ccb_fix_haiku_20260302_013713.md) | `ccb_fix` | `mcp-remote-direct` | 1 | 1.000 | 1.000 |
| [ccb_fix_haiku_20260302_015531](runs/ccb_fix_haiku_20260302_015531.md) | `ccb_fix` | `mcp-remote-direct` | 1 | 1.000 | 1.000 |
| [ccb_fix_haiku_20260302_020340](runs/ccb_fix_haiku_20260302_020340.md) | `ccb_fix` | `mcp-remote-direct` | 2 | 0.280 | 0.500 |
| [ccb_fix_haiku_20260302_021447](runs/ccb_fix_haiku_20260302_021447.md) | `ccb_fix` | `baseline-local-direct` | 2 | 0.429 | 0.500 |
| [ccb_fix_haiku_20260302_022542](runs/ccb_fix_haiku_20260302_022542.md) | `ccb_fix` | `baseline-local-direct` | 1 | 0.667 | 1.000 |
| [ccb_fix_haiku_20260302_022542](runs/ccb_fix_haiku_20260302_022542.md) | `ccb_fix` | `mcp-remote-direct` | 1 | 0.500 | 1.000 |
| [ccb_fix_haiku_20260302_022550](runs/ccb_fix_haiku_20260302_022550.md) | `ccb_fix` | `baseline-local-direct` | 1 | 0.667 | 1.000 |
| [ccb_fix_haiku_20260302_022550](runs/ccb_fix_haiku_20260302_022550.md) | `ccb_fix` | `mcp-remote-direct` | 1 | 1.000 | 1.000 |
| [ccb_fix_haiku_20260302_022552](runs/ccb_fix_haiku_20260302_022552.md) | `ccb_fix` | `baseline-local-direct` | 1 | 0.000 | 0.000 |
| [ccb_mcp_compliance_haiku_20260224_181919](runs/ccb_mcp_compliance_haiku_20260224_181919.md) | `ccb_mcp_compliance` | `mcp-remote-artifact` | 1 | 0.742 | 1.000 |
| [ccb_mcp_compliance_haiku_20260225_011700](runs/ccb_mcp_compliance_haiku_20260225_011700.md) | `ccb_mcp_compliance` | `baseline-local-artifact` | 1 | 0.375 | 1.000 |
| [ccb_mcp_compliance_haiku_20260226_035515_variance](runs/ccb_mcp_compliance_haiku_20260226_035515_variance.md) | `ccb_mcp_compliance` | `baseline-local-direct` | 1 | 0.386 | 1.000 |
| [ccb_mcp_compliance_haiku_20260226_035515_variance](runs/ccb_mcp_compliance_haiku_20260226_035515_variance.md) | `ccb_mcp_compliance` | `mcp-remote-direct` | 3 | 0.489 | 1.000 |
| [ccb_mcp_compliance_haiku_20260226_035617](runs/ccb_mcp_compliance_haiku_20260226_035617.md) | `ccb_mcp_compliance` | `baseline-local-direct` | 1 | 0.327 | 1.000 |
| [ccb_mcp_compliance_haiku_20260226_035617](runs/ccb_mcp_compliance_haiku_20260226_035617.md) | `ccb_mcp_compliance` | `mcp-remote-direct` | 4 | 0.485 | 1.000 |
| [ccb_mcp_compliance_haiku_20260226_035622_variance](runs/ccb_mcp_compliance_haiku_20260226_035622_variance.md) | `ccb_mcp_compliance` | `baseline-local-direct` | 1 | 0.373 | 1.000 |
| [ccb_mcp_compliance_haiku_20260226_035622_variance](runs/ccb_mcp_compliance_haiku_20260226_035622_variance.md) | `ccb_mcp_compliance` | `mcp-remote-direct` | 4 | 0.590 | 1.000 |
| [ccb_mcp_compliance_haiku_20260226_035628_variance](runs/ccb_mcp_compliance_haiku_20260226_035628_variance.md) | `ccb_mcp_compliance` | `baseline-local-direct` | 1 | 0.302 | 1.000 |
| [ccb_mcp_compliance_haiku_20260226_035628_variance](runs/ccb_mcp_compliance_haiku_20260226_035628_variance.md) | `ccb_mcp_compliance` | `mcp-remote-direct` | 4 | 0.548 | 1.000 |
| [ccb_mcp_compliance_haiku_20260226_035633_variance](runs/ccb_mcp_compliance_haiku_20260226_035633_variance.md) | `ccb_mcp_compliance` | `baseline-local-direct` | 1 | 0.356 | 1.000 |
| [ccb_mcp_compliance_haiku_20260226_035633_variance](runs/ccb_mcp_compliance_haiku_20260226_035633_variance.md) | `ccb_mcp_compliance` | `mcp-remote-direct` | 4 | 0.638 | 1.000 |
| [ccb_mcp_compliance_haiku_20260226_145828](runs/ccb_mcp_compliance_haiku_20260226_145828.md) | `ccb_mcp_compliance` | `baseline-local-direct` | 5 | 0.436 | 0.600 |
| [ccb_mcp_compliance_haiku_20260226_205845](runs/ccb_mcp_compliance_haiku_20260226_205845.md) | `ccb_mcp_compliance` | `baseline-local-direct` | 3 | 0.700 | 1.000 |
| [ccb_mcp_compliance_haiku_20260226_214446](runs/ccb_mcp_compliance_haiku_20260226_214446.md) | `ccb_mcp_compliance` | `baseline-local-direct` | 2 | 0.778 | 1.000 |
| [ccb_mcp_compliance_haiku_20260226_221038](runs/ccb_mcp_compliance_haiku_20260226_221038.md) | `ccb_mcp_compliance` | `mcp-remote-direct` | 2 | 0.833 | 1.000 |
| [ccb_mcp_compliance_haiku_20260228_011250](runs/ccb_mcp_compliance_haiku_20260228_011250.md) | `ccb_mcp_compliance` | `baseline-local-direct` | 7 | 0.652 | 1.000 |
| [ccb_mcp_compliance_haiku_20260228_011250](runs/ccb_mcp_compliance_haiku_20260228_011250.md) | `ccb_mcp_compliance` | `mcp-remote-direct` | 7 | 0.597 | 1.000 |
| [ccb_mcp_compliance_haiku_20260228_123206](runs/ccb_mcp_compliance_haiku_20260228_123206.md) | `ccb_mcp_compliance` | `baseline-local-direct` | 1 | 0.593 | 1.000 |
| [ccb_mcp_compliance_haiku_20260228_133005](runs/ccb_mcp_compliance_haiku_20260228_133005.md) | `ccb_mcp_compliance` | `baseline-local-direct` | 1 | 0.655 | 1.000 |
| [ccb_mcp_compliance_haiku_20260301_185444](runs/ccb_mcp_compliance_haiku_20260301_185444.md) | `ccb_mcp_compliance` | `baseline-local-direct` | 14 | 0.153 | 0.714 |
| [ccb_mcp_compliance_haiku_20260301_185444](runs/ccb_mcp_compliance_haiku_20260301_185444.md) | `ccb_mcp_compliance` | `mcp-remote-direct` | 14 | 0.186 | 0.714 |
| [ccb_mcp_compliance_haiku_20260302_014939](runs/ccb_mcp_compliance_haiku_20260302_014939.md) | `ccb_mcp_compliance` | `baseline-local-direct` | 12 | 0.179 | 0.833 |
| [ccb_mcp_compliance_haiku_20260302_014939](runs/ccb_mcp_compliance_haiku_20260302_014939.md) | `ccb_mcp_compliance` | `mcp-remote-direct` | 12 | 0.194 | 0.833 |
| [ccb_mcp_crossorg_haiku_022126](runs/ccb_mcp_crossorg_haiku_022126.md) | `ccb_mcp_crossorg` | `baseline-local-artifact` | 2 | 0.750 | 1.000 |
| [ccb_mcp_crossorg_haiku_022126](runs/ccb_mcp_crossorg_haiku_022126.md) | `ccb_mcp_crossorg` | `mcp-remote-artifact` | 2 | 1.000 | 1.000 |
| [ccb_mcp_crossorg_haiku_20260224_181919](runs/ccb_mcp_crossorg_haiku_20260224_181919.md) | `ccb_mcp_crossorg` | `mcp-remote-artifact` | 2 | 0.171 | 0.500 |
| [ccb_mcp_crossorg_haiku_20260225_011700](runs/ccb_mcp_crossorg_haiku_20260225_011700.md) | `ccb_mcp_crossorg` | `baseline-local-artifact` | 2 | 0.062 | 0.500 |
| [ccb_mcp_crossorg_haiku_20260226_035617](runs/ccb_mcp_crossorg_haiku_20260226_035617.md) | `ccb_mcp_crossorg` | `mcp-remote-direct` | 1 | 0.800 | 1.000 |
| [ccb_mcp_crossorg_haiku_20260226_035622_variance](runs/ccb_mcp_crossorg_haiku_20260226_035622_variance.md) | `ccb_mcp_crossorg` | `mcp-remote-direct` | 1 | 0.680 | 1.000 |
| [ccb_mcp_crossorg_haiku_20260226_035628_variance](runs/ccb_mcp_crossorg_haiku_20260226_035628_variance.md) | `ccb_mcp_crossorg` | `mcp-remote-direct` | 1 | 0.680 | 1.000 |
| [ccb_mcp_crossorg_haiku_20260226_035633_variance](runs/ccb_mcp_crossorg_haiku_20260226_035633_variance.md) | `ccb_mcp_crossorg` | `mcp-remote-direct` | 1 | 0.711 | 1.000 |
| [ccb_mcp_crossorg_haiku_20260226_145828](runs/ccb_mcp_crossorg_haiku_20260226_145828.md) | `ccb_mcp_crossorg` | `baseline-local-direct` | 1 | 0.335 | 1.000 |
| [ccb_mcp_crossorg_haiku_20260226_205845](runs/ccb_mcp_crossorg_haiku_20260226_205845.md) | `ccb_mcp_crossorg` | `baseline-local-direct` | 1 | 0.658 | 1.000 |
| [ccb_mcp_crossorg_haiku_20260228_005320](runs/ccb_mcp_crossorg_haiku_20260228_005320.md) | `ccb_mcp_crossorg` | `baseline-local-direct` | 5 | 0.330 | 0.800 |
| [ccb_mcp_crossorg_haiku_20260228_005320](runs/ccb_mcp_crossorg_haiku_20260228_005320.md) | `ccb_mcp_crossorg` | `mcp-remote-direct` | 5 | 0.434 | 0.800 |
| [ccb_mcp_crossorg_haiku_20260228_123206](runs/ccb_mcp_crossorg_haiku_20260228_123206.md) | `ccb_mcp_crossorg` | `baseline-local-direct` | 2 | 0.345 | 1.000 |
| [ccb_mcp_crossorg_haiku_20260228_133005](runs/ccb_mcp_crossorg_haiku_20260228_133005.md) | `ccb_mcp_crossorg` | `baseline-local-direct` | 2 | 0.334 | 1.000 |
| [ccb_mcp_crossorg_haiku_20260302_014939](runs/ccb_mcp_crossorg_haiku_20260302_014939.md) | `ccb_mcp_crossorg` | `baseline-local-direct` | 12 | 0.107 | 0.583 |
| [ccb_mcp_crossorg_haiku_20260302_014939](runs/ccb_mcp_crossorg_haiku_20260302_014939.md) | `ccb_mcp_crossorg` | `mcp-remote-direct` | 12 | 0.181 | 0.667 |
| [ccb_mcp_crossrepo_haiku_20260226_035617](runs/ccb_mcp_crossrepo_haiku_20260226_035617.md) | `ccb_mcp_crossrepo` | `mcp-remote-direct` | 1 | 0.767 | 1.000 |
| [ccb_mcp_crossrepo_haiku_20260226_035622_variance](runs/ccb_mcp_crossrepo_haiku_20260226_035622_variance.md) | `ccb_mcp_crossrepo` | `mcp-remote-direct` | 1 | 0.644 | 1.000 |
| [ccb_mcp_crossrepo_haiku_20260226_035628_variance](runs/ccb_mcp_crossrepo_haiku_20260226_035628_variance.md) | `ccb_mcp_crossrepo` | `mcp-remote-direct` | 1 | 0.767 | 1.000 |
| [ccb_mcp_crossrepo_haiku_20260226_035633_variance](runs/ccb_mcp_crossrepo_haiku_20260226_035633_variance.md) | `ccb_mcp_crossrepo` | `mcp-remote-direct` | 1 | 0.850 | 1.000 |
| [ccb_mcp_crossrepo_haiku_20260226_145828](runs/ccb_mcp_crossrepo_haiku_20260226_145828.md) | `ccb_mcp_crossrepo` | `baseline-local-direct` | 1 | 0.900 | 1.000 |
| [ccb_mcp_crossrepo_haiku_20260226_205845](runs/ccb_mcp_crossrepo_haiku_20260226_205845.md) | `ccb_mcp_crossrepo` | `baseline-local-direct` | 1 | 0.867 | 1.000 |
| [ccb_mcp_crossrepo_haiku_20260228_005303](runs/ccb_mcp_crossrepo_haiku_20260228_005303.md) | `ccb_mcp_crossrepo` | `baseline-local-direct` | 1 | 0.850 | 1.000 |
| [ccb_mcp_crossrepo_haiku_20260228_005303](runs/ccb_mcp_crossrepo_haiku_20260228_005303.md) | `ccb_mcp_crossrepo` | `mcp-remote-direct` | 1 | 0.633 | 1.000 |
| [ccb_mcp_crossrepo_haiku_20260301_191250](runs/ccb_mcp_crossrepo_haiku_20260301_191250.md) | `ccb_mcp_crossrepo` | `baseline-local-direct` | 11 | 0.253 | 1.000 |
| [ccb_mcp_crossrepo_haiku_20260301_191250](runs/ccb_mcp_crossrepo_haiku_20260301_191250.md) | `ccb_mcp_crossrepo` | `mcp-remote-direct` | 11 | 0.250 | 1.000 |
| [ccb_mcp_crossrepo_haiku_20260301_201320](runs/ccb_mcp_crossrepo_haiku_20260301_201320.md) | `ccb_mcp_crossrepo` | `baseline-local-direct` | 6 | 0.040 | 0.333 |
| [ccb_mcp_crossrepo_haiku_20260301_201320](runs/ccb_mcp_crossrepo_haiku_20260301_201320.md) | `ccb_mcp_crossrepo` | `mcp-remote-direct` | 6 | 0.049 | 0.333 |
| [ccb_mcp_crossrepo_haiku_20260302_014939](runs/ccb_mcp_crossrepo_haiku_20260302_014939.md) | `ccb_mcp_crossrepo` | `baseline-local-direct` | 11 | 0.293 | 1.000 |
| [ccb_mcp_crossrepo_haiku_20260302_014939](runs/ccb_mcp_crossrepo_haiku_20260302_014939.md) | `ccb_mcp_crossrepo` | `mcp-remote-direct` | 11 | 0.291 | 1.000 |
| [ccb_mcp_crossrepo_tracing_haiku_022126](runs/ccb_mcp_crossrepo_tracing_haiku_022126.md) | `ccb_mcp_crossrepo` | `baseline-local-artifact` | 3 | 0.941 | 1.000 |
| [ccb_mcp_crossrepo_tracing_haiku_022126](runs/ccb_mcp_crossrepo_tracing_haiku_022126.md) | `ccb_mcp_crossrepo` | `mcp-remote-artifact` | 3 | 0.899 | 1.000 |
| [ccb_mcp_crossrepo_tracing_haiku_20260224_181919](runs/ccb_mcp_crossrepo_tracing_haiku_20260224_181919.md) | `ccb_mcp_crossrepo` | `mcp-remote-artifact` | 2 | 0.287 | 1.000 |
| [ccb_mcp_crossrepo_tracing_haiku_20260225_011700](runs/ccb_mcp_crossrepo_tracing_haiku_20260225_011700.md) | `ccb_mcp_crossrepo` | `baseline-local-artifact` | 2 | 0.000 | 0.000 |
| [ccb_mcp_crossrepo_tracing_haiku_20260226_035617](runs/ccb_mcp_crossrepo_tracing_haiku_20260226_035617.md) | `ccb_mcp_crossrepo` | `mcp-remote-direct` | 3 | 0.669 | 1.000 |
| [ccb_mcp_crossrepo_tracing_haiku_20260226_035622_variance](runs/ccb_mcp_crossrepo_tracing_haiku_20260226_035622_variance.md) | `ccb_mcp_crossrepo` | `mcp-remote-direct` | 3 | 0.762 | 1.000 |
| [ccb_mcp_crossrepo_tracing_haiku_20260226_035628_variance](runs/ccb_mcp_crossrepo_tracing_haiku_20260226_035628_variance.md) | `ccb_mcp_crossrepo` | `mcp-remote-direct` | 3 | 0.756 | 1.000 |
| [ccb_mcp_crossrepo_tracing_haiku_20260226_035633_variance](runs/ccb_mcp_crossrepo_tracing_haiku_20260226_035633_variance.md) | `ccb_mcp_crossrepo` | `mcp-remote-direct` | 3 | 0.595 | 1.000 |
| [ccb_mcp_crossrepo_tracing_haiku_20260226_145828](runs/ccb_mcp_crossrepo_tracing_haiku_20260226_145828.md) | `ccb_mcp_crossrepo` | `baseline-local-direct` | 4 | 0.525 | 0.750 |
| [ccb_mcp_crossrepo_tracing_haiku_20260226_205845](runs/ccb_mcp_crossrepo_tracing_haiku_20260226_205845.md) | `ccb_mcp_crossrepo` | `baseline-local-direct` | 3 | 0.722 | 1.000 |
| [ccb_mcp_crossrepo_tracing_haiku_20260226_214446](runs/ccb_mcp_crossrepo_tracing_haiku_20260226_214446.md) | `ccb_mcp_crossrepo` | `baseline-local-direct` | 1 | 0.571 | 1.000 |
| [ccb_mcp_crossrepo_tracing_haiku_20260226_221038](runs/ccb_mcp_crossrepo_tracing_haiku_20260226_221038.md) | `ccb_mcp_crossrepo` | `mcp-remote-direct` | 1 | 0.800 | 1.000 |
| [ccb_mcp_crossrepo_tracing_haiku_20260228_022542](runs/ccb_mcp_crossrepo_tracing_haiku_20260228_022542.md) | `ccb_mcp_crossrepo` | `baseline-local-direct` | 9 | 0.538 | 0.778 |
| [ccb_mcp_crossrepo_tracing_haiku_20260228_025547](runs/ccb_mcp_crossrepo_tracing_haiku_20260228_025547.md) | `ccb_mcp_crossrepo` | `baseline-local-direct` | 2 | 0.096 | 0.500 |
| [ccb_mcp_crossrepo_tracing_haiku_20260228_025547](runs/ccb_mcp_crossrepo_tracing_haiku_20260228_025547.md) | `ccb_mcp_crossrepo` | `mcp-remote-direct` | 2 | 0.204 | 0.500 |
| [ccb_mcp_crossrepo_tracing_haiku_20260228_123206](runs/ccb_mcp_crossrepo_tracing_haiku_20260228_123206.md) | `ccb_mcp_crossrepo` | `baseline-local-direct` | 2 | 0.195 | 1.000 |
| [ccb_mcp_crossrepo_tracing_haiku_20260228_124521](runs/ccb_mcp_crossrepo_tracing_haiku_20260228_124521.md) | `ccb_mcp_crossrepo` | `mcp-remote-direct` | 3 | 1.000 | 1.000 |
| [ccb_mcp_crossrepo_tracing_haiku_20260301_191250](runs/ccb_mcp_crossrepo_tracing_haiku_20260301_191250.md) | `ccb_mcp_crossrepo` | `baseline-local-direct` | 9 | 0.075 | 0.556 |
| [ccb_mcp_crossrepo_tracing_haiku_20260301_191250](runs/ccb_mcp_crossrepo_tracing_haiku_20260301_191250.md) | `ccb_mcp_crossrepo` | `mcp-remote-direct` | 9 | 0.080 | 0.556 |
| [ccb_mcp_crossrepo_tracing_haiku_20260301_195739](runs/ccb_mcp_crossrepo_tracing_haiku_20260301_195739.md) | `ccb_mcp_crossrepo` | `baseline-local-direct` | 11 | 0.069 | 0.545 |
| [ccb_mcp_crossrepo_tracing_haiku_20260301_195739](runs/ccb_mcp_crossrepo_tracing_haiku_20260301_195739.md) | `ccb_mcp_crossrepo` | `mcp-remote-direct` | 11 | 0.081 | 0.545 |
| [ccb_mcp_crossrepo_tracing_haiku_20260301_231457](runs/ccb_mcp_crossrepo_tracing_haiku_20260301_231457.md) | `ccb_mcp_crossrepo` | `baseline-local-direct` | 2 | 0.819 | 1.000 |
| [ccb_mcp_crossrepo_tracing_haiku_20260301_231457](runs/ccb_mcp_crossrepo_tracing_haiku_20260301_231457.md) | `ccb_mcp_crossrepo` | `mcp-remote-direct` | 2 | 0.818 | 1.000 |
| [ccb_mcp_crossrepo_tracing_haiku_20260302_013655](runs/ccb_mcp_crossrepo_tracing_haiku_20260302_013655.md) | `ccb_mcp_crossrepo` | `mcp-remote-direct` | 1 | 0.333 | 1.000 |
| [ccb_mcp_crossrepo_tracing_haiku_20260302_014939](runs/ccb_mcp_crossrepo_tracing_haiku_20260302_014939.md) | `ccb_mcp_crossrepo` | `baseline-local-direct` | 4 | 0.509 | 0.750 |
| [ccb_mcp_crossrepo_tracing_haiku_20260302_014939](runs/ccb_mcp_crossrepo_tracing_haiku_20260302_014939.md) | `ccb_mcp_crossrepo` | `mcp-remote-direct` | 4 | 0.427 | 0.750 |
| [ccb_mcp_crossrepo_tracing_haiku_20260302_022538](runs/ccb_mcp_crossrepo_tracing_haiku_20260302_022538.md) | `ccb_mcp_crossrepo` | `baseline-local-direct` | 2 | 0.875 | 1.000 |
| [ccb_mcp_crossrepo_tracing_haiku_20260302_022538](runs/ccb_mcp_crossrepo_tracing_haiku_20260302_022538.md) | `ccb_mcp_crossrepo` | `mcp-remote-direct` | 2 | 0.834 | 1.000 |
| [ccb_mcp_crossrepo_tracing_haiku_20260302_022540](runs/ccb_mcp_crossrepo_tracing_haiku_20260302_022540.md) | `ccb_mcp_crossrepo` | `mcp-remote-direct` | 1 | 0.500 | 1.000 |
| [ccb_mcp_domain_haiku_20260224_181919](runs/ccb_mcp_domain_haiku_20260224_181919.md) | `ccb_mcp_domain` | `mcp-remote-artifact` | 3 | 0.529 | 1.000 |
| [ccb_mcp_domain_haiku_20260225_011700](runs/ccb_mcp_domain_haiku_20260225_011700.md) | `ccb_mcp_domain` | `baseline-local-artifact` | 3 | 0.000 | 0.000 |
| [ccb_mcp_domain_haiku_20260226_035617](runs/ccb_mcp_domain_haiku_20260226_035617.md) | `ccb_mcp_domain` | `mcp-remote-direct` | 6 | 0.559 | 1.000 |
| [ccb_mcp_domain_haiku_20260226_035622_variance](runs/ccb_mcp_domain_haiku_20260226_035622_variance.md) | `ccb_mcp_domain` | `mcp-remote-direct` | 6 | 0.508 | 1.000 |
| [ccb_mcp_domain_haiku_20260226_035628_variance](runs/ccb_mcp_domain_haiku_20260226_035628_variance.md) | `ccb_mcp_domain` | `mcp-remote-direct` | 6 | 0.627 | 1.000 |
| [ccb_mcp_domain_haiku_20260226_035633_variance](runs/ccb_mcp_domain_haiku_20260226_035633_variance.md) | `ccb_mcp_domain` | `mcp-remote-direct` | 6 | 0.543 | 1.000 |
| [ccb_mcp_domain_haiku_20260226_145828](runs/ccb_mcp_domain_haiku_20260226_145828.md) | `ccb_mcp_domain` | `baseline-local-direct` | 6 | 0.618 | 1.000 |
| [ccb_mcp_domain_haiku_20260226_205845](runs/ccb_mcp_domain_haiku_20260226_205845.md) | `ccb_mcp_domain` | `baseline-local-direct` | 6 | 0.604 | 1.000 |
| [ccb_mcp_domain_haiku_20260226_222632](runs/ccb_mcp_domain_haiku_20260226_222632.md) | `ccb_mcp_domain` | `baseline-local-direct` | 1 | 0.800 | 1.000 |
| [ccb_mcp_domain_haiku_20260226_222632](runs/ccb_mcp_domain_haiku_20260226_222632.md) | `ccb_mcp_domain` | `mcp-remote-direct` | 1 | 0.800 | 1.000 |
| [ccb_mcp_domain_haiku_20260226_224414](runs/ccb_mcp_domain_haiku_20260226_224414.md) | `ccb_mcp_domain` | `baseline-local-direct` | 1 | 0.800 | 1.000 |
| [ccb_mcp_domain_haiku_20260226_224414](runs/ccb_mcp_domain_haiku_20260226_224414.md) | `ccb_mcp_domain` | `mcp-remote-direct` | 1 | 0.800 | 1.000 |
| [ccb_mcp_domain_haiku_20260228_021254](runs/ccb_mcp_domain_haiku_20260228_021254.md) | `ccb_mcp_domain` | `baseline-local-direct` | 10 | 0.567 | 1.000 |
| [ccb_mcp_domain_haiku_20260228_025547](runs/ccb_mcp_domain_haiku_20260228_025547.md) | `ccb_mcp_domain` | `baseline-local-direct` | 3 | 0.418 | 1.000 |
| [ccb_mcp_domain_haiku_20260228_025547](runs/ccb_mcp_domain_haiku_20260228_025547.md) | `ccb_mcp_domain` | `mcp-remote-direct` | 3 | 0.444 | 1.000 |
| [ccb_mcp_domain_haiku_20260228_123206](runs/ccb_mcp_domain_haiku_20260228_123206.md) | `ccb_mcp_domain` | `baseline-local-direct` | 3 | 0.424 | 1.000 |
| [ccb_mcp_domain_haiku_20260301_191250](runs/ccb_mcp_domain_haiku_20260301_191250.md) | `ccb_mcp_domain` | `baseline-local-direct` | 8 | 0.186 | 0.875 |
| [ccb_mcp_domain_haiku_20260301_191250](runs/ccb_mcp_domain_haiku_20260301_191250.md) | `ccb_mcp_domain` | `mcp-remote-direct` | 8 | 0.184 | 0.875 |
| [ccb_mcp_domain_haiku_20260301_195739](runs/ccb_mcp_domain_haiku_20260301_195739.md) | `ccb_mcp_domain` | `baseline-local-direct` | 10 | 0.132 | 0.800 |
| [ccb_mcp_domain_haiku_20260301_195739](runs/ccb_mcp_domain_haiku_20260301_195739.md) | `ccb_mcp_domain` | `mcp-remote-direct` | 10 | 0.159 | 0.800 |
| [ccb_mcp_domain_haiku_20260302_014939](runs/ccb_mcp_domain_haiku_20260302_014939.md) | `ccb_mcp_domain` | `baseline-local-direct` | 2 | 0.080 | 0.500 |
| [ccb_mcp_domain_haiku_20260302_014939](runs/ccb_mcp_domain_haiku_20260302_014939.md) | `ccb_mcp_domain` | `mcp-remote-direct` | 2 | 0.000 | 0.000 |
| [ccb_mcp_incident_haiku_022126](runs/ccb_mcp_incident_haiku_022126.md) | `ccb_mcp_incident` | `baseline-local-artifact` | 1 | 0.500 | 1.000 |
| [ccb_mcp_incident_haiku_022126](runs/ccb_mcp_incident_haiku_022126.md) | `ccb_mcp_incident` | `mcp-remote-artifact` | 1 | 1.000 | 1.000 |
| [ccb_mcp_incident_haiku_20260224_181919](runs/ccb_mcp_incident_haiku_20260224_181919.md) | `ccb_mcp_incident` | `mcp-remote-artifact` | 3 | 0.782 | 1.000 |
| [ccb_mcp_incident_haiku_20260225_011700](runs/ccb_mcp_incident_haiku_20260225_011700.md) | `ccb_mcp_incident` | `baseline-local-artifact` | 3 | 0.167 | 0.333 |
| [ccb_mcp_incident_haiku_20260226_035617](runs/ccb_mcp_incident_haiku_20260226_035617.md) | `ccb_mcp_incident` | `mcp-remote-direct` | 6 | 0.753 | 1.000 |
| [ccb_mcp_incident_haiku_20260226_035622_variance](runs/ccb_mcp_incident_haiku_20260226_035622_variance.md) | `ccb_mcp_incident` | `mcp-remote-direct` | 6 | 0.632 | 1.000 |
| [ccb_mcp_incident_haiku_20260226_035628_variance](runs/ccb_mcp_incident_haiku_20260226_035628_variance.md) | `ccb_mcp_incident` | `mcp-remote-direct` | 6 | 0.661 | 1.000 |
| [ccb_mcp_incident_haiku_20260226_035633_variance](runs/ccb_mcp_incident_haiku_20260226_035633_variance.md) | `ccb_mcp_incident` | `mcp-remote-direct` | 6 | 0.669 | 1.000 |
| [ccb_mcp_incident_haiku_20260226_145828](runs/ccb_mcp_incident_haiku_20260226_145828.md) | `ccb_mcp_incident` | `baseline-local-direct` | 6 | 0.672 | 1.000 |
| [ccb_mcp_incident_haiku_20260226_205845](runs/ccb_mcp_incident_haiku_20260226_205845.md) | `ccb_mcp_incident` | `baseline-local-direct` | 6 | 0.722 | 1.000 |
| [ccb_mcp_incident_haiku_20260226_224414](runs/ccb_mcp_incident_haiku_20260226_224414.md) | `ccb_mcp_incident` | `baseline-local-direct` | 1 | 0.667 | 1.000 |
| [ccb_mcp_incident_haiku_20260226_224414](runs/ccb_mcp_incident_haiku_20260226_224414.md) | `ccb_mcp_incident` | `mcp-remote-direct` | 1 | 0.800 | 1.000 |
| [ccb_mcp_incident_haiku_20260228_021904](runs/ccb_mcp_incident_haiku_20260228_021904.md) | `ccb_mcp_incident` | `baseline-local-direct` | 11 | 0.566 | 0.818 |
| [ccb_mcp_incident_haiku_20260228_025547](runs/ccb_mcp_incident_haiku_20260228_025547.md) | `ccb_mcp_incident` | `baseline-local-direct` | 3 | 0.746 | 1.000 |
| [ccb_mcp_incident_haiku_20260228_025547](runs/ccb_mcp_incident_haiku_20260228_025547.md) | `ccb_mcp_incident` | `mcp-remote-direct` | 3 | 0.779 | 1.000 |
| [ccb_mcp_incident_haiku_20260228_123206](runs/ccb_mcp_incident_haiku_20260228_123206.md) | `ccb_mcp_incident` | `baseline-local-direct` | 3 | 0.723 | 1.000 |
| [ccb_mcp_incident_haiku_20260228_124521](runs/ccb_mcp_incident_haiku_20260228_124521.md) | `ccb_mcp_incident` | `mcp-remote-direct` | 1 | 1.000 | 1.000 |
| [ccb_mcp_incident_haiku_20260301_191250](runs/ccb_mcp_incident_haiku_20260301_191250.md) | `ccb_mcp_incident` | `baseline-local-direct` | 6 | 0.349 | 1.000 |
| [ccb_mcp_incident_haiku_20260301_191250](runs/ccb_mcp_incident_haiku_20260301_191250.md) | `ccb_mcp_incident` | `mcp-remote-direct` | 6 | 0.357 | 1.000 |
| [ccb_mcp_incident_haiku_20260301_195739](runs/ccb_mcp_incident_haiku_20260301_195739.md) | `ccb_mcp_incident` | `baseline-local-direct` | 9 | 0.314 | 0.778 |
| [ccb_mcp_incident_haiku_20260301_195739](runs/ccb_mcp_incident_haiku_20260301_195739.md) | `ccb_mcp_incident` | `mcp-remote-direct` | 9 | 0.410 | 0.889 |
| [ccb_mcp_incident_haiku_20260302_013655](runs/ccb_mcp_incident_haiku_20260302_013655.md) | `ccb_mcp_incident` | `mcp-remote-direct` | 1 | 1.000 | 1.000 |
| [ccb_mcp_incident_haiku_20260302_014939](runs/ccb_mcp_incident_haiku_20260302_014939.md) | `ccb_mcp_incident` | `baseline-local-direct` | 3 | 0.222 | 0.333 |
| [ccb_mcp_incident_haiku_20260302_014939](runs/ccb_mcp_incident_haiku_20260302_014939.md) | `ccb_mcp_incident` | `mcp-remote-direct` | 3 | 0.167 | 0.333 |
| [ccb_mcp_incident_haiku_20260302_022540](runs/ccb_mcp_incident_haiku_20260302_022540.md) | `ccb_mcp_incident` | `mcp-remote-direct` | 1 | 0.933 | 1.000 |
| [ccb_mcp_migration_haiku_20260226_035617](runs/ccb_mcp_migration_haiku_20260226_035617.md) | `ccb_mcp_migration` | `baseline-local-direct` | 1 | 1.000 | 1.000 |
| [ccb_mcp_migration_haiku_20260226_035617](runs/ccb_mcp_migration_haiku_20260226_035617.md) | `ccb_mcp_migration` | `mcp-remote-direct` | 1 | 1.000 | 1.000 |
| [ccb_mcp_migration_haiku_20260226_035622_variance](runs/ccb_mcp_migration_haiku_20260226_035622_variance.md) | `ccb_mcp_migration` | `baseline-local-direct` | 1 | 1.000 | 1.000 |
| [ccb_mcp_migration_haiku_20260226_035622_variance](runs/ccb_mcp_migration_haiku_20260226_035622_variance.md) | `ccb_mcp_migration` | `mcp-remote-direct` | 1 | 1.000 | 1.000 |
| [ccb_mcp_migration_haiku_20260226_035628_variance](runs/ccb_mcp_migration_haiku_20260226_035628_variance.md) | `ccb_mcp_migration` | `baseline-local-direct` | 1 | 1.000 | 1.000 |
| [ccb_mcp_migration_haiku_20260226_035628_variance](runs/ccb_mcp_migration_haiku_20260226_035628_variance.md) | `ccb_mcp_migration` | `mcp-remote-direct` | 1 | 1.000 | 1.000 |
| [ccb_mcp_migration_haiku_20260226_035633_variance](runs/ccb_mcp_migration_haiku_20260226_035633_variance.md) | `ccb_mcp_migration` | `baseline-local-direct` | 1 | 1.000 | 1.000 |
| [ccb_mcp_migration_haiku_20260226_035633_variance](runs/ccb_mcp_migration_haiku_20260226_035633_variance.md) | `ccb_mcp_migration` | `mcp-remote-direct` | 1 | 1.000 | 1.000 |
| [ccb_mcp_migration_haiku_20260226_145828](runs/ccb_mcp_migration_haiku_20260226_145828.md) | `ccb_mcp_migration` | `baseline-local-direct` | 5 | 0.033 | 0.400 |
| [ccb_mcp_migration_haiku_20260226_214446](runs/ccb_mcp_migration_haiku_20260226_214446.md) | `ccb_mcp_migration` | `baseline-local-direct` | 3 | 0.930 | 1.000 |
| [ccb_mcp_migration_haiku_20260226_221038](runs/ccb_mcp_migration_haiku_20260226_221038.md) | `ccb_mcp_migration` | `mcp-remote-direct` | 3 | 0.917 | 1.000 |
| [ccb_mcp_migration_haiku_20260226_231458](runs/ccb_mcp_migration_haiku_20260226_231458.md) | `ccb_mcp_migration` | `baseline-local-direct` | 3 | 0.639 | 1.000 |
| [ccb_mcp_migration_haiku_20260226_231458](runs/ccb_mcp_migration_haiku_20260226_231458.md) | `ccb_mcp_migration` | `mcp-remote-direct` | 3 | 0.771 | 1.000 |
| [ccb_mcp_migration_haiku_20260228_011912](runs/ccb_mcp_migration_haiku_20260228_011912.md) | `ccb_mcp_migration` | `baseline-local-direct` | 7 | 0.801 | 1.000 |
| [ccb_mcp_migration_haiku_20260228_011912](runs/ccb_mcp_migration_haiku_20260228_011912.md) | `ccb_mcp_migration` | `mcp-remote-direct` | 7 | 0.804 | 1.000 |
| [ccb_mcp_migration_haiku_20260301_191250](runs/ccb_mcp_migration_haiku_20260301_191250.md) | `ccb_mcp_migration` | `baseline-local-direct` | 12 | 0.115 | 0.917 |
| [ccb_mcp_migration_haiku_20260301_191250](runs/ccb_mcp_migration_haiku_20260301_191250.md) | `ccb_mcp_migration` | `mcp-remote-direct` | 12 | 0.135 | 0.833 |
| [ccb_mcp_migration_haiku_20260301_195739](runs/ccb_mcp_migration_haiku_20260301_195739.md) | `ccb_mcp_migration` | `baseline-local-direct` | 13 | 0.100 | 0.692 |
| [ccb_mcp_migration_haiku_20260301_195739](runs/ccb_mcp_migration_haiku_20260301_195739.md) | `ccb_mcp_migration` | `mcp-remote-direct` | 13 | 0.094 | 0.615 |
| [ccb_mcp_migration_haiku_20260301_231457](runs/ccb_mcp_migration_haiku_20260301_231457.md) | `ccb_mcp_migration` | `baseline-local-direct` | 5 | 0.570 | 1.000 |
| [ccb_mcp_migration_haiku_20260301_231457](runs/ccb_mcp_migration_haiku_20260301_231457.md) | `ccb_mcp_migration` | `mcp-remote-direct` | 6 | 0.632 | 1.000 |
| [ccb_mcp_migration_haiku_20260301_235018](runs/ccb_mcp_migration_haiku_20260301_235018.md) | `ccb_mcp_migration` | `baseline-local-direct` | 1 | 0.741 | 1.000 |
| [ccb_mcp_migration_haiku_20260302_014939](runs/ccb_mcp_migration_haiku_20260302_014939.md) | `ccb_mcp_migration` | `baseline-local-direct` | 7 | 0.492 | 0.857 |
| [ccb_mcp_migration_haiku_20260302_014939](runs/ccb_mcp_migration_haiku_20260302_014939.md) | `ccb_mcp_migration` | `mcp-remote-direct` | 7 | 0.612 | 0.857 |
| [ccb_mcp_migration_haiku_20260302_022538](runs/ccb_mcp_migration_haiku_20260302_022538.md) | `ccb_mcp_migration` | `baseline-local-direct` | 6 | 0.583 | 1.000 |
| [ccb_mcp_migration_haiku_20260302_022538](runs/ccb_mcp_migration_haiku_20260302_022538.md) | `ccb_mcp_migration` | `mcp-remote-direct` | 6 | 0.765 | 1.000 |
| [ccb_mcp_onboarding_haiku_022126](runs/ccb_mcp_onboarding_haiku_022126.md) | `ccb_mcp_onboarding` | `baseline-local-artifact` | 1 | 1.000 | 1.000 |
| [ccb_mcp_onboarding_haiku_022126](runs/ccb_mcp_onboarding_haiku_022126.md) | `ccb_mcp_onboarding` | `mcp-remote-artifact` | 1 | 1.000 | 1.000 |
| [ccb_mcp_onboarding_haiku_20260224_181919](runs/ccb_mcp_onboarding_haiku_20260224_181919.md) | `ccb_mcp_onboarding` | `mcp-remote-artifact` | 4 | 0.843 | 1.000 |
| [ccb_mcp_onboarding_haiku_20260225_011700](runs/ccb_mcp_onboarding_haiku_20260225_011700.md) | `ccb_mcp_onboarding` | `baseline-local-artifact` | 4 | 0.000 | 0.000 |
| [ccb_mcp_onboarding_haiku_20260226_035617](runs/ccb_mcp_onboarding_haiku_20260226_035617.md) | `ccb_mcp_onboarding` | `mcp-remote-direct` | 4 | 0.501 | 1.000 |
| [ccb_mcp_onboarding_haiku_20260226_035622_variance](runs/ccb_mcp_onboarding_haiku_20260226_035622_variance.md) | `ccb_mcp_onboarding` | `mcp-remote-direct` | 4 | 0.452 | 1.000 |
| [ccb_mcp_onboarding_haiku_20260226_035628_variance](runs/ccb_mcp_onboarding_haiku_20260226_035628_variance.md) | `ccb_mcp_onboarding` | `mcp-remote-direct` | 4 | 0.550 | 1.000 |
| [ccb_mcp_onboarding_haiku_20260226_035633_variance](runs/ccb_mcp_onboarding_haiku_20260226_035633_variance.md) | `ccb_mcp_onboarding` | `mcp-remote-direct` | 4 | 0.472 | 1.000 |
| [ccb_mcp_onboarding_haiku_20260226_145828](runs/ccb_mcp_onboarding_haiku_20260226_145828.md) | `ccb_mcp_onboarding` | `baseline-local-direct` | 3 | 0.539 | 1.000 |
| [ccb_mcp_onboarding_haiku_20260226_205845](runs/ccb_mcp_onboarding_haiku_20260226_205845.md) | `ccb_mcp_onboarding` | `baseline-local-direct` | 3 | 0.540 | 1.000 |
| [ccb_mcp_onboarding_haiku_20260226_231458](runs/ccb_mcp_onboarding_haiku_20260226_231458.md) | `ccb_mcp_onboarding` | `baseline-local-direct` | 1 | 0.473 | 1.000 |
| [ccb_mcp_onboarding_haiku_20260226_231458](runs/ccb_mcp_onboarding_haiku_20260226_231458.md) | `ccb_mcp_onboarding` | `mcp-remote-direct` | 1 | 0.432 | 1.000 |
| [ccb_mcp_onboarding_haiku_20260227_132300](runs/ccb_mcp_onboarding_haiku_20260227_132300.md) | `ccb_mcp_onboarding` | `baseline-local-direct` | 14 | 0.936 | 1.000 |
| [ccb_mcp_onboarding_haiku_20260227_132300](runs/ccb_mcp_onboarding_haiku_20260227_132300.md) | `ccb_mcp_onboarding` | `mcp-remote-direct` | 12 | 1.000 | 1.000 |
| [ccb_mcp_onboarding_haiku_20260227_132304](runs/ccb_mcp_onboarding_haiku_20260227_132304.md) | `ccb_mcp_onboarding` | `baseline-local-direct` | 14 | 0.864 | 0.929 |
| [ccb_mcp_onboarding_haiku_20260227_132304](runs/ccb_mcp_onboarding_haiku_20260227_132304.md) | `ccb_mcp_onboarding` | `mcp-remote-direct` | 12 | 1.000 | 1.000 |
| [ccb_mcp_onboarding_haiku_20260228_023118](runs/ccb_mcp_onboarding_haiku_20260228_023118.md) | `ccb_mcp_onboarding` | `baseline-local-direct` | 25 | 0.784 | 0.960 |
| [ccb_mcp_onboarding_haiku_20260228_025547](runs/ccb_mcp_onboarding_haiku_20260228_025547.md) | `ccb_mcp_onboarding` | `baseline-local-direct` | 4 | 0.843 | 1.000 |
| [ccb_mcp_onboarding_haiku_20260228_025547](runs/ccb_mcp_onboarding_haiku_20260228_025547.md) | `ccb_mcp_onboarding` | `mcp-remote-direct` | 4 | 0.843 | 1.000 |
| [ccb_mcp_onboarding_haiku_20260228_123206](runs/ccb_mcp_onboarding_haiku_20260228_123206.md) | `ccb_mcp_onboarding` | `baseline-local-direct` | 4 | 0.779 | 1.000 |
| [ccb_mcp_onboarding_haiku_20260228_124521](runs/ccb_mcp_onboarding_haiku_20260228_124521.md) | `ccb_mcp_onboarding` | `mcp-remote-direct` | 17 | 0.931 | 1.000 |
| [ccb_mcp_onboarding_haiku_20260301_191250](runs/ccb_mcp_onboarding_haiku_20260301_191250.md) | `ccb_mcp_onboarding` | `baseline-local-direct` | 2 | 0.008 | 0.500 |
| [ccb_mcp_onboarding_haiku_20260301_191250](runs/ccb_mcp_onboarding_haiku_20260301_191250.md) | `ccb_mcp_onboarding` | `mcp-remote-direct` | 2 | 0.015 | 0.500 |
| [ccb_mcp_onboarding_haiku_20260301_195739](runs/ccb_mcp_onboarding_haiku_20260301_195739.md) | `ccb_mcp_onboarding` | `baseline-local-direct` | 2 | 0.036 | 0.500 |
| [ccb_mcp_onboarding_haiku_20260301_195739](runs/ccb_mcp_onboarding_haiku_20260301_195739.md) | `ccb_mcp_onboarding` | `mcp-remote-direct` | 2 | 0.015 | 0.500 |
| [ccb_mcp_onboarding_haiku_20260301_231457](runs/ccb_mcp_onboarding_haiku_20260301_231457.md) | `ccb_mcp_onboarding` | `baseline-local-direct` | 8 | 0.626 | 0.875 |
| [ccb_mcp_onboarding_haiku_20260301_231457](runs/ccb_mcp_onboarding_haiku_20260301_231457.md) | `ccb_mcp_onboarding` | `mcp-remote-direct` | 8 | 0.735 | 1.000 |
| [ccb_mcp_onboarding_haiku_20260302_014939](runs/ccb_mcp_onboarding_haiku_20260302_014939.md) | `ccb_mcp_onboarding` | `baseline-local-direct` | 1 | 0.962 | 1.000 |
| [ccb_mcp_onboarding_haiku_20260302_014939](runs/ccb_mcp_onboarding_haiku_20260302_014939.md) | `ccb_mcp_onboarding` | `mcp-remote-direct` | 1 | 1.000 | 1.000 |
| [ccb_mcp_onboarding_haiku_20260302_022538](runs/ccb_mcp_onboarding_haiku_20260302_022538.md) | `ccb_mcp_onboarding` | `baseline-local-direct` | 1 | 0.928 | 1.000 |
| [ccb_mcp_onboarding_haiku_20260302_022538](runs/ccb_mcp_onboarding_haiku_20260302_022538.md) | `ccb_mcp_onboarding` | `mcp-remote-direct` | 1 | 1.000 | 1.000 |
| [ccb_mcp_onboarding_haiku_20260302_030627](runs/ccb_mcp_onboarding_haiku_20260302_030627.md) | `ccb_mcp_onboarding` | `mcp-remote-direct` | 2 | 1.000 | 1.000 |
| [ccb_mcp_org_haiku_20260224_181919](runs/ccb_mcp_org_haiku_20260224_181919.md) | `ccb_mcp_org` | `mcp-remote-artifact` | 2 | 0.705 | 1.000 |
| [ccb_mcp_org_haiku_20260225_011700](runs/ccb_mcp_org_haiku_20260225_011700.md) | `ccb_mcp_org` | `baseline-local-artifact` | 2 | 0.500 | 1.000 |
| [ccb_mcp_org_haiku_20260226_035617](runs/ccb_mcp_org_haiku_20260226_035617.md) | `ccb_mcp_org` | `mcp-remote-direct` | 3 | 0.503 | 1.000 |
| [ccb_mcp_org_haiku_20260226_035622_variance](runs/ccb_mcp_org_haiku_20260226_035622_variance.md) | `ccb_mcp_org` | `mcp-remote-direct` | 3 | 0.557 | 1.000 |
| [ccb_mcp_org_haiku_20260226_035628_variance](runs/ccb_mcp_org_haiku_20260226_035628_variance.md) | `ccb_mcp_org` | `mcp-remote-direct` | 3 | 0.497 | 1.000 |
| [ccb_mcp_org_haiku_20260226_035633_variance](runs/ccb_mcp_org_haiku_20260226_035633_variance.md) | `ccb_mcp_org` | `mcp-remote-direct` | 3 | 0.515 | 1.000 |
| [ccb_mcp_org_haiku_20260226_145828](runs/ccb_mcp_org_haiku_20260226_145828.md) | `ccb_mcp_org` | `baseline-local-direct` | 3 | 0.385 | 1.000 |
| [ccb_mcp_org_haiku_20260226_205845](runs/ccb_mcp_org_haiku_20260226_205845.md) | `ccb_mcp_org` | `baseline-local-direct` | 3 | 0.404 | 1.000 |
| [ccb_mcp_org_haiku_20260228_010402](runs/ccb_mcp_org_haiku_20260228_010402.md) | `ccb_mcp_org` | `baseline-local-direct` | 5 | 0.543 | 1.000 |
| [ccb_mcp_org_haiku_20260228_010402](runs/ccb_mcp_org_haiku_20260228_010402.md) | `ccb_mcp_org` | `mcp-remote-direct` | 5 | 0.592 | 1.000 |
| [ccb_mcp_org_haiku_20260228_051032](runs/ccb_mcp_org_haiku_20260228_051032.md) | `ccb_mcp_org` | `baseline-local-direct` | 1 | 0.720 | 1.000 |
| [ccb_mcp_org_haiku_20260228_123206](runs/ccb_mcp_org_haiku_20260228_123206.md) | `ccb_mcp_org` | `baseline-local-direct` | 2 | 0.683 | 1.000 |
| [ccb_mcp_org_haiku_20260228_133005](runs/ccb_mcp_org_haiku_20260228_133005.md) | `ccb_mcp_org` | `baseline-local-direct` | 1 | 0.574 | 1.000 |
| [ccb_mcp_org_haiku_20260301_191250](runs/ccb_mcp_org_haiku_20260301_191250.md) | `ccb_mcp_org` | `baseline-local-direct` | 13 | 0.000 | 0.000 |
| [ccb_mcp_org_haiku_20260301_191250](runs/ccb_mcp_org_haiku_20260301_191250.md) | `ccb_mcp_org` | `mcp-remote-direct` | 13 | 0.000 | 0.000 |
| [ccb_mcp_org_haiku_20260301_195739](runs/ccb_mcp_org_haiku_20260301_195739.md) | `ccb_mcp_org` | `baseline-local-direct` | 15 | 0.308 | 0.933 |
| [ccb_mcp_org_haiku_20260301_195739](runs/ccb_mcp_org_haiku_20260301_195739.md) | `ccb_mcp_org` | `mcp-remote-direct` | 15 | 0.338 | 0.933 |
| [ccb_mcp_org_haiku_20260302_014939](runs/ccb_mcp_org_haiku_20260302_014939.md) | `ccb_mcp_org` | `baseline-local-direct` | 2 | 0.282 | 1.000 |
| [ccb_mcp_org_haiku_20260302_014939](runs/ccb_mcp_org_haiku_20260302_014939.md) | `ccb_mcp_org` | `mcp-remote-direct` | 2 | 0.274 | 1.000 |
| [ccb_mcp_platform_haiku_20260226_035617](runs/ccb_mcp_platform_haiku_20260226_035617.md) | `ccb_mcp_platform` | `baseline-local-direct` | 2 | 0.744 | 1.000 |
| [ccb_mcp_platform_haiku_20260226_035617](runs/ccb_mcp_platform_haiku_20260226_035617.md) | `ccb_mcp_platform` | `mcp-remote-direct` | 3 | 0.544 | 1.000 |
| [ccb_mcp_platform_haiku_20260226_035622_variance](runs/ccb_mcp_platform_haiku_20260226_035622_variance.md) | `ccb_mcp_platform` | `baseline-local-direct` | 2 | 0.728 | 1.000 |
| [ccb_mcp_platform_haiku_20260226_035622_variance](runs/ccb_mcp_platform_haiku_20260226_035622_variance.md) | `ccb_mcp_platform` | `mcp-remote-direct` | 3 | 0.572 | 1.000 |
| [ccb_mcp_platform_haiku_20260226_035628_variance](runs/ccb_mcp_platform_haiku_20260226_035628_variance.md) | `ccb_mcp_platform` | `baseline-local-direct` | 2 | 0.744 | 1.000 |
| [ccb_mcp_platform_haiku_20260226_035628_variance](runs/ccb_mcp_platform_haiku_20260226_035628_variance.md) | `ccb_mcp_platform` | `mcp-remote-direct` | 3 | 0.635 | 1.000 |
| [ccb_mcp_platform_haiku_20260226_035633_variance](runs/ccb_mcp_platform_haiku_20260226_035633_variance.md) | `ccb_mcp_platform` | `baseline-local-direct` | 2 | 0.717 | 1.000 |
| [ccb_mcp_platform_haiku_20260226_035633_variance](runs/ccb_mcp_platform_haiku_20260226_035633_variance.md) | `ccb_mcp_platform` | `mcp-remote-direct` | 3 | 0.552 | 1.000 |
| [ccb_mcp_platform_haiku_20260226_145828](runs/ccb_mcp_platform_haiku_20260226_145828.md) | `ccb_mcp_platform` | `baseline-local-direct` | 2 | 0.292 | 0.500 |
| [ccb_mcp_platform_haiku_20260226_205845](runs/ccb_mcp_platform_haiku_20260226_205845.md) | `ccb_mcp_platform` | `baseline-local-direct` | 1 | 0.583 | 1.000 |
| [ccb_mcp_platform_haiku_20260226_214446](runs/ccb_mcp_platform_haiku_20260226_214446.md) | `ccb_mcp_platform` | `baseline-local-direct` | 1 | 0.632 | 1.000 |
| [ccb_mcp_platform_haiku_20260226_221038](runs/ccb_mcp_platform_haiku_20260226_221038.md) | `ccb_mcp_platform` | `mcp-remote-direct` | 1 | 0.556 | 1.000 |
| [ccb_mcp_platform_haiku_20260228_010919](runs/ccb_mcp_platform_haiku_20260228_010919.md) | `ccb_mcp_platform` | `baseline-local-direct` | 5 | 0.678 | 1.000 |
| [ccb_mcp_platform_haiku_20260228_010919](runs/ccb_mcp_platform_haiku_20260228_010919.md) | `ccb_mcp_platform` | `mcp-remote-direct` | 5 | 0.597 | 1.000 |
| [ccb_mcp_platform_haiku_20260301_191250](runs/ccb_mcp_platform_haiku_20260301_191250.md) | `ccb_mcp_platform` | `baseline-local-direct` | 11 | 0.177 | 0.818 |
| [ccb_mcp_platform_haiku_20260301_191250](runs/ccb_mcp_platform_haiku_20260301_191250.md) | `ccb_mcp_platform` | `mcp-remote-direct` | 11 | 0.192 | 0.909 |
| [ccb_mcp_platform_haiku_20260301_195739](runs/ccb_mcp_platform_haiku_20260301_195739.md) | `ccb_mcp_platform` | `baseline-local-direct` | 16 | 0.184 | 0.938 |
| [ccb_mcp_platform_haiku_20260301_195739](runs/ccb_mcp_platform_haiku_20260301_195739.md) | `ccb_mcp_platform` | `mcp-remote-direct` | 16 | 0.147 | 0.938 |
| [ccb_mcp_platform_haiku_20260302_014939](runs/ccb_mcp_platform_haiku_20260302_014939.md) | `ccb_mcp_platform` | `baseline-local-direct` | 5 | 0.241 | 1.000 |
| [ccb_mcp_platform_haiku_20260302_014939](runs/ccb_mcp_platform_haiku_20260302_014939.md) | `ccb_mcp_platform` | `mcp-remote-direct` | 5 | 0.173 | 1.000 |
| [ccb_mcp_security_haiku_022126](runs/ccb_mcp_security_haiku_022126.md) | `ccb_mcp_security` | `baseline-local-artifact` | 2 | 0.500 | 1.000 |
| [ccb_mcp_security_haiku_022126](runs/ccb_mcp_security_haiku_022126.md) | `ccb_mcp_security` | `mcp-remote-artifact` | 2 | 0.821 | 1.000 |
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
| [ccb_mcp_security_haiku_20260226_145828](runs/ccb_mcp_security_haiku_20260226_145828.md) | `ccb_mcp_security` | `baseline-local-direct` | 3 | 0.641 | 1.000 |
| [ccb_mcp_security_haiku_20260226_205845](runs/ccb_mcp_security_haiku_20260226_205845.md) | `ccb_mcp_security` | `baseline-local-direct` | 3 | 0.682 | 1.000 |
| [ccb_mcp_security_haiku_20260228_012337](runs/ccb_mcp_security_haiku_20260228_012337.md) | `ccb_mcp_security` | `baseline-local-direct` | 7 | 0.420 | 0.714 |
| [ccb_mcp_security_haiku_20260228_012337](runs/ccb_mcp_security_haiku_20260228_012337.md) | `ccb_mcp_security` | `mcp-remote-direct` | 5 | 0.690 | 1.000 |
| [ccb_mcp_security_haiku_20260228_020502](runs/ccb_mcp_security_haiku_20260228_020502.md) | `ccb_mcp_security` | `baseline-local-direct` | 9 | 0.496 | 0.778 |
| [ccb_mcp_security_haiku_20260228_025547](runs/ccb_mcp_security_haiku_20260228_025547.md) | `ccb_mcp_security` | `baseline-local-direct` | 4 | 0.662 | 1.000 |
| [ccb_mcp_security_haiku_20260228_025547](runs/ccb_mcp_security_haiku_20260228_025547.md) | `ccb_mcp_security` | `mcp-remote-direct` | 4 | 0.811 | 1.000 |
| [ccb_mcp_security_haiku_20260228_123206](runs/ccb_mcp_security_haiku_20260228_123206.md) | `ccb_mcp_security` | `baseline-local-direct` | 4 | 0.731 | 1.000 |
| [ccb_mcp_security_haiku_20260301_201904](runs/ccb_mcp_security_haiku_20260301_201904.md) | `ccb_mcp_security` | `baseline-local-artifact` | 19 | 0.320 | 0.842 |
| [ccb_mcp_security_haiku_20260301_201904](runs/ccb_mcp_security_haiku_20260301_201904.md) | `ccb_mcp_security` | `mcp-remote-artifact` | 20 | 0.494 | 1.000 |
| [ccb_mcp_security_haiku_20260301_231457](runs/ccb_mcp_security_haiku_20260301_231457.md) | `ccb_mcp_security` | `baseline-local-direct` | 3 | 0.786 | 1.000 |
| [ccb_mcp_security_haiku_20260301_231457](runs/ccb_mcp_security_haiku_20260301_231457.md) | `ccb_mcp_security` | `mcp-remote-direct` | 4 | 0.753 | 1.000 |
| [ccb_mcp_security_haiku_20260301_235018](runs/ccb_mcp_security_haiku_20260301_235018.md) | `ccb_mcp_security` | `baseline-local-direct` | 1 | 0.673 | 1.000 |
| [ccb_mcp_security_haiku_20260302_014939](runs/ccb_mcp_security_haiku_20260302_014939.md) | `ccb_mcp_security` | `baseline-local-direct` | 6 | 0.718 | 1.000 |
| [ccb_mcp_security_haiku_20260302_014939](runs/ccb_mcp_security_haiku_20260302_014939.md) | `ccb_mcp_security` | `mcp-remote-direct` | 6 | 0.731 | 1.000 |
| [ccb_mcp_security_haiku_20260302_022538](runs/ccb_mcp_security_haiku_20260302_022538.md) | `ccb_mcp_security` | `baseline-local-direct` | 4 | 0.767 | 1.000 |
| [ccb_mcp_security_haiku_20260302_022538](runs/ccb_mcp_security_haiku_20260302_022538.md) | `ccb_mcp_security` | `mcp-remote-direct` | 4 | 0.737 | 1.000 |
| [ccb_refactor_haiku_20260301_133910](runs/ccb_refactor_haiku_20260301_133910.md) | `ccb_refactor` | `baseline-local-direct` | 1 | 0.800 | 1.000 |
| [ccb_secure_haiku_022326](runs/ccb_secure_haiku_022326.md) | `ccb_secure` | `baseline-local-direct` | 18 | 0.688 | 0.944 |
| [ccb_secure_haiku_022326](runs/ccb_secure_haiku_022326.md) | `ccb_secure` | `mcp-remote-direct` | 18 | 0.705 | 1.000 |
| [ccb_secure_haiku_20260224_213146](runs/ccb_secure_haiku_20260224_213146.md) | `ccb_secure` | `baseline-local-direct` | 2 | 0.500 | 1.000 |
| [ccb_secure_haiku_20260224_213146](runs/ccb_secure_haiku_20260224_213146.md) | `ccb_secure` | `mcp-remote-direct` | 2 | 0.250 | 0.500 |
| [ccb_secure_haiku_20260228_124521](runs/ccb_secure_haiku_20260228_124521.md) | `ccb_secure` | `mcp-remote-direct` | 2 | 0.555 | 1.000 |
| [ccb_test_haiku_20260224_180149](runs/ccb_test_haiku_20260224_180149.md) | `ccb_test` | `baseline-local-direct` | 11 | 0.486 | 0.727 |
| [ccb_test_haiku_20260224_180149](runs/ccb_test_haiku_20260224_180149.md) | `ccb_test` | `mcp-remote-direct` | 11 | 0.387 | 0.727 |
| [ccb_test_haiku_20260226_015500_backfill](runs/ccb_test_haiku_20260226_015500_backfill.md) | `ccb_test` | `baseline-local-direct` | 1 | 0.370 | 1.000 |
| [ccb_test_haiku_20260226_015500_backfill](runs/ccb_test_haiku_20260226_015500_backfill.md) | `ccb_test` | `mcp-remote-direct` | 1 | 0.900 | 1.000 |
| [ccb_test_haiku_20260228_124521](runs/ccb_test_haiku_20260228_124521.md) | `ccb_test` | `mcp-remote-direct` | 4 | 0.985 | 1.000 |
| [ccb_test_haiku_20260301_230048](runs/ccb_test_haiku_20260301_230048.md) | `ccb_test` | `baseline-local-direct` | 13 | 0.644 | 0.923 |
| [ccb_test_haiku_20260301_230048](runs/ccb_test_haiku_20260301_230048.md) | `ccb_test` | `mcp-remote-direct` | 6 | 0.798 | 1.000 |
| [ccb_test_haiku_20260302_004743](runs/ccb_test_haiku_20260302_004743.md) | `ccb_test` | `baseline-local-direct` | 3 | 0.660 | 1.000 |
| [ccb_test_haiku_20260302_005945](runs/ccb_test_haiku_20260302_005945.md) | `ccb_test` | `baseline-local-direct` | 1 | 0.500 | 1.000 |
| [ccb_test_haiku_20260302_005945](runs/ccb_test_haiku_20260302_005945.md) | `ccb_test` | `mcp-remote-direct` | 1 | 0.370 | 1.000 |
| [ccb_test_haiku_20260302_005947](runs/ccb_test_haiku_20260302_005947.md) | `ccb_test` | `baseline-local-direct` | 5 | 0.732 | 1.000 |
| [ccb_test_haiku_20260302_013712](runs/ccb_test_haiku_20260302_013712.md) | `ccb_test` | `baseline-local-direct` | 1 | 0.000 | 0.000 |
| [ccb_test_haiku_20260302_013713](runs/ccb_test_haiku_20260302_013713.md) | `ccb_test` | `mcp-remote-direct` | 1 | 0.000 | 0.000 |
| [ccb_test_haiku_20260302_020340](runs/ccb_test_haiku_20260302_020340.md) | `ccb_test` | `mcp-remote-direct` | 6 | 0.450 | 1.000 |
| [ccb_test_haiku_20260302_021358](runs/ccb_test_haiku_20260302_021358.md) | `ccb_test` | `mcp-remote-direct` | 1 | 0.620 | 1.000 |
| [ccb_test_haiku_20260302_021447](runs/ccb_test_haiku_20260302_021447.md) | `ccb_test` | `baseline-local-direct` | 7 | 0.627 | 1.000 |
| [ccb_test_haiku_20260302_022542](runs/ccb_test_haiku_20260302_022542.md) | `ccb_test` | `baseline-local-direct` | 1 | 0.440 | 1.000 |
| [ccb_test_haiku_20260302_022542](runs/ccb_test_haiku_20260302_022542.md) | `ccb_test` | `mcp-remote-direct` | 1 | 0.290 | 1.000 |
| [ccb_test_haiku_20260302_022544](runs/ccb_test_haiku_20260302_022544.md) | `ccb_test` | `baseline-local-direct` | 4 | 0.775 | 1.000 |
| [ccb_test_haiku_20260302_022552](runs/ccb_test_haiku_20260302_022552.md) | `ccb_test` | `baseline-local-direct` | 2 | 0.240 | 0.500 |
| [ccb_test_haiku_20260302_022553](runs/ccb_test_haiku_20260302_022553.md) | `ccb_test` | `mcp-remote-direct` | 1 | 0.000 | 0.000 |
| [ccb_test_haiku_20260302_041201](runs/ccb_test_haiku_20260302_041201.md) | `ccb_test` | `mcp-remote-direct` | 3 | 0.503 | 1.000 |
| [ccb_understand_haiku_022426](runs/ccb_understand_haiku_022426.md) | `ccb_understand` | `baseline-local-direct` | 13 | 0.592 | 0.692 |
| [ccb_understand_haiku_022426](runs/ccb_understand_haiku_022426.md) | `ccb_understand` | `mcp-remote-direct` | 13 | 0.841 | 1.000 |
| [ccb_understand_haiku_20260227_132300](runs/ccb_understand_haiku_20260227_132300.md) | `ccb_understand` | `baseline-local-direct` | 14 | 1.000 | 1.000 |
| [ccb_understand_haiku_20260227_132300](runs/ccb_understand_haiku_20260227_132300.md) | `ccb_understand` | `mcp-remote-direct` | 12 | 0.858 | 0.917 |
| [ccb_understand_haiku_20260227_132304](runs/ccb_understand_haiku_20260227_132304.md) | `ccb_understand` | `baseline-local-direct` | 14 | 0.864 | 0.929 |
| [ccb_understand_haiku_20260227_132304](runs/ccb_understand_haiku_20260227_132304.md) | `ccb_understand` | `mcp-remote-direct` | 12 | 0.942 | 1.000 |
| [ccb_understand_haiku_20260228_124521](runs/ccb_understand_haiku_20260228_124521.md) | `ccb_understand` | `mcp-remote-direct` | 4 | 0.823 | 1.000 |
| [debug_haiku_20260228_230112](runs/debug_haiku_20260228_230112.md) | `ccb_debug` | `baseline-local-direct` | 10 | 0.833 | 1.000 |
| [debug_haiku_20260228_230112](runs/debug_haiku_20260228_230112.md) | `ccb_debug` | `mcp-remote-direct` | 8 | 0.730 | 1.000 |
| [debug_haiku_20260228_230648](runs/debug_haiku_20260228_230648.md) | `ccb_debug` | `baseline-local-direct` | 11 | 0.864 | 1.000 |
| [debug_haiku_20260228_230648](runs/debug_haiku_20260228_230648.md) | `ccb_debug` | `mcp-remote-direct` | 2 | 1.000 | 1.000 |
| [debug_haiku_20260228_231033](runs/debug_haiku_20260228_231033.md) | `ccb_debug` | `baseline-local-direct` | 11 | 0.857 | 1.000 |
| [debug_haiku_20260228_231033](runs/debug_haiku_20260228_231033.md) | `ccb_debug` | `mcp-remote-direct` | 10 | 0.804 | 1.000 |
| [debug_haiku_20260301_021540](runs/debug_haiku_20260301_021540.md) | `ccb_debug` | `baseline-local-direct` | 11 | 0.847 | 1.000 |
| [debug_haiku_20260301_021540](runs/debug_haiku_20260301_021540.md) | `ccb_debug` | `mcp-remote-direct` | 11 | 0.813 | 1.000 |
| [debug_haiku_20260301_030159](runs/debug_haiku_20260301_030159.md) | `ccb_debug` | `baseline-local-direct` | 11 | 0.837 | 1.000 |
| [debug_haiku_20260301_030159](runs/debug_haiku_20260301_030159.md) | `ccb_debug` | `mcp-remote-direct` | 11 | 0.801 | 1.000 |
| [debug_haiku_20260301_031844](runs/debug_haiku_20260301_031844.md) | `ccb_debug` | `baseline-local-direct` | 11 | 0.806 | 1.000 |
| [debug_haiku_20260301_031844](runs/debug_haiku_20260301_031844.md) | `ccb_debug` | `mcp-remote-direct` | 11 | 0.750 | 1.000 |
| [debug_haiku_20260301_033225](runs/debug_haiku_20260301_033225.md) | `ccb_debug` | `baseline-local-direct` | 9 | 0.444 | 0.889 |
| [debug_haiku_20260301_033225](runs/debug_haiku_20260301_033225.md) | `ccb_debug` | `mcp-remote-direct` | 9 | 0.389 | 0.778 |
| [debug_haiku_20260301_035030](runs/debug_haiku_20260301_035030.md) | `ccb_debug` | `baseline-local-direct` | 9 | 0.333 | 0.667 |
| [debug_haiku_20260301_035030](runs/debug_haiku_20260301_035030.md) | `ccb_debug` | `mcp-remote-direct` | 9 | 0.278 | 0.556 |
| [debug_haiku_20260301_040300](runs/debug_haiku_20260301_040300.md) | `ccb_debug` | `baseline-local-direct` | 9 | 0.500 | 1.000 |
| [debug_haiku_20260301_040300](runs/debug_haiku_20260301_040300.md) | `ccb_debug` | `mcp-remote-direct` | 9 | 0.389 | 0.778 |
| [debug_haiku_20260301_071226](runs/debug_haiku_20260301_071226.md) | `ccb_debug` | `baseline-local-direct` | 11 | 0.842 | 1.000 |
| [debug_haiku_20260301_071226](runs/debug_haiku_20260301_071226.md) | `ccb_debug` | `mcp-remote-direct` | 11 | 0.841 | 1.000 |
| [design_haiku_20260301_022406](runs/design_haiku_20260301_022406.md) | `ccb_design` | `baseline-local-direct` | 20 | 0.766 | 1.000 |
| [design_haiku_20260301_022406](runs/design_haiku_20260301_022406.md) | `ccb_design` | `mcp-remote-direct` | 20 | 0.734 | 1.000 |
| [design_haiku_20260301_031030](runs/design_haiku_20260301_031030.md) | `ccb_design` | `baseline-local-direct` | 20 | 0.762 | 0.950 |
| [design_haiku_20260301_031030](runs/design_haiku_20260301_031030.md) | `ccb_design` | `mcp-remote-direct` | 20 | 0.747 | 1.000 |
| [design_haiku_20260301_031845](runs/design_haiku_20260301_031845.md) | `ccb_design` | `baseline-local-direct` | 20 | 0.807 | 1.000 |
| [design_haiku_20260301_031845](runs/design_haiku_20260301_031845.md) | `ccb_design` | `mcp-remote-direct` | 19 | 0.701 | 1.000 |
| [design_haiku_20260301_071227](runs/design_haiku_20260301_071227.md) | `ccb_design` | `baseline-local-direct` | 20 | 0.770 | 1.000 |
| [design_haiku_20260301_071227](runs/design_haiku_20260301_071227.md) | `ccb_design` | `mcp-remote-direct` | 20 | 0.699 | 0.950 |
| [document_haiku_20260223_164240](runs/document_haiku_20260223_164240.md) | `ccb_document` | `baseline-local-direct` | 19 | 0.851 | 1.000 |
| [document_haiku_20260223_164240](runs/document_haiku_20260223_164240.md) | `ccb_document` | `mcp-remote-direct` | 20 | 0.822 | 1.000 |
| [document_haiku_20260226_013910](runs/document_haiku_20260226_013910.md) | `ccb_document` | `baseline-local-direct` | 1 | 1.000 | 1.000 |
| [document_haiku_20260301_031846](runs/document_haiku_20260301_031846.md) | `ccb_document` | `baseline-local-direct` | 20 | 0.875 | 1.000 |
| [document_haiku_20260301_031846](runs/document_haiku_20260301_031846.md) | `ccb_document` | `mcp-remote-direct` | 20 | 0.908 | 1.000 |
| [document_haiku_20260301_071228](runs/document_haiku_20260301_071228.md) | `ccb_document` | `baseline-local-direct` | 20 | 0.845 | 1.000 |
| [document_haiku_20260301_071228](runs/document_haiku_20260301_071228.md) | `ccb_document` | `mcp-remote-direct` | 20 | 0.898 | 1.000 |
| [feature_haiku_20260228_190114](runs/feature_haiku_20260228_190114.md) | `ccb_feature` | `baseline-local-direct` | 5 | 0.507 | 0.600 |
| [feature_haiku_20260228_190114](runs/feature_haiku_20260228_190114.md) | `ccb_feature` | `mcp-remote-direct` | 6 | 0.550 | 0.833 |
| [feature_haiku_20260228_211127](runs/feature_haiku_20260228_211127.md) | `ccb_feature` | `baseline-local-direct` | 17 | 0.694 | 1.000 |
| [feature_haiku_20260228_211127](runs/feature_haiku_20260228_211127.md) | `ccb_feature` | `mcp-remote-direct` | 16 | 0.618 | 0.938 |
| [feature_haiku_20260228_220733](runs/feature_haiku_20260228_220733.md) | `ccb_feature` | `baseline-local-direct` | 4 | 0.375 | 0.500 |
| [feature_haiku_20260228_220733](runs/feature_haiku_20260228_220733.md) | `ccb_feature` | `mcp-remote-direct` | 4 | 0.542 | 0.750 |
| [feature_haiku_20260228_230114](runs/feature_haiku_20260228_230114.md) | `ccb_feature` | `mcp-remote-direct` | 1 | 0.280 | 1.000 |
| [feature_haiku_20260228_231035](runs/feature_haiku_20260228_231035.md) | `ccb_feature` | `mcp-remote-direct` | 4 | 0.333 | 0.750 |
| [feature_haiku_20260228_231041](runs/feature_haiku_20260228_231041.md) | `ccb_feature` | `baseline-local-direct` | 4 | 0.557 | 1.000 |
| [feature_haiku_20260301_023333](runs/feature_haiku_20260301_023333.md) | `ccb_feature` | `baseline-local-direct` | 8 | 0.835 | 1.000 |
| [feature_haiku_20260301_023333](runs/feature_haiku_20260301_023333.md) | `ccb_feature` | `mcp-remote-direct` | 6 | 0.867 | 1.000 |
| [feature_haiku_20260301_031848](runs/feature_haiku_20260301_031848.md) | `ccb_feature` | `baseline-local-direct` | 19 | 0.665 | 0.947 |
| [feature_haiku_20260301_031848](runs/feature_haiku_20260301_031848.md) | `ccb_feature` | `mcp-remote-direct` | 18 | 0.644 | 0.889 |
| [feature_haiku_20260301_071229](runs/feature_haiku_20260301_071229.md) | `ccb_feature` | `baseline-local-direct` | 20 | 0.656 | 0.900 |
| [feature_haiku_20260301_071229](runs/feature_haiku_20260301_071229.md) | `ccb_feature` | `mcp-remote-direct` | 19 | 0.608 | 0.895 |
| [feature_haiku_vscode_rerun_20260301_023018](runs/feature_haiku_vscode_rerun_20260301_023018.md) | `ccb_feature` | `baseline-local-direct` | 1 | 0.500 | 1.000 |
| [fix_haiku_20260301_190026](runs/fix_haiku_20260301_190026.md) | `ccb_fix` | `baseline-local-direct` | 2 | 0.000 | 0.000 |
| [fix_haiku_20260301_190026](runs/fix_haiku_20260301_190026.md) | `ccb_fix` | `mcp-remote-direct` | 2 | 0.000 | 0.000 |
| [refactor_haiku_20260228_210652](runs/refactor_haiku_20260228_210652.md) | `ccb_refactor` | `baseline-local-direct` | 1 | 0.750 | 1.000 |
| [refactor_haiku_20260228_210652](runs/refactor_haiku_20260228_210652.md) | `ccb_refactor` | `mcp-remote-direct` | 1 | 0.790 | 1.000 |
| [refactor_haiku_20260228_231037](runs/refactor_haiku_20260228_231037.md) | `ccb_refactor` | `mcp-remote-direct` | 4 | 0.592 | 1.000 |
| [refactor_haiku_20260228_231045](runs/refactor_haiku_20260228_231045.md) | `ccb_refactor` | `baseline-local-direct` | 4 | 0.463 | 1.000 |
| [refactor_haiku_20260301_010758](runs/refactor_haiku_20260301_010758.md) | `ccb_refactor` | `baseline-local-direct` | 20 | 0.791 | 0.950 |
| [refactor_haiku_20260301_010758](runs/refactor_haiku_20260301_010758.md) | `ccb_refactor` | `mcp-remote-direct` | 20 | 0.737 | 0.950 |
| [refactor_haiku_20260301_023530](runs/refactor_haiku_20260301_023530.md) | `ccb_refactor` | `baseline-local-direct` | 10 | 0.950 | 1.000 |
| [refactor_haiku_20260301_023530](runs/refactor_haiku_20260301_023530.md) | `ccb_refactor` | `mcp-remote-direct` | 10 | 0.717 | 0.900 |
| [refactor_haiku_20260301_031849](runs/refactor_haiku_20260301_031849.md) | `ccb_refactor` | `baseline-local-direct` | 20 | 0.755 | 1.000 |
| [refactor_haiku_20260301_031849](runs/refactor_haiku_20260301_031849.md) | `ccb_refactor` | `mcp-remote-direct` | 20 | 0.671 | 1.000 |
| [refactor_haiku_20260301_071230](runs/refactor_haiku_20260301_071230.md) | `ccb_refactor` | `baseline-local-direct` | 20 | 0.789 | 0.950 |
| [refactor_haiku_20260301_071230](runs/refactor_haiku_20260301_071230.md) | `ccb_refactor` | `mcp-remote-direct` | 19 | 0.713 | 1.000 |
| [secure_haiku_20260223_232545](runs/secure_haiku_20260223_232545.md) | `ccb_secure` | `baseline-local-direct` | 20 | 0.669 | 0.950 |
| [secure_haiku_20260223_232545](runs/secure_haiku_20260223_232545.md) | `ccb_secure` | `mcp-remote-direct` | 18 | 0.705 | 1.000 |
| [secure_haiku_20260224_011825](runs/secure_haiku_20260224_011825.md) | `ccb_secure` | `mcp-remote-direct` | 2 | 0.500 | 0.500 |
| [secure_haiku_20260301_031850](runs/secure_haiku_20260301_031850.md) | `ccb_secure` | `baseline-local-direct` | 20 | 0.737 | 0.950 |
| [secure_haiku_20260301_031850](runs/secure_haiku_20260301_031850.md) | `ccb_secure` | `mcp-remote-direct` | 20 | 0.728 | 1.000 |
| [secure_haiku_20260301_071231](runs/secure_haiku_20260301_071231.md) | `ccb_secure` | `baseline-local-direct` | 20 | 0.712 | 1.000 |
| [secure_haiku_20260301_071231](runs/secure_haiku_20260301_071231.md) | `ccb_secure` | `mcp-remote-direct` | 20 | 0.767 | 1.000 |
| [test_haiku_20260224_011816](runs/test_haiku_20260224_011816.md) | `ccb_test` | `baseline-local-direct` | 11 | 0.295 | 0.545 |
| [test_haiku_20260224_011816](runs/test_haiku_20260224_011816.md) | `ccb_test` | `mcp-remote-direct` | 11 | 0.262 | 0.455 |
| [test_haiku_20260228_230654](runs/test_haiku_20260228_230654.md) | `ccb_test` | `mcp-remote-direct` | 1 | 0.000 | 0.000 |
| [test_haiku_20260228_231039](runs/test_haiku_20260228_231039.md) | `ccb_test` | `mcp-remote-direct` | 1 | 0.200 | 1.000 |
| [test_haiku_20260301_031851](runs/test_haiku_20260301_031851.md) | `ccb_test` | `baseline-local-direct` | 17 | 0.571 | 0.824 |
| [test_haiku_20260301_031851](runs/test_haiku_20260301_031851.md) | `ccb_test` | `mcp-remote-direct` | 8 | 0.769 | 1.000 |
| [test_haiku_20260301_071232](runs/test_haiku_20260301_071232.md) | `ccb_test` | `baseline-local-direct` | 17 | 0.569 | 0.824 |
| [test_haiku_20260301_071232](runs/test_haiku_20260301_071232.md) | `ccb_test` | `mcp-remote-direct` | 8 | 0.780 | 1.000 |
| [test_haiku_20260301_192246](runs/test_haiku_20260301_192246.md) | `ccb_test` | `baseline-local-direct` | 4 | 0.128 | 0.250 |
| [test_haiku_20260301_192246](runs/test_haiku_20260301_192246.md) | `ccb_test` | `mcp-remote-direct` | 3 | 0.000 | 0.000 |
| [understand_haiku_20260224_001815](runs/understand_haiku_20260224_001815.md) | `ccb_understand` | `baseline-local-direct` | 20 | 0.533 | 0.650 |
| [understand_haiku_20260224_001815](runs/understand_haiku_20260224_001815.md) | `ccb_understand` | `mcp-remote-direct` | 20 | 0.679 | 0.850 |
| [understand_haiku_20260225_211346](runs/understand_haiku_20260225_211346.md) | `ccb_understand` | `baseline-local-direct` | 7 | 0.789 | 1.000 |
| [understand_haiku_20260225_211346](runs/understand_haiku_20260225_211346.md) | `ccb_understand` | `mcp-remote-direct` | 7 | 0.870 | 1.000 |
| [understand_haiku_20260301_031852](runs/understand_haiku_20260301_031852.md) | `ccb_understand` | `baseline-local-direct` | 20 | 0.728 | 0.850 |
| [understand_haiku_20260301_031852](runs/understand_haiku_20260301_031852.md) | `ccb_understand` | `mcp-remote-direct` | 20 | 0.832 | 0.950 |
| [understand_haiku_20260301_071233](runs/understand_haiku_20260301_071233.md) | `ccb_understand` | `baseline-local-direct` | 20 | 0.884 | 1.000 |
| [understand_haiku_20260301_071233](runs/understand_haiku_20260301_071233.md) | `ccb_understand` | `mcp-remote-direct` | 20 | 0.850 | 1.000 |

</details>

`index.html`, `data/official_results.json`, and `audits/*.json` provide GitHub-auditable artifacts.