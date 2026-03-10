# Official Results Browser

This bundle is generated from `runs/analysis/` and includes only valid scored tasks (`passed`/`failed` with numeric reward) that pass config-specific validity checks.
Mean reward and pass rate are reported separately. Mixed scorer-family reward means are convenience summaries, not calibrated cross-family comparisons.

Generated: `2026-03-10T23:32:58.567545+00:00`

## Local Browse

```bash
python3 scripts/export_official_results.py --serve
```

Suite-level views are deduplicated to the latest row per `suite + config + task_name`.
Historical reruns/backfills remain available in `data/official_results.json` under `all_tasks`.

## Suite/Config Summary

| Suite | Config | Valid Tasks | Min Required | Mean Reward | Pass Rate | Coverage |
|---|---|---:|---:|---:|---:|---|
| [ccb_codereview](suites/ccb_codereview.md) | `sourcegraph_base` | 3 | 3 | 0.893 | 1.000 | ok |
| [ccb_crossrepo](suites/ccb_crossrepo.md) | `baseline` | 5 | 5 | 0.200 | 0.200 | ok |
| [ccb_crossrepo](suites/ccb_crossrepo.md) | `sourcegraph_base` | 4 | 5 | 0.000 | 0.000 | FLAG: below minimum |
| [ccb_crossrepo](suites/ccb_crossrepo.md) | `sourcegraph_full` | 2 | 5 | 0.000 | 0.000 | FLAG: below minimum |
| [ccb_dependeval](suites/ccb_dependeval.md) | `baseline` | 6 | 6 | 0.561 | 0.667 | ok |
| [ccb_dibench](suites/ccb_dibench.md) | `sourcegraph_base` | 4 | 4 | 0.250 | 0.250 | ok |
| [ccb_dibench](suites/ccb_dibench.md) | `sourcegraph_full` | 4 | 4 | 0.250 | 0.250 | ok |
| [ccb_investigation](suites/ccb_investigation.md) | `baseline` | 4 | 4 | 0.970 | 1.000 | ok |
| [ccb_investigation](suites/ccb_investigation.md) | `sourcegraph_base` | 4 | 4 | 0.745 | 1.000 | ok |
| [ccb_investigation](suites/ccb_investigation.md) | `sourcegraph_full` | 4 | 4 | 0.885 | 1.000 | ok |
| [ccb_k8sdocs](suites/ccb_k8sdocs.md) | `baseline` | 1 | 5 | 0.900 | 1.000 | FLAG: below minimum |
| [ccb_k8sdocs](suites/ccb_k8sdocs.md) | `sourcegraph_base` | 5 | 5 | 0.920 | 1.000 | ok |
| [ccb_largerepo](suites/ccb_largerepo.md) | `baseline` | 4 | 4 | 0.000 | 0.000 | ok |
| [ccb_linuxflbench](suites/ccb_linuxflbench.md) | `sourcegraph_base` | 5 | 5 | 0.740 | 1.000 | ok |
| [ccb_linuxflbench](suites/ccb_linuxflbench.md) | `sourcegraph_full` | 5 | 5 | 0.860 | 1.000 | ok |
| [ccb_locobench](suites/ccb_locobench.md) | `baseline` | 46 | 46 | 0.488 | 1.000 | ok |
| [ccb_locobench](suites/ccb_locobench.md) | `sourcegraph_base` | 8 | 46 | 0.502 | 1.000 | FLAG: below minimum |
| [ccb_locobench](suites/ccb_locobench.md) | `sourcegraph_full` | 27 | 46 | 0.503 | 1.000 | FLAG: below minimum |
| [ccb_mcp_crossorg](suites/ccb_mcp_crossorg.md) | `mcp-remote-artifact` | 2 | 2 | 1.000 | 1.000 | ok |
| [ccb_mcp_crossrepo](suites/ccb_mcp_crossrepo.md) | `mcp-remote-artifact` | 3 | 3 | 0.941 | 1.000 | ok |
| [ccb_mcp_incident](suites/ccb_mcp_incident.md) | `mcp-remote-artifact` | 1 | 1 | 1.000 | 1.000 | ok |
| [ccb_mcp_migration](suites/ccb_mcp_migration.md) | `baseline-local-direct` | 26 | 41 | 0.317 | 0.808 | FLAG: below minimum |
| [ccb_mcp_migration](suites/ccb_mcp_migration.md) | `mcp-remote-direct` | 41 | 41 | 0.464 | 0.902 | ok |
| [ccb_mcp_onboarding](suites/ccb_mcp_onboarding.md) | `mcp-remote-artifact` | 3 | 3 | 0.722 | 1.000 | ok |
| [ccb_mcp_platform](suites/ccb_mcp_platform.md) | `mcp-remote-artifact` | 1 | 1 | 0.875 | 1.000 | ok |
| [ccb_mcp_security](suites/ccb_mcp_security.md) | `baseline-local-direct` | 10 | 18 | 0.000 | 0.000 | FLAG: below minimum |
| [ccb_mcp_security](suites/ccb_mcp_security.md) | `mcp-remote-artifact` | 2 | 18 | 0.875 | 1.000 | FLAG: below minimum |
| [ccb_mcp_security](suites/ccb_mcp_security.md) | `mcp-remote-direct` | 18 | 18 | 0.000 | 0.000 | ok |
| [ccb_misc](suites/ccb_misc.md) | `baseline-local-artifact` | 6 | 67 | 0.525 | 1.000 | FLAG: below minimum |
| [ccb_misc](suites/ccb_misc.md) | `baseline-local-direct` | 5 | 67 | 0.273 | 0.800 | FLAG: below minimum |
| [ccb_misc](suites/ccb_misc.md) | `mcp` | 7 | 67 | 0.286 | 0.286 | FLAG: below minimum |
| [ccb_misc](suites/ccb_misc.md) | `mcp-remote-artifact` | 67 | 67 | 0.617 | 0.896 | ok |
| [ccb_misc](suites/ccb_misc.md) | `mcp-remote-direct` | 6 | 67 | 0.450 | 0.833 | FLAG: below minimum |
| [ccb_pytorch](suites/ccb_pytorch.md) | `baseline` | 14 | 14 | 0.643 | 0.643 | ok |
| [ccb_pytorch](suites/ccb_pytorch.md) | `sourcegraph_base` | 12 | 14 | 0.080 | 0.083 | FLAG: below minimum |
| [ccb_pytorch](suites/ccb_pytorch.md) | `sourcegraph_full` | 13 | 14 | 0.458 | 0.462 | FLAG: below minimum |
| [ccb_sdlc_representative](suites/ccb_sdlc_representative.md) | `baseline` | 8 | 13 | 0.098 | 0.125 | FLAG: below minimum |
| [ccb_sdlc_representative](suites/ccb_sdlc_representative.md) | `sourcegraph_full` | 13 | 13 | 0.367 | 0.462 | ok |
| [ccb_swebenchpro](suites/ccb_swebenchpro.md) | `baseline` | 9 | 25 | 0.667 | 0.667 | FLAG: below minimum |
| [ccb_swebenchpro](suites/ccb_swebenchpro.md) | `sourcegraph` | 1 | 25 | 0.000 | 0.000 | FLAG: below minimum |
| [ccb_swebenchpro](suites/ccb_swebenchpro.md) | `sourcegraph_base` | 25 | 25 | 0.560 | 0.560 | ok |
| [ccb_swebenchpro](suites/ccb_swebenchpro.md) | `sourcegraph_full` | 6 | 25 | 0.833 | 0.833 | FLAG: below minimum |
| [ccb_sweperf](suites/ccb_sweperf.md) | `baseline` | 3 | 3 | 0.000 | 0.000 | ok |
| [ccb_sweperf](suites/ccb_sweperf.md) | `sourcegraph_base` | 3 | 3 | 0.000 | 0.000 | ok |
| [ccb_tac](suites/ccb_tac.md) | `baseline` | 8 | 8 | 0.000 | 0.000 | ok |
| [ccb_tac](suites/ccb_tac.md) | `sourcegraph_base` | 6 | 8 | 0.000 | 0.000 | FLAG: below minimum |
| [ccb_tac](suites/ccb_tac.md) | `sourcegraph_full` | 2 | 8 | 0.000 | 0.000 | FLAG: below minimum |
| [csb_org_compliance](suites/csb_org_compliance.md) | `baseline-local-artifact` | 3 | 122 | 0.125 | 0.333 | FLAG: below minimum |
| [csb_org_compliance](suites/csb_org_compliance.md) | `baseline-local-direct` | 20 | 122 | 0.314 | 0.950 | FLAG: below minimum |
| [csb_org_compliance](suites/csb_org_compliance.md) | `mcp-remote-artifact` | 3 | 122 | 0.247 | 0.333 | FLAG: below minimum |
| [csb_org_compliance](suites/csb_org_compliance.md) | `mcp-remote-direct` | 122 | 122 | 0.299 | 0.770 | ok |
| [csb_org_crossorg](suites/csb_org_crossorg.md) | `baseline-local-artifact` | 5 | 105 | 0.114 | 0.400 | FLAG: below minimum |
| [csb_org_crossorg](suites/csb_org_crossorg.md) | `baseline-local-direct` | 18 | 105 | 0.261 | 0.722 | FLAG: below minimum |
| [csb_org_crossorg](suites/csb_org_crossorg.md) | `mcp-remote-artifact` | 5 | 105 | 0.154 | 0.400 | FLAG: below minimum |
| [csb_org_crossorg](suites/csb_org_crossorg.md) | `mcp-remote-direct` | 105 | 105 | 0.181 | 0.533 | ok |
| [csb_org_crossrepo](suites/csb_org_crossrepo.md) | `baseline-local-artifact` | 7 | 220 | 0.538 | 0.571 | FLAG: below minimum |
| [csb_org_crossrepo](suites/csb_org_crossrepo.md) | `baseline-local-direct` | 37 | 220 | 0.324 | 0.838 | FLAG: below minimum |
| [csb_org_crossrepo](suites/csb_org_crossrepo.md) | `mcp-remote-artifact` | 7 | 220 | 0.577 | 0.857 | FLAG: below minimum |
| [csb_org_crossrepo](suites/csb_org_crossrepo.md) | `mcp-remote-direct` | 220 | 220 | 0.335 | 0.800 | ok |
| [csb_org_domain](suites/csb_org_domain.md) | `baseline-local-artifact` | 3 | 93 | 0.000 | 0.000 | FLAG: below minimum |
| [csb_org_domain](suites/csb_org_domain.md) | `baseline-local-direct` | 20 | 93 | 0.355 | 0.900 | FLAG: below minimum |
| [csb_org_domain](suites/csb_org_domain.md) | `mcp-remote-artifact` | 3 | 93 | 0.529 | 1.000 | FLAG: below minimum |
| [csb_org_domain](suites/csb_org_domain.md) | `mcp-remote-direct` | 93 | 93 | 0.320 | 0.817 | ok |
| [csb_org_incident](suites/csb_org_incident.md) | `baseline-local-artifact` | 4 | 101 | 0.250 | 0.500 | FLAG: below minimum |
| [csb_org_incident](suites/csb_org_incident.md) | `baseline-local-direct` | 20 | 101 | 0.507 | 0.800 | FLAG: below minimum |
| [csb_org_incident](suites/csb_org_incident.md) | `mcp-remote-artifact` | 4 | 101 | 0.837 | 1.000 | FLAG: below minimum |
| [csb_org_incident](suites/csb_org_incident.md) | `mcp-remote-direct` | 101 | 101 | 0.608 | 0.931 | ok |
| [csb_org_migration](suites/csb_org_migration.md) | `baseline-local-artifact` | 2 | 118 | 0.284 | 0.500 | FLAG: below minimum |
| [csb_org_migration](suites/csb_org_migration.md) | `baseline-local-direct` | 28 | 118 | 0.371 | 0.929 | FLAG: below minimum |
| [csb_org_migration](suites/csb_org_migration.md) | `mcp-remote-artifact` | 4 | 118 | 0.307 | 0.500 | FLAG: below minimum |
| [csb_org_migration](suites/csb_org_migration.md) | `mcp-remote-direct` | 118 | 118 | 0.408 | 0.839 | ok |
| [csb_org_onboarding](suites/csb_org_onboarding.md) | `baseline-local-artifact` | 7 | 169 | 0.274 | 0.429 | FLAG: below minimum |
| [csb_org_onboarding](suites/csb_org_onboarding.md) | `baseline-local-direct` | 28 | 169 | 0.703 | 0.857 | FLAG: below minimum |
| [csb_org_onboarding](suites/csb_org_onboarding.md) | `mcp-remote-artifact` | 7 | 169 | 0.815 | 1.000 | FLAG: below minimum |
| [csb_org_onboarding](suites/csb_org_onboarding.md) | `mcp-remote-direct` | 169 | 169 | 0.799 | 0.970 | ok |
| [csb_org_org](suites/csb_org_org.md) | `baseline-local-artifact` | 3 | 94 | 0.333 | 0.667 | FLAG: below minimum |
| [csb_org_org](suites/csb_org_org.md) | `baseline-local-direct` | 16 | 94 | 0.401 | 1.000 | FLAG: below minimum |
| [csb_org_org](suites/csb_org_org.md) | `mcp-remote-artifact` | 3 | 94 | 0.470 | 0.667 | FLAG: below minimum |
| [csb_org_org](suites/csb_org_org.md) | `mcp-remote-direct` | 94 | 94 | 0.312 | 0.713 | ok |
| [csb_org_platform](suites/csb_org_platform.md) | `baseline-local-artifact` | 2 | 110 | 0.000 | 0.000 | FLAG: below minimum |
| [csb_org_platform](suites/csb_org_platform.md) | `baseline-local-direct` | 19 | 110 | 0.298 | 0.947 | FLAG: below minimum |
| [csb_org_platform](suites/csb_org_platform.md) | `mcp-remote-artifact` | 2 | 110 | 0.000 | 0.000 | FLAG: below minimum |
| [csb_org_platform](suites/csb_org_platform.md) | `mcp-remote-direct` | 110 | 110 | 0.275 | 0.900 | ok |
| [csb_org_security](suites/csb_org_security.md) | `baseline-local-artifact` | 18 | 107 | 0.284 | 0.556 | FLAG: below minimum |
| [csb_org_security](suites/csb_org_security.md) | `baseline-local-direct` | 24 | 107 | 0.406 | 0.875 | FLAG: below minimum |
| [csb_org_security](suites/csb_org_security.md) | `mcp-remote-artifact` | 28 | 107 | 0.522 | 0.929 | FLAG: below minimum |
| [csb_org_security](suites/csb_org_security.md) | `mcp-remote-direct` | 107 | 107 | 0.567 | 0.925 | ok |
| [csb_sdlc_build](suites/csb_sdlc_build.md) | `baseline-local-artifact` | 1 | 23 | 0.700 | 1.000 | FLAG: below minimum |
| [csb_sdlc_build](suites/csb_sdlc_build.md) | `baseline-local-direct` | 23 | 23 | 0.580 | 0.783 | ok |
| [csb_sdlc_build](suites/csb_sdlc_build.md) | `mcp-remote-direct` | 20 | 23 | 0.592 | 0.800 | FLAG: below minimum |
| [csb_sdlc_debug](suites/csb_sdlc_debug.md) | `baseline-local-direct` | 22 | 20 | 0.667 | 0.955 | ok |
| [csb_sdlc_debug](suites/csb_sdlc_debug.md) | `mcp-remote-direct` | 81 | 20 | 0.593 | 0.877 | ok |
| [csb_sdlc_debug](suites/csb_sdlc_debug.md) | `sourcegraph_full` | 3 | 20 | 0.833 | 1.000 | FLAG: below minimum |
| [csb_sdlc_design](suites/csb_sdlc_design.md) | `baseline-local-direct` | 15 | 20 | 0.851 | 1.000 | FLAG: below minimum |
| [csb_sdlc_design](suites/csb_sdlc_design.md) | `mcp-remote-direct` | 59 | 20 | 0.736 | 0.966 | ok |
| [csb_sdlc_document](suites/csb_sdlc_document.md) | `baseline-local-direct` | 16 | 20 | 0.838 | 1.000 | FLAG: below minimum |
| [csb_sdlc_document](suites/csb_sdlc_document.md) | `mcp-remote-direct` | 66 | 20 | 0.831 | 0.985 | ok |
| [csb_sdlc_document](suites/csb_sdlc_document.md) | `sourcegraph_full` | 36 | 20 | 0.815 | 1.000 | ok |
| [csb_sdlc_feature](suites/csb_sdlc_feature.md) | `baseline-local-direct` | 23 | 20 | 0.631 | 0.913 | ok |
| [csb_sdlc_feature](suites/csb_sdlc_feature.md) | `mcp-remote-direct` | 109 | 20 | 0.591 | 0.807 | ok |
| [csb_sdlc_fix](suites/csb_sdlc_fix.md) | `baseline-local-artifact` | 2 | 25 | 0.595 | 1.000 | FLAG: below minimum |
| [csb_sdlc_fix](suites/csb_sdlc_fix.md) | `baseline-local-direct` | 33 | 25 | 0.414 | 0.515 | ok |
| [csb_sdlc_fix](suites/csb_sdlc_fix.md) | `mcp-remote-artifact` | 1 | 25 | 0.200 | 1.000 | FLAG: below minimum |
| [csb_sdlc_fix](suites/csb_sdlc_fix.md) | `mcp-remote-direct` | 150 | 25 | 0.518 | 0.647 | ok |
| [csb_sdlc_refactor](suites/csb_sdlc_refactor.md) | `baseline-local-direct` | 22 | 20 | 0.799 | 0.955 | ok |
| [csb_sdlc_refactor](suites/csb_sdlc_refactor.md) | `mcp-remote-direct` | 71 | 20 | 0.662 | 0.915 | ok |
| [csb_sdlc_secure](suites/csb_sdlc_secure.md) | `baseline-local-direct` | 13 | 20 | 0.788 | 1.000 | FLAG: below minimum |
| [csb_sdlc_secure](suites/csb_sdlc_secure.md) | `mcp-remote-direct` | 61 | 20 | 0.721 | 0.967 | ok |
| [csb_sdlc_test](suites/csb_sdlc_test.md) | `baseline-local-direct` | 20 | 20 | 0.591 | 0.850 | ok |
| [csb_sdlc_test](suites/csb_sdlc_test.md) | `mcp-remote-direct` | 74 | 20 | 0.568 | 0.851 | ok |
| [csb_sdlc_test](suites/csb_sdlc_test.md) | `sourcegraph_full` | 26 | 20 | 0.617 | 0.731 | ok |
| [csb_sdlc_understand](suites/csb_sdlc_understand.md) | `baseline-local-direct` | 17 | 20 | 0.938 | 1.000 | FLAG: below minimum |
| [csb_sdlc_understand](suites/csb_sdlc_understand.md) | `mcp-remote-direct` | 74 | 20 | 0.887 | 1.000 | ok |
| [csb_sdlc_understand](suites/csb_sdlc_understand.md) | `sourcegraph_full` | 3 | 20 | 0.887 | 1.000 | FLAG: below minimum |
| [unknown](suites/unknown.md) | `baseline-local-artifact` | 30 | 167 | 0.241 | 0.367 | FLAG: below minimum |
| [unknown](suites/unknown.md) | `baseline-local-direct` | 136 | 167 | 0.366 | 0.713 | FLAG: below minimum |
| [unknown](suites/unknown.md) | `mcp-remote-artifact` | 30 | 167 | 0.289 | 0.367 | FLAG: below minimum |
| [unknown](suites/unknown.md) | `mcp-remote-direct` | 167 | 167 | 0.459 | 0.832 | ok |

<details>
<summary>Run/Config Summary</summary>


| Run | Suite | Config | Valid Tasks | Mean Reward | Pass Rate |
|---|---|---|---:|---:|---:|
| [__old_pre_fix_ccb_mcp_compliance_haiku_20260224_170834](runs/__old_pre_fix_ccb_mcp_compliance_haiku_20260224_170834.md) | `unknown` | `baseline-local-artifact` | 1 | 0.000 | 0.000 |
| [__old_pre_fix_ccb_mcp_compliance_haiku_20260224_170834](runs/__old_pre_fix_ccb_mcp_compliance_haiku_20260224_170834.md) | `unknown` | `mcp-remote-artifact` | 1 | 0.000 | 0.000 |
| [__old_pre_fix_ccb_mcp_crossorg_haiku_20260224_170834](runs/__old_pre_fix_ccb_mcp_crossorg_haiku_20260224_170834.md) | `unknown` | `baseline-local-artifact` | 2 | 0.000 | 0.000 |
| [__old_pre_fix_ccb_mcp_crossorg_haiku_20260224_170834](runs/__old_pre_fix_ccb_mcp_crossorg_haiku_20260224_170834.md) | `unknown` | `mcp-remote-artifact` | 2 | 0.000 | 0.000 |
| [__old_pre_fix_ccb_mcp_crossrepo_tracing_haiku_20260221_140913](runs/__old_pre_fix_ccb_mcp_crossrepo_tracing_haiku_20260221_140913.md) | `unknown` | `baseline-local-artifact` | 3 | 0.941 | 1.000 |
| [__old_pre_fix_ccb_mcp_crossrepo_tracing_haiku_20260221_140913](runs/__old_pre_fix_ccb_mcp_crossrepo_tracing_haiku_20260221_140913.md) | `unknown` | `mcp-remote-artifact` | 3 | 0.899 | 1.000 |
| [__old_pre_fix_ccb_mcp_crossrepo_tracing_haiku_20260224_170834](runs/__old_pre_fix_ccb_mcp_crossrepo_tracing_haiku_20260224_170834.md) | `unknown` | `baseline-local-artifact` | 2 | 0.000 | 0.000 |
| [__old_pre_fix_ccb_mcp_crossrepo_tracing_haiku_20260224_170834](runs/__old_pre_fix_ccb_mcp_crossrepo_tracing_haiku_20260224_170834.md) | `unknown` | `mcp-remote-artifact` | 2 | 0.000 | 0.000 |
| [__old_pre_fix_ccb_mcp_domain_haiku_20260224_170834](runs/__old_pre_fix_ccb_mcp_domain_haiku_20260224_170834.md) | `unknown` | `baseline-local-artifact` | 3 | 0.000 | 0.000 |
| [__old_pre_fix_ccb_mcp_domain_haiku_20260224_170834](runs/__old_pre_fix_ccb_mcp_domain_haiku_20260224_170834.md) | `unknown` | `mcp-remote-artifact` | 3 | 0.000 | 0.000 |
| [__old_pre_fix_ccb_mcp_incident_haiku_20260221_140913](runs/__old_pre_fix_ccb_mcp_incident_haiku_20260221_140913.md) | `unknown` | `baseline-local-artifact` | 1 | 0.500 | 1.000 |
| [__old_pre_fix_ccb_mcp_incident_haiku_20260221_140913](runs/__old_pre_fix_ccb_mcp_incident_haiku_20260221_140913.md) | `unknown` | `mcp-remote-artifact` | 1 | 1.000 | 1.000 |
| [__old_pre_fix_ccb_mcp_incident_haiku_20260224_170834](runs/__old_pre_fix_ccb_mcp_incident_haiku_20260224_170834.md) | `unknown` | `baseline-local-artifact` | 3 | 0.000 | 0.000 |
| [__old_pre_fix_ccb_mcp_incident_haiku_20260224_170834](runs/__old_pre_fix_ccb_mcp_incident_haiku_20260224_170834.md) | `unknown` | `mcp-remote-artifact` | 3 | 0.000 | 0.000 |
| [__old_pre_fix_ccb_mcp_onboarding_haiku_20260221_140913](runs/__old_pre_fix_ccb_mcp_onboarding_haiku_20260221_140913.md) | `unknown` | `baseline-local-artifact` | 3 | 0.639 | 1.000 |
| [__old_pre_fix_ccb_mcp_onboarding_haiku_20260221_140913](runs/__old_pre_fix_ccb_mcp_onboarding_haiku_20260221_140913.md) | `unknown` | `mcp-remote-artifact` | 3 | 0.778 | 1.000 |
| [__old_pre_fix_ccb_mcp_onboarding_haiku_20260224_170834](runs/__old_pre_fix_ccb_mcp_onboarding_haiku_20260224_170834.md) | `unknown` | `baseline-local-artifact` | 4 | 0.000 | 0.000 |
| [__old_pre_fix_ccb_mcp_onboarding_haiku_20260224_170834](runs/__old_pre_fix_ccb_mcp_onboarding_haiku_20260224_170834.md) | `unknown` | `mcp-remote-artifact` | 4 | 0.000 | 0.000 |
| [__old_pre_fix_ccb_mcp_org_haiku_20260224_170834](runs/__old_pre_fix_ccb_mcp_org_haiku_20260224_170834.md) | `unknown` | `baseline-local-artifact` | 2 | 0.500 | 1.000 |
| [__old_pre_fix_ccb_mcp_org_haiku_20260224_170834](runs/__old_pre_fix_ccb_mcp_org_haiku_20260224_170834.md) | `unknown` | `mcp-remote-artifact` | 2 | 0.500 | 1.000 |
| [__old_pre_fix_ccb_mcp_security_haiku_20260221_140913](runs/__old_pre_fix_ccb_mcp_security_haiku_20260221_140913.md) | `unknown` | `baseline-local-artifact` | 2 | 0.500 | 1.000 |
| [__old_pre_fix_ccb_mcp_security_haiku_20260221_140913](runs/__old_pre_fix_ccb_mcp_security_haiku_20260221_140913.md) | `unknown` | `mcp-remote-artifact` | 2 | 0.821 | 1.000 |
| [__old_pre_fix_ccb_mcp_security_haiku_20260224_170834](runs/__old_pre_fix_ccb_mcp_security_haiku_20260224_170834.md) | `unknown` | `baseline-local-artifact` | 4 | 0.000 | 0.000 |
| [__old_pre_fix_ccb_mcp_security_haiku_20260224_170834](runs/__old_pre_fix_ccb_mcp_security_haiku_20260224_170834.md) | `unknown` | `mcp-remote-artifact` | 4 | 0.000 | 0.000 |
| [bigcode_mcp_opus_20260205_212220](runs/bigcode_mcp_opus_20260205_212220.md) | `ccb_largerepo` | `baseline` | 4 | 0.000 | 0.000 |
| [build_haiku_20260222_125217__pre_sgenv_fix](runs/build_haiku_20260222_125217__pre_sgenv_fix.md) | `csb_sdlc_build` | `baseline-local-artifact` | 1 | 0.700 | 1.000 |
| [ccb_build_haiku_022326](runs/ccb_build_haiku_022326.md) | `ccb_misc` | `mcp` | 7 | 0.286 | 0.286 |
| [ccb_contextbench_haiku_20260302_184833](runs/ccb_contextbench_haiku_20260302_184833.md) | `ccb_misc` | `baseline-local-direct` | 5 | 0.273 | 0.800 |
| [ccb_contextbench_haiku_20260302_184833](runs/ccb_contextbench_haiku_20260302_184833.md) | `ccb_misc` | `mcp-remote-direct` | 5 | 0.392 | 0.800 |
| [ccb_debug_haiku_20260221_203204__pre_sgenv_fix](runs/ccb_debug_haiku_20260221_203204__pre_sgenv_fix.md) | `ccb_misc` | `baseline-local-artifact` | 5 | 0.500 | 1.000 |
| [ccb_debug_haiku_20260221_203204__pre_sgenv_fix](runs/ccb_debug_haiku_20260221_203204__pre_sgenv_fix.md) | `ccb_misc` | `mcp-remote-artifact` | 19 | 0.563 | 0.842 |
| [ccb_design_haiku_20260221_230537__pre_sgenv_fix](runs/ccb_design_haiku_20260221_230537__pre_sgenv_fix.md) | `ccb_misc` | `mcp-remote-artifact` | 20 | 0.544 | 0.850 |
| [ccb_document_haiku_20260221_174306__pre_sgenv_fix](runs/ccb_document_haiku_20260221_174306__pre_sgenv_fix.md) | `ccb_misc` | `baseline-local-artifact` | 1 | 0.650 | 1.000 |
| [ccb_document_haiku_20260221_174306__pre_sgenv_fix](runs/ccb_document_haiku_20260221_174306__pre_sgenv_fix.md) | `ccb_misc` | `mcp-remote-artifact` | 17 | 0.862 | 1.000 |
| [ccb_fix_haiku_20260224_203138](runs/ccb_fix_haiku_20260224_203138.md) | `ccb_misc` | `mcp-remote-direct` | 1 | 0.740 | 1.000 |
| [ccb_mcp_crossorg_haiku_20260221_165304__promoted](runs/ccb_mcp_crossorg_haiku_20260221_165304__promoted.md) | `ccb_mcp_crossorg` | `mcp-remote-artifact` | 2 | 1.000 | 1.000 |
| [ccb_mcp_crossrepo_tracing_haiku_20260221_165304__promoted](runs/ccb_mcp_crossrepo_tracing_haiku_20260221_165304__promoted.md) | `ccb_mcp_crossrepo` | `mcp-remote-artifact` | 3 | 0.941 | 1.000 |
| [ccb_mcp_incident_haiku_20260221_165304__promoted](runs/ccb_mcp_incident_haiku_20260221_165304__promoted.md) | `ccb_mcp_incident` | `mcp-remote-artifact` | 1 | 1.000 | 1.000 |
| [ccb_mcp_migration_haiku_20260302_175827](runs/ccb_mcp_migration_haiku_20260302_175827.md) | `ccb_mcp_migration` | `baseline-local-direct` | 26 | 0.318 | 0.808 |
| [ccb_mcp_migration_haiku_20260302_175827](runs/ccb_mcp_migration_haiku_20260302_175827.md) | `ccb_mcp_migration` | `mcp-remote-direct` | 25 | 0.317 | 0.840 |
| [ccb_mcp_migration_haiku_20260302_183602](runs/ccb_mcp_migration_haiku_20260302_183602.md) | `ccb_mcp_migration` | `baseline-local-direct` | 8 | 0.681 | 1.000 |
| [ccb_mcp_migration_haiku_20260302_183602](runs/ccb_mcp_migration_haiku_20260302_183602.md) | `ccb_mcp_migration` | `mcp-remote-direct` | 8 | 0.696 | 1.000 |
| [ccb_mcp_migration_haiku_20260302_183608](runs/ccb_mcp_migration_haiku_20260302_183608.md) | `ccb_mcp_migration` | `baseline-local-direct` | 8 | 0.659 | 1.000 |
| [ccb_mcp_migration_haiku_20260302_183608](runs/ccb_mcp_migration_haiku_20260302_183608.md) | `ccb_mcp_migration` | `mcp-remote-direct` | 8 | 0.694 | 1.000 |
| [ccb_mcp_onboarding_haiku_20260221_165304__promoted](runs/ccb_mcp_onboarding_haiku_20260221_165304__promoted.md) | `ccb_mcp_onboarding` | `mcp-remote-artifact` | 3 | 0.722 | 1.000 |
| [ccb_mcp_platform_haiku_20260221_165304__promoted](runs/ccb_mcp_platform_haiku_20260221_165304__promoted.md) | `ccb_mcp_platform` | `mcp-remote-artifact` | 1 | 0.875 | 1.000 |
| [ccb_mcp_security_haiku_20260221_165304__promoted](runs/ccb_mcp_security_haiku_20260221_165304__promoted.md) | `ccb_mcp_security` | `mcp-remote-artifact` | 2 | 0.875 | 1.000 |
| [ccb_mcp_security_haiku_20260301_191250](runs/ccb_mcp_security_haiku_20260301_191250.md) | `ccb_mcp_security` | `mcp-remote-direct` | 8 | 0.000 | 0.000 |
| [ccb_mcp_security_haiku_20260301_195739](runs/ccb_mcp_security_haiku_20260301_195739.md) | `ccb_mcp_security` | `baseline-local-direct` | 10 | 0.000 | 0.000 |
| [ccb_mcp_security_haiku_20260301_195739](runs/ccb_mcp_security_haiku_20260301_195739.md) | `ccb_mcp_security` | `mcp-remote-direct` | 10 | 0.000 | 0.000 |
| [ccb_test_haiku_20260221_174306__pre_sgenv_fix](runs/ccb_test_haiku_20260221_174306__pre_sgenv_fix.md) | `ccb_misc` | `mcp-remote-artifact` | 9 | 0.544 | 1.000 |
| [ccb_understand_haiku_20260221_174306__incomplete](runs/ccb_understand_haiku_20260221_174306__incomplete.md) | `ccb_misc` | `mcp-remote-artifact` | 2 | 0.125 | 0.500 |
| [codereview_opus_20260206_163958__doubled_prefix](runs/codereview_opus_20260206_163958__doubled_prefix.md) | `ccb_codereview` | `sourcegraph_base` | 3 | 0.893 | 1.000 |
| [crossrepo_opus_20260202_204730](runs/crossrepo_opus_20260202_204730.md) | `ccb_crossrepo` | `baseline` | 5 | 0.200 | 0.200 |
| [crossrepo_opus_20260202_204733](runs/crossrepo_opus_20260202_204733.md) | `ccb_crossrepo` | `sourcegraph_full` | 2 | 0.000 | 0.000 |
| [crossrepo_opus_20260203_160607](runs/crossrepo_opus_20260203_160607.md) | `ccb_crossrepo` | `baseline` | 1 | 1.000 | 1.000 |
| [crossrepo_opus_20260204_133742__verifier_path_bug](runs/crossrepo_opus_20260204_133742__verifier_path_bug.md) | `ccb_crossrepo` | `baseline` | 4 | 0.000 | 0.000 |
| [crossrepo_opus_20260204_133742__verifier_path_bug](runs/crossrepo_opus_20260204_133742__verifier_path_bug.md) | `ccb_crossrepo` | `sourcegraph_base` | 4 | 0.000 | 0.000 |
| [csb_org_compliance_haiku_20260224_181919](runs/csb_org_compliance_haiku_20260224_181919.md) | `csb_org_compliance` | `mcp-remote-artifact` | 1 | 0.742 | 1.000 |
| [csb_org_compliance_haiku_20260225_011700](runs/csb_org_compliance_haiku_20260225_011700.md) | `csb_org_compliance` | `baseline-local-artifact` | 1 | 0.375 | 1.000 |
| [csb_org_compliance_haiku_20260226_035515_variance](runs/csb_org_compliance_haiku_20260226_035515_variance.md) | `csb_org_compliance` | `baseline-local-direct` | 1 | 0.386 | 1.000 |
| [csb_org_compliance_haiku_20260226_035515_variance](runs/csb_org_compliance_haiku_20260226_035515_variance.md) | `csb_org_compliance` | `mcp-remote-direct` | 3 | 0.489 | 1.000 |
| [csb_org_compliance_haiku_20260226_035617](runs/csb_org_compliance_haiku_20260226_035617.md) | `csb_org_compliance` | `baseline-local-direct` | 1 | 0.327 | 1.000 |
| [csb_org_compliance_haiku_20260226_035617](runs/csb_org_compliance_haiku_20260226_035617.md) | `csb_org_compliance` | `mcp-remote-direct` | 4 | 0.485 | 1.000 |
| [csb_org_compliance_haiku_20260226_035622_variance](runs/csb_org_compliance_haiku_20260226_035622_variance.md) | `csb_org_compliance` | `baseline-local-direct` | 1 | 0.373 | 1.000 |
| [csb_org_compliance_haiku_20260226_035622_variance](runs/csb_org_compliance_haiku_20260226_035622_variance.md) | `csb_org_compliance` | `mcp-remote-direct` | 4 | 0.590 | 1.000 |
| [csb_org_compliance_haiku_20260226_035628_variance](runs/csb_org_compliance_haiku_20260226_035628_variance.md) | `csb_org_compliance` | `baseline-local-direct` | 1 | 0.302 | 1.000 |
| [csb_org_compliance_haiku_20260226_035628_variance](runs/csb_org_compliance_haiku_20260226_035628_variance.md) | `csb_org_compliance` | `mcp-remote-direct` | 4 | 0.548 | 1.000 |
| [csb_org_compliance_haiku_20260226_035633_variance](runs/csb_org_compliance_haiku_20260226_035633_variance.md) | `csb_org_compliance` | `baseline-local-direct` | 1 | 0.356 | 1.000 |
| [csb_org_compliance_haiku_20260226_035633_variance](runs/csb_org_compliance_haiku_20260226_035633_variance.md) | `csb_org_compliance` | `mcp-remote-direct` | 3 | 0.806 | 1.000 |
| [csb_org_compliance_haiku_20260226_145828](runs/csb_org_compliance_haiku_20260226_145828.md) | `csb_org_compliance` | `baseline-local-direct` | 4 | 0.337 | 0.500 |
| [csb_org_compliance_haiku_20260226_205845](runs/csb_org_compliance_haiku_20260226_205845.md) | `csb_org_compliance` | `baseline-local-direct` | 2 | 0.667 | 1.000 |
| [csb_org_compliance_haiku_20260226_214446](runs/csb_org_compliance_haiku_20260226_214446.md) | `csb_org_compliance` | `baseline-local-direct` | 2 | 0.778 | 1.000 |
| [csb_org_compliance_haiku_20260226_221038](runs/csb_org_compliance_haiku_20260226_221038.md) | `csb_org_compliance` | `mcp-remote-direct` | 2 | 0.833 | 1.000 |
| [csb_org_compliance_haiku_20260228_011250](runs/csb_org_compliance_haiku_20260228_011250.md) | `csb_org_compliance` | `baseline-local-direct` | 6 | 0.626 | 1.000 |
| [csb_org_compliance_haiku_20260228_011250](runs/csb_org_compliance_haiku_20260228_011250.md) | `csb_org_compliance` | `mcp-remote-direct` | 7 | 0.597 | 1.000 |
| [csb_org_compliance_haiku_20260228_123206](runs/csb_org_compliance_haiku_20260228_123206.md) | `csb_org_compliance` | `baseline-local-direct` | 1 | 0.593 | 1.000 |
| [csb_org_compliance_haiku_20260228_133005](runs/csb_org_compliance_haiku_20260228_133005.md) | `csb_org_compliance` | `baseline-local-direct` | 1 | 0.655 | 1.000 |
| [csb_org_compliance_haiku_20260301_173337](runs/csb_org_compliance_haiku_20260301_173337.md) | `csb_org_compliance` | `baseline-local-direct` | 10 | 0.000 | 0.000 |
| [csb_org_compliance_haiku_20260301_173337](runs/csb_org_compliance_haiku_20260301_173337.md) | `csb_org_compliance` | `mcp-remote-direct` | 12 | 0.000 | 0.000 |
| [csb_org_compliance_haiku_20260301_185444](runs/csb_org_compliance_haiku_20260301_185444.md) | `csb_org_compliance` | `baseline-local-direct` | 12 | 0.178 | 0.833 |
| [csb_org_compliance_haiku_20260301_185444](runs/csb_org_compliance_haiku_20260301_185444.md) | `csb_org_compliance` | `mcp-remote-direct` | 14 | 0.186 | 0.714 |
| [csb_org_compliance_haiku_20260301_195739](runs/csb_org_compliance_haiku_20260301_195739.md) | `csb_org_compliance` | `baseline-local-direct` | 11 | 0.159 | 0.909 |
| [csb_org_compliance_haiku_20260301_195739](runs/csb_org_compliance_haiku_20260301_195739.md) | `csb_org_compliance` | `mcp-remote-direct` | 10 | 0.157 | 0.600 |
| [csb_org_compliance_haiku_20260302_014939](runs/csb_org_compliance_haiku_20260302_014939.md) | `csb_org_compliance` | `baseline-local-direct` | 12 | 0.179 | 0.833 |
| [csb_org_compliance_haiku_20260302_014939](runs/csb_org_compliance_haiku_20260302_014939.md) | `csb_org_compliance` | `mcp-remote-direct` | 12 | 0.194 | 0.833 |
| [csb_org_compliance_haiku_20260302_175821](runs/csb_org_compliance_haiku_20260302_175821.md) | `csb_org_compliance` | `baseline-local-direct` | 16 | 0.202 | 0.875 |
| [csb_org_compliance_haiku_20260302_175821](runs/csb_org_compliance_haiku_20260302_175821.md) | `csb_org_compliance` | `mcp-remote-direct` | 16 | 0.242 | 0.875 |
| [csb_org_compliance_haiku_20260302_175827](runs/csb_org_compliance_haiku_20260302_175827.md) | `csb_org_compliance` | `baseline-local-direct` | 16 | 0.204 | 0.812 |
| [csb_org_compliance_haiku_20260302_175827](runs/csb_org_compliance_haiku_20260302_175827.md) | `csb_org_compliance` | `mcp-remote-direct` | 16 | 0.248 | 0.875 |
| [csb_org_compliance_haiku_20260302_183602](runs/csb_org_compliance_haiku_20260302_183602.md) | `csb_org_compliance` | `baseline-local-direct` | 1 | 0.355 | 1.000 |
| [csb_org_compliance_haiku_20260302_183602](runs/csb_org_compliance_haiku_20260302_183602.md) | `csb_org_compliance` | `mcp-remote-direct` | 1 | 0.455 | 1.000 |
| [csb_org_compliance_haiku_20260302_183608](runs/csb_org_compliance_haiku_20260302_183608.md) | `csb_org_compliance` | `baseline-local-direct` | 1 | 0.351 | 1.000 |
| [csb_org_compliance_haiku_20260302_183608](runs/csb_org_compliance_haiku_20260302_183608.md) | `csb_org_compliance` | `mcp-remote-direct` | 1 | 0.917 | 1.000 |
| [csb_org_compliance_haiku_20260307_030626](runs/csb_org_compliance_haiku_20260307_030626.md) | `csb_org_compliance` | `baseline-local-artifact` | 2 | 0.000 | 0.000 |
| [csb_org_compliance_haiku_20260307_030626](runs/csb_org_compliance_haiku_20260307_030626.md) | `csb_org_compliance` | `mcp-remote-artifact` | 2 | 0.000 | 0.000 |
| [csb_org_compliance_sonnet_20260308_034803](runs/csb_org_compliance_sonnet_20260308_034803.md) | `csb_org_compliance` | `baseline-local-direct` | 13 | 0.347 | 0.923 |
| [csb_org_compliance_sonnet_20260308_034803](runs/csb_org_compliance_sonnet_20260308_034803.md) | `csb_org_compliance` | `mcp-remote-direct` | 13 | 0.349 | 0.846 |
| [csb_org_crossorg_haiku_20260224_181919](runs/csb_org_crossorg_haiku_20260224_181919.md) | `csb_org_crossorg` | `mcp-remote-artifact` | 2 | 0.171 | 0.500 |
| [csb_org_crossorg_haiku_20260225_011700](runs/csb_org_crossorg_haiku_20260225_011700.md) | `csb_org_crossorg` | `baseline-local-artifact` | 2 | 0.062 | 0.500 |
| [csb_org_crossorg_haiku_20260226_035617](runs/csb_org_crossorg_haiku_20260226_035617.md) | `csb_org_crossorg` | `mcp-remote-direct` | 1 | 0.800 | 1.000 |
| [csb_org_crossorg_haiku_20260226_035622_variance](runs/csb_org_crossorg_haiku_20260226_035622_variance.md) | `csb_org_crossorg` | `mcp-remote-direct` | 1 | 0.680 | 1.000 |
| [csb_org_crossorg_haiku_20260226_035628_variance](runs/csb_org_crossorg_haiku_20260226_035628_variance.md) | `csb_org_crossorg` | `mcp-remote-direct` | 1 | 0.680 | 1.000 |
| [csb_org_crossorg_haiku_20260226_035633_variance](runs/csb_org_crossorg_haiku_20260226_035633_variance.md) | `csb_org_crossorg` | `mcp-remote-direct` | 1 | 0.711 | 1.000 |
| [csb_org_crossorg_haiku_20260226_145828](runs/csb_org_crossorg_haiku_20260226_145828.md) | `csb_org_crossorg` | `baseline-local-direct` | 1 | 0.335 | 1.000 |
| [csb_org_crossorg_haiku_20260226_205845](runs/csb_org_crossorg_haiku_20260226_205845.md) | `csb_org_crossorg` | `baseline-local-direct` | 1 | 0.658 | 1.000 |
| [csb_org_crossorg_haiku_20260228_005320](runs/csb_org_crossorg_haiku_20260228_005320.md) | `csb_org_crossorg` | `baseline-local-direct` | 3 | 0.466 | 1.000 |
| [csb_org_crossorg_haiku_20260228_005320](runs/csb_org_crossorg_haiku_20260228_005320.md) | `csb_org_crossorg` | `mcp-remote-direct` | 5 | 0.434 | 0.800 |
| [csb_org_crossorg_haiku_20260228_123206](runs/csb_org_crossorg_haiku_20260228_123206.md) | `csb_org_crossorg` | `baseline-local-direct` | 2 | 0.345 | 1.000 |
| [csb_org_crossorg_haiku_20260228_133005](runs/csb_org_crossorg_haiku_20260228_133005.md) | `csb_org_crossorg` | `baseline-local-direct` | 2 | 0.334 | 1.000 |
| [csb_org_crossorg_haiku_20260301_173337](runs/csb_org_crossorg_haiku_20260301_173337.md) | `csb_org_crossorg` | `baseline-local-direct` | 12 | 0.000 | 0.000 |
| [csb_org_crossorg_haiku_20260301_173337](runs/csb_org_crossorg_haiku_20260301_173337.md) | `csb_org_crossorg` | `mcp-remote-direct` | 5 | 0.000 | 0.000 |
| [csb_org_crossorg_haiku_20260301_185444](runs/csb_org_crossorg_haiku_20260301_185444.md) | `csb_org_crossorg` | `mcp-remote-direct` | 2 | 0.000 | 0.000 |
| [csb_org_crossorg_haiku_20260301_191250](runs/csb_org_crossorg_haiku_20260301_191250.md) | `csb_org_crossorg` | `baseline-local-direct` | 11 | 0.000 | 0.000 |
| [csb_org_crossorg_haiku_20260301_191250](runs/csb_org_crossorg_haiku_20260301_191250.md) | `csb_org_crossorg` | `mcp-remote-direct` | 15 | 0.000 | 0.000 |
| [csb_org_crossorg_haiku_20260301_195739](runs/csb_org_crossorg_haiku_20260301_195739.md) | `csb_org_crossorg` | `baseline-local-direct` | 9 | 0.128 | 0.667 |
| [csb_org_crossorg_haiku_20260301_195739](runs/csb_org_crossorg_haiku_20260301_195739.md) | `csb_org_crossorg` | `mcp-remote-direct` | 9 | 0.046 | 0.222 |
| [csb_org_crossorg_haiku_20260302_014939](runs/csb_org_crossorg_haiku_20260302_014939.md) | `csb_org_crossorg` | `baseline-local-direct` | 12 | 0.107 | 0.583 |
| [csb_org_crossorg_haiku_20260302_014939](runs/csb_org_crossorg_haiku_20260302_014939.md) | `csb_org_crossorg` | `mcp-remote-direct` | 12 | 0.181 | 0.667 |
| [csb_org_crossorg_haiku_20260302_034936](runs/csb_org_crossorg_haiku_20260302_034936.md) | `csb_org_crossorg` | `baseline-local-direct` | 12 | 0.103 | 0.500 |
| [csb_org_crossorg_haiku_20260302_034936](runs/csb_org_crossorg_haiku_20260302_034936.md) | `csb_org_crossorg` | `mcp-remote-direct` | 12 | 0.096 | 0.500 |
| [csb_org_crossorg_haiku_20260302_175821](runs/csb_org_crossorg_haiku_20260302_175821.md) | `csb_org_crossorg` | `baseline-local-direct` | 14 | 0.144 | 0.714 |
| [csb_org_crossorg_haiku_20260302_175821](runs/csb_org_crossorg_haiku_20260302_175821.md) | `csb_org_crossorg` | `mcp-remote-direct` | 14 | 0.184 | 0.714 |
| [csb_org_crossorg_haiku_20260302_175827](runs/csb_org_crossorg_haiku_20260302_175827.md) | `csb_org_crossorg` | `baseline-local-direct` | 14 | 0.161 | 0.643 |
| [csb_org_crossorg_haiku_20260302_175827](runs/csb_org_crossorg_haiku_20260302_175827.md) | `csb_org_crossorg` | `mcp-remote-direct` | 14 | 0.175 | 0.643 |
| [csb_org_crossorg_haiku_20260307_001927](runs/csb_org_crossorg_haiku_20260307_001927.md) | `csb_org_crossorg` | `baseline-local-direct` | 1 | 0.407 | 1.000 |
| [csb_org_crossorg_haiku_20260307_001927](runs/csb_org_crossorg_haiku_20260307_001927.md) | `csb_org_crossorg` | `mcp-remote-direct` | 1 | 0.488 | 1.000 |
| [csb_org_crossorg_haiku_20260307_004359](runs/csb_org_crossorg_haiku_20260307_004359.md) | `csb_org_crossorg` | `baseline-local-artifact` | 1 | 0.444 | 1.000 |
| [csb_org_crossorg_haiku_20260307_004359](runs/csb_org_crossorg_haiku_20260307_004359.md) | `csb_org_crossorg` | `mcp-remote-artifact` | 1 | 0.429 | 1.000 |
| [csb_org_crossorg_haiku_20260307_030626](runs/csb_org_crossorg_haiku_20260307_030626.md) | `csb_org_crossorg` | `baseline-local-artifact` | 2 | 0.000 | 0.000 |
| [csb_org_crossorg_haiku_20260307_030626](runs/csb_org_crossorg_haiku_20260307_030626.md) | `csb_org_crossorg` | `mcp-remote-artifact` | 2 | 0.000 | 0.000 |
| [csb_org_crossorg_sonnet_20260308_034803](runs/csb_org_crossorg_sonnet_20260308_034803.md) | `csb_org_crossorg` | `baseline-local-direct` | 12 | 0.375 | 1.000 |
| [csb_org_crossorg_sonnet_20260308_034803](runs/csb_org_crossorg_sonnet_20260308_034803.md) | `csb_org_crossorg` | `mcp-remote-direct` | 12 | 0.396 | 1.000 |
| [csb_org_crossrepo_haiku_20260226_035617](runs/csb_org_crossrepo_haiku_20260226_035617.md) | `csb_org_crossrepo` | `mcp-remote-direct` | 1 | 0.767 | 1.000 |
| [csb_org_crossrepo_haiku_20260226_035622_variance](runs/csb_org_crossrepo_haiku_20260226_035622_variance.md) | `csb_org_crossrepo` | `mcp-remote-direct` | 1 | 0.644 | 1.000 |
| [csb_org_crossrepo_haiku_20260226_035628_variance](runs/csb_org_crossrepo_haiku_20260226_035628_variance.md) | `csb_org_crossrepo` | `mcp-remote-direct` | 1 | 0.767 | 1.000 |
| [csb_org_crossrepo_haiku_20260226_035633_variance](runs/csb_org_crossrepo_haiku_20260226_035633_variance.md) | `csb_org_crossrepo` | `mcp-remote-direct` | 1 | 0.850 | 1.000 |
| [csb_org_crossrepo_haiku_20260226_145828](runs/csb_org_crossrepo_haiku_20260226_145828.md) | `csb_org_crossrepo` | `baseline-local-direct` | 1 | 0.900 | 1.000 |
| [csb_org_crossrepo_haiku_20260226_205845](runs/csb_org_crossrepo_haiku_20260226_205845.md) | `csb_org_crossrepo` | `baseline-local-direct` | 1 | 0.867 | 1.000 |
| [csb_org_crossrepo_haiku_20260228_005303](runs/csb_org_crossrepo_haiku_20260228_005303.md) | `csb_org_crossrepo` | `baseline-local-direct` | 1 | 0.850 | 1.000 |
| [csb_org_crossrepo_haiku_20260228_005303](runs/csb_org_crossrepo_haiku_20260228_005303.md) | `csb_org_crossrepo` | `mcp-remote-direct` | 1 | 0.633 | 1.000 |
| [csb_org_crossrepo_haiku_20260301_173337](runs/csb_org_crossrepo_haiku_20260301_173337.md) | `csb_org_crossrepo` | `baseline-local-direct` | 5 | 0.000 | 0.000 |
| [csb_org_crossrepo_haiku_20260301_173337](runs/csb_org_crossrepo_haiku_20260301_173337.md) | `csb_org_crossrepo` | `mcp-remote-direct` | 7 | 0.000 | 0.000 |
| [csb_org_crossrepo_haiku_20260301_185444](runs/csb_org_crossrepo_haiku_20260301_185444.md) | `csb_org_crossrepo` | `baseline-local-direct` | 8 | 0.261 | 0.875 |
| [csb_org_crossrepo_haiku_20260301_185444](runs/csb_org_crossrepo_haiku_20260301_185444.md) | `csb_org_crossrepo` | `mcp-remote-direct` | 11 | 0.203 | 0.727 |
| [csb_org_crossrepo_haiku_20260301_191250](runs/csb_org_crossrepo_haiku_20260301_191250.md) | `csb_org_crossrepo` | `baseline-local-direct` | 8 | 0.257 | 1.000 |
| [csb_org_crossrepo_haiku_20260301_191250](runs/csb_org_crossrepo_haiku_20260301_191250.md) | `csb_org_crossrepo` | `mcp-remote-direct` | 11 | 0.250 | 1.000 |
| [csb_org_crossrepo_haiku_20260301_195739](runs/csb_org_crossrepo_haiku_20260301_195739.md) | `csb_org_crossrepo` | `baseline-local-direct` | 13 | 0.271 | 0.923 |
| [csb_org_crossrepo_haiku_20260301_195739](runs/csb_org_crossrepo_haiku_20260301_195739.md) | `csb_org_crossrepo` | `mcp-remote-direct` | 18 | 0.194 | 0.778 |
| [csb_org_crossrepo_haiku_20260301_201320](runs/csb_org_crossrepo_haiku_20260301_201320.md) | `csb_org_crossrepo` | `baseline-local-direct` | 2 | 0.121 | 1.000 |
| [csb_org_crossrepo_haiku_20260301_201320](runs/csb_org_crossrepo_haiku_20260301_201320.md) | `csb_org_crossrepo` | `mcp-remote-direct` | 6 | 0.049 | 0.333 |
| [csb_org_crossrepo_haiku_20260302_014939](runs/csb_org_crossrepo_haiku_20260302_014939.md) | `csb_org_crossrepo` | `baseline-local-direct` | 11 | 0.293 | 1.000 |
| [csb_org_crossrepo_haiku_20260302_014939](runs/csb_org_crossrepo_haiku_20260302_014939.md) | `csb_org_crossrepo` | `mcp-remote-direct` | 11 | 0.291 | 1.000 |
| [csb_org_crossrepo_haiku_20260302_034936](runs/csb_org_crossrepo_haiku_20260302_034936.md) | `csb_org_crossrepo` | `baseline-local-direct` | 5 | 0.253 | 1.000 |
| [csb_org_crossrepo_haiku_20260302_034936](runs/csb_org_crossrepo_haiku_20260302_034936.md) | `csb_org_crossrepo` | `mcp-remote-direct` | 5 | 0.250 | 1.000 |
| [csb_org_crossrepo_haiku_20260302_175821](runs/csb_org_crossrepo_haiku_20260302_175821.md) | `csb_org_crossrepo` | `baseline-local-direct` | 13 | 0.259 | 1.000 |
| [csb_org_crossrepo_haiku_20260302_175821](runs/csb_org_crossrepo_haiku_20260302_175821.md) | `csb_org_crossrepo` | `mcp-remote-direct` | 13 | 0.227 | 1.000 |
| [csb_org_crossrepo_haiku_20260302_175827](runs/csb_org_crossrepo_haiku_20260302_175827.md) | `csb_org_crossrepo` | `baseline-local-direct` | 13 | 0.271 | 1.000 |
| [csb_org_crossrepo_haiku_20260302_175827](runs/csb_org_crossrepo_haiku_20260302_175827.md) | `csb_org_crossrepo` | `mcp-remote-direct` | 13 | 0.265 | 1.000 |
| [csb_org_crossrepo_sonnet_20260308_034803](runs/csb_org_crossrepo_sonnet_20260308_034803.md) | `csb_org_crossrepo` | `baseline-local-direct` | 11 | 0.282 | 1.000 |
| [csb_org_crossrepo_sonnet_20260308_034803](runs/csb_org_crossrepo_sonnet_20260308_034803.md) | `csb_org_crossrepo` | `mcp-remote-direct` | 11 | 0.288 | 1.000 |
| [csb_org_crossrepo_tracing_haiku_022126](runs/csb_org_crossrepo_tracing_haiku_022126.md) | `csb_org_crossrepo` | `baseline-local-artifact` | 3 | 0.941 | 1.000 |
| [csb_org_crossrepo_tracing_haiku_022126](runs/csb_org_crossrepo_tracing_haiku_022126.md) | `csb_org_crossrepo` | `mcp-remote-artifact` | 3 | 0.899 | 1.000 |
| [csb_org_crossrepo_tracing_haiku_20260224_181919](runs/csb_org_crossrepo_tracing_haiku_20260224_181919.md) | `csb_org_crossrepo` | `mcp-remote-artifact` | 2 | 0.287 | 1.000 |
| [csb_org_crossrepo_tracing_haiku_20260225_011700](runs/csb_org_crossrepo_tracing_haiku_20260225_011700.md) | `csb_org_crossrepo` | `baseline-local-artifact` | 2 | 0.000 | 0.000 |
| [csb_org_crossrepo_tracing_haiku_20260226_035617](runs/csb_org_crossrepo_tracing_haiku_20260226_035617.md) | `csb_org_crossrepo` | `mcp-remote-direct` | 3 | 0.669 | 1.000 |
| [csb_org_crossrepo_tracing_haiku_20260226_035622_variance](runs/csb_org_crossrepo_tracing_haiku_20260226_035622_variance.md) | `csb_org_crossrepo` | `mcp-remote-direct` | 3 | 0.762 | 1.000 |
| [csb_org_crossrepo_tracing_haiku_20260226_035628_variance](runs/csb_org_crossrepo_tracing_haiku_20260226_035628_variance.md) | `csb_org_crossrepo` | `mcp-remote-direct` | 3 | 0.756 | 1.000 |
| [csb_org_crossrepo_tracing_haiku_20260226_035633_variance](runs/csb_org_crossrepo_tracing_haiku_20260226_035633_variance.md) | `csb_org_crossrepo` | `mcp-remote-direct` | 3 | 0.595 | 1.000 |
| [csb_org_crossrepo_tracing_haiku_20260226_145828](runs/csb_org_crossrepo_tracing_haiku_20260226_145828.md) | `csb_org_crossrepo` | `baseline-local-direct` | 4 | 0.525 | 0.750 |
| [csb_org_crossrepo_tracing_haiku_20260226_205845](runs/csb_org_crossrepo_tracing_haiku_20260226_205845.md) | `csb_org_crossrepo` | `baseline-local-direct` | 3 | 0.722 | 1.000 |
| [csb_org_crossrepo_tracing_haiku_20260226_214446](runs/csb_org_crossrepo_tracing_haiku_20260226_214446.md) | `csb_org_crossrepo` | `baseline-local-direct` | 1 | 0.571 | 1.000 |
| [csb_org_crossrepo_tracing_haiku_20260226_221038](runs/csb_org_crossrepo_tracing_haiku_20260226_221038.md) | `csb_org_crossrepo` | `mcp-remote-direct` | 1 | 0.800 | 1.000 |
| [csb_org_crossrepo_tracing_haiku_20260228_022542](runs/csb_org_crossrepo_tracing_haiku_20260228_022542.md) | `csb_org_crossrepo` | `baseline-local-direct` | 9 | 0.538 | 0.778 |
| [csb_org_crossrepo_tracing_haiku_20260228_025547](runs/csb_org_crossrepo_tracing_haiku_20260228_025547.md) | `csb_org_crossrepo` | `baseline-local-direct` | 2 | 0.096 | 0.500 |
| [csb_org_crossrepo_tracing_haiku_20260228_025547](runs/csb_org_crossrepo_tracing_haiku_20260228_025547.md) | `csb_org_crossrepo` | `mcp-remote-direct` | 2 | 0.204 | 0.500 |
| [csb_org_crossrepo_tracing_haiku_20260228_123206](runs/csb_org_crossrepo_tracing_haiku_20260228_123206.md) | `csb_org_crossrepo` | `baseline-local-direct` | 2 | 0.195 | 1.000 |
| [csb_org_crossrepo_tracing_haiku_20260228_124521](runs/csb_org_crossrepo_tracing_haiku_20260228_124521.md) | `csb_org_crossrepo` | `mcp-remote-direct` | 3 | 1.000 | 1.000 |
| [csb_org_crossrepo_tracing_haiku_20260301_173337](runs/csb_org_crossrepo_tracing_haiku_20260301_173337.md) | `csb_org_crossrepo` | `baseline-local-direct` | 11 | 0.000 | 0.000 |
| [csb_org_crossrepo_tracing_haiku_20260301_173337](runs/csb_org_crossrepo_tracing_haiku_20260301_173337.md) | `csb_org_crossrepo` | `mcp-remote-direct` | 2 | 0.000 | 0.000 |
| [csb_org_crossrepo_tracing_haiku_20260301_185444](runs/csb_org_crossrepo_tracing_haiku_20260301_185444.md) | `csb_org_crossrepo` | `baseline-local-direct` | 5 | 0.108 | 0.600 |
| [csb_org_crossrepo_tracing_haiku_20260301_185444](runs/csb_org_crossrepo_tracing_haiku_20260301_185444.md) | `csb_org_crossrepo` | `mcp-remote-direct` | 3 | 0.083 | 0.333 |
| [csb_org_crossrepo_tracing_haiku_20260301_191250](runs/csb_org_crossrepo_tracing_haiku_20260301_191250.md) | `csb_org_crossrepo` | `baseline-local-direct` | 9 | 0.075 | 0.556 |
| [csb_org_crossrepo_tracing_haiku_20260301_191250](runs/csb_org_crossrepo_tracing_haiku_20260301_191250.md) | `csb_org_crossrepo` | `mcp-remote-direct` | 9 | 0.080 | 0.556 |
| [csb_org_crossrepo_tracing_haiku_20260301_195739](runs/csb_org_crossrepo_tracing_haiku_20260301_195739.md) | `csb_org_crossrepo` | `baseline-local-direct` | 11 | 0.069 | 0.545 |
| [csb_org_crossrepo_tracing_haiku_20260301_195739](runs/csb_org_crossrepo_tracing_haiku_20260301_195739.md) | `csb_org_crossrepo` | `mcp-remote-direct` | 11 | 0.081 | 0.545 |
| [csb_org_crossrepo_tracing_haiku_20260301_231457](runs/csb_org_crossrepo_tracing_haiku_20260301_231457.md) | `csb_org_crossrepo` | `baseline-local-direct` | 2 | 0.819 | 1.000 |
| [csb_org_crossrepo_tracing_haiku_20260301_231457](runs/csb_org_crossrepo_tracing_haiku_20260301_231457.md) | `csb_org_crossrepo` | `mcp-remote-direct` | 2 | 0.818 | 1.000 |
| [csb_org_crossrepo_tracing_haiku_20260302_013655](runs/csb_org_crossrepo_tracing_haiku_20260302_013655.md) | `csb_org_crossrepo` | `mcp-remote-direct` | 1 | 0.333 | 1.000 |
| [csb_org_crossrepo_tracing_haiku_20260302_014939](runs/csb_org_crossrepo_tracing_haiku_20260302_014939.md) | `csb_org_crossrepo` | `baseline-local-direct` | 4 | 0.509 | 0.750 |
| [csb_org_crossrepo_tracing_haiku_20260302_014939](runs/csb_org_crossrepo_tracing_haiku_20260302_014939.md) | `csb_org_crossrepo` | `mcp-remote-direct` | 4 | 0.427 | 0.750 |
| [csb_org_crossrepo_tracing_haiku_20260302_022538](runs/csb_org_crossrepo_tracing_haiku_20260302_022538.md) | `csb_org_crossrepo` | `baseline-local-direct` | 2 | 0.875 | 1.000 |
| [csb_org_crossrepo_tracing_haiku_20260302_022538](runs/csb_org_crossrepo_tracing_haiku_20260302_022538.md) | `csb_org_crossrepo` | `mcp-remote-direct` | 2 | 0.834 | 1.000 |
| [csb_org_crossrepo_tracing_haiku_20260302_022540](runs/csb_org_crossrepo_tracing_haiku_20260302_022540.md) | `csb_org_crossrepo` | `mcp-remote-direct` | 1 | 0.500 | 1.000 |
| [csb_org_crossrepo_tracing_haiku_20260302_175821](runs/csb_org_crossrepo_tracing_haiku_20260302_175821.md) | `csb_org_crossrepo` | `baseline-local-direct` | 17 | 0.227 | 0.588 |
| [csb_org_crossrepo_tracing_haiku_20260302_175821](runs/csb_org_crossrepo_tracing_haiku_20260302_175821.md) | `csb_org_crossrepo` | `mcp-remote-direct` | 18 | 0.353 | 0.778 |
| [csb_org_crossrepo_tracing_haiku_20260302_175827](runs/csb_org_crossrepo_tracing_haiku_20260302_175827.md) | `csb_org_crossrepo` | `baseline-local-direct` | 18 | 0.306 | 0.722 |
| [csb_org_crossrepo_tracing_haiku_20260302_175827](runs/csb_org_crossrepo_tracing_haiku_20260302_175827.md) | `csb_org_crossrepo` | `mcp-remote-direct` | 17 | 0.349 | 0.706 |
| [csb_org_crossrepo_tracing_haiku_20260302_183602](runs/csb_org_crossrepo_tracing_haiku_20260302_183602.md) | `csb_org_crossrepo` | `baseline-local-direct` | 5 | 0.841 | 1.000 |
| [csb_org_crossrepo_tracing_haiku_20260302_183602](runs/csb_org_crossrepo_tracing_haiku_20260302_183602.md) | `csb_org_crossrepo` | `mcp-remote-direct` | 5 | 0.914 | 1.000 |
| [csb_org_crossrepo_tracing_haiku_20260302_183608](runs/csb_org_crossrepo_tracing_haiku_20260302_183608.md) | `csb_org_crossrepo` | `baseline-local-direct` | 5 | 0.865 | 1.000 |
| [csb_org_crossrepo_tracing_haiku_20260302_183608](runs/csb_org_crossrepo_tracing_haiku_20260302_183608.md) | `csb_org_crossrepo` | `mcp-remote-direct` | 5 | 0.956 | 1.000 |
| [csb_org_crossrepo_tracing_haiku_20260303_175543](runs/csb_org_crossrepo_tracing_haiku_20260303_175543.md) | `csb_org_crossrepo` | `baseline-local-direct` | 2 | 0.250 | 0.500 |
| [csb_org_crossrepo_tracing_haiku_20260307_030626](runs/csb_org_crossrepo_tracing_haiku_20260307_030626.md) | `csb_org_crossrepo` | `baseline-local-artifact` | 1 | 0.000 | 0.000 |
| [csb_org_crossrepo_tracing_haiku_20260307_030626](runs/csb_org_crossrepo_tracing_haiku_20260307_030626.md) | `csb_org_crossrepo` | `mcp-remote-artifact` | 1 | 0.000 | 0.000 |
| [csb_org_crossrepo_tracing_haiku_20260307_032820](runs/csb_org_crossrepo_tracing_haiku_20260307_032820.md) | `csb_org_crossrepo` | `baseline-local-artifact` | 1 | 0.944 | 1.000 |
| [csb_org_crossrepo_tracing_haiku_20260307_032820](runs/csb_org_crossrepo_tracing_haiku_20260307_032820.md) | `csb_org_crossrepo` | `mcp-remote-artifact` | 1 | 0.770 | 1.000 |
| [csb_org_crossrepo_tracing_sonnet_20260308_034803](runs/csb_org_crossrepo_tracing_sonnet_20260308_034803.md) | `csb_org_crossrepo` | `baseline-local-direct` | 2 | 0.786 | 1.000 |
| [csb_org_crossrepo_tracing_sonnet_20260308_034803](runs/csb_org_crossrepo_tracing_sonnet_20260308_034803.md) | `csb_org_crossrepo` | `mcp-remote-direct` | 2 | 1.000 | 1.000 |
| [csb_org_crossrepo_tracing_sonnet_20260309_013353](runs/csb_org_crossrepo_tracing_sonnet_20260309_013353.md) | `csb_org_crossrepo` | `baseline-local-direct` | 9 | 0.446 | 0.889 |
| [csb_org_crossrepo_tracing_sonnet_20260309_013354](runs/csb_org_crossrepo_tracing_sonnet_20260309_013354.md) | `csb_org_crossrepo` | `mcp-remote-direct` | 9 | 0.376 | 0.778 |
| [csb_org_domain_haiku_20260224_181919](runs/csb_org_domain_haiku_20260224_181919.md) | `csb_org_domain` | `mcp-remote-artifact` | 3 | 0.529 | 1.000 |
| [csb_org_domain_haiku_20260225_011700](runs/csb_org_domain_haiku_20260225_011700.md) | `csb_org_domain` | `baseline-local-artifact` | 3 | 0.000 | 0.000 |
| [csb_org_domain_haiku_20260226_035617](runs/csb_org_domain_haiku_20260226_035617.md) | `csb_org_domain` | `mcp-remote-direct` | 5 | 0.544 | 1.000 |
| [csb_org_domain_haiku_20260226_035622_variance](runs/csb_org_domain_haiku_20260226_035622_variance.md) | `csb_org_domain` | `mcp-remote-direct` | 6 | 0.508 | 1.000 |
| [csb_org_domain_haiku_20260226_035628_variance](runs/csb_org_domain_haiku_20260226_035628_variance.md) | `csb_org_domain` | `mcp-remote-direct` | 6 | 0.627 | 1.000 |
| [csb_org_domain_haiku_20260226_035633_variance](runs/csb_org_domain_haiku_20260226_035633_variance.md) | `csb_org_domain` | `mcp-remote-direct` | 5 | 0.554 | 1.000 |
| [csb_org_domain_haiku_20260226_145828](runs/csb_org_domain_haiku_20260226_145828.md) | `csb_org_domain` | `baseline-local-direct` | 6 | 0.618 | 1.000 |
| [csb_org_domain_haiku_20260226_205845](runs/csb_org_domain_haiku_20260226_205845.md) | `csb_org_domain` | `baseline-local-direct` | 6 | 0.604 | 1.000 |
| [csb_org_domain_haiku_20260226_222632](runs/csb_org_domain_haiku_20260226_222632.md) | `csb_org_domain` | `baseline-local-direct` | 1 | 0.800 | 1.000 |
| [csb_org_domain_haiku_20260226_222632](runs/csb_org_domain_haiku_20260226_222632.md) | `csb_org_domain` | `mcp-remote-direct` | 1 | 0.800 | 1.000 |
| [csb_org_domain_haiku_20260226_224414](runs/csb_org_domain_haiku_20260226_224414.md) | `csb_org_domain` | `baseline-local-direct` | 1 | 0.800 | 1.000 |
| [csb_org_domain_haiku_20260226_224414](runs/csb_org_domain_haiku_20260226_224414.md) | `csb_org_domain` | `mcp-remote-direct` | 1 | 0.800 | 1.000 |
| [csb_org_domain_haiku_20260228_021254](runs/csb_org_domain_haiku_20260228_021254.md) | `csb_org_domain` | `baseline-local-direct` | 10 | 0.567 | 1.000 |
| [csb_org_domain_haiku_20260228_025547](runs/csb_org_domain_haiku_20260228_025547.md) | `csb_org_domain` | `baseline-local-direct` | 3 | 0.418 | 1.000 |
| [csb_org_domain_haiku_20260228_025547](runs/csb_org_domain_haiku_20260228_025547.md) | `csb_org_domain` | `mcp-remote-direct` | 3 | 0.444 | 1.000 |
| [csb_org_domain_haiku_20260228_123206](runs/csb_org_domain_haiku_20260228_123206.md) | `csb_org_domain` | `baseline-local-direct` | 3 | 0.424 | 1.000 |
| [csb_org_domain_haiku_20260301_173337](runs/csb_org_domain_haiku_20260301_173337.md) | `csb_org_domain` | `baseline-local-direct` | 7 | 0.000 | 0.000 |
| [csb_org_domain_haiku_20260301_173337](runs/csb_org_domain_haiku_20260301_173337.md) | `csb_org_domain` | `mcp-remote-direct` | 5 | 0.000 | 0.000 |
| [csb_org_domain_haiku_20260301_185444](runs/csb_org_domain_haiku_20260301_185444.md) | `csb_org_domain` | `baseline-local-direct` | 7 | 0.165 | 0.857 |
| [csb_org_domain_haiku_20260301_185444](runs/csb_org_domain_haiku_20260301_185444.md) | `csb_org_domain` | `mcp-remote-direct` | 2 | 0.000 | 0.000 |
| [csb_org_domain_haiku_20260301_191250](runs/csb_org_domain_haiku_20260301_191250.md) | `csb_org_domain` | `baseline-local-direct` | 8 | 0.186 | 0.875 |
| [csb_org_domain_haiku_20260301_191250](runs/csb_org_domain_haiku_20260301_191250.md) | `csb_org_domain` | `mcp-remote-direct` | 8 | 0.184 | 0.875 |
| [csb_org_domain_haiku_20260301_195739](runs/csb_org_domain_haiku_20260301_195739.md) | `csb_org_domain` | `baseline-local-direct` | 10 | 0.132 | 0.800 |
| [csb_org_domain_haiku_20260301_195739](runs/csb_org_domain_haiku_20260301_195739.md) | `csb_org_domain` | `mcp-remote-direct` | 10 | 0.159 | 0.800 |
| [csb_org_domain_haiku_20260302_014939](runs/csb_org_domain_haiku_20260302_014939.md) | `csb_org_domain` | `baseline-local-direct` | 2 | 0.080 | 0.500 |
| [csb_org_domain_haiku_20260302_014939](runs/csb_org_domain_haiku_20260302_014939.md) | `csb_org_domain` | `mcp-remote-direct` | 2 | 0.000 | 0.000 |
| [csb_org_domain_haiku_20260302_175821](runs/csb_org_domain_haiku_20260302_175821.md) | `csb_org_domain` | `baseline-local-direct` | 14 | 0.256 | 0.857 |
| [csb_org_domain_haiku_20260302_175821](runs/csb_org_domain_haiku_20260302_175821.md) | `csb_org_domain` | `mcp-remote-direct` | 14 | 0.257 | 0.929 |
| [csb_org_domain_haiku_20260302_175827](runs/csb_org_domain_haiku_20260302_175827.md) | `csb_org_domain` | `baseline-local-direct` | 13 | 0.222 | 0.923 |
| [csb_org_domain_haiku_20260302_175827](runs/csb_org_domain_haiku_20260302_175827.md) | `csb_org_domain` | `mcp-remote-direct` | 14 | 0.237 | 0.786 |
| [csb_org_domain_sonnet_20260308_034803](runs/csb_org_domain_sonnet_20260308_034803.md) | `csb_org_domain` | `baseline-local-direct` | 11 | 0.370 | 0.818 |
| [csb_org_domain_sonnet_20260308_034803](runs/csb_org_domain_sonnet_20260308_034803.md) | `csb_org_domain` | `mcp-remote-direct` | 11 | 0.409 | 0.909 |
| [csb_org_incident_haiku_022126](runs/csb_org_incident_haiku_022126.md) | `csb_org_incident` | `baseline-local-artifact` | 1 | 0.500 | 1.000 |
| [csb_org_incident_haiku_022126](runs/csb_org_incident_haiku_022126.md) | `csb_org_incident` | `mcp-remote-artifact` | 1 | 1.000 | 1.000 |
| [csb_org_incident_haiku_20260224_181919](runs/csb_org_incident_haiku_20260224_181919.md) | `csb_org_incident` | `mcp-remote-artifact` | 3 | 0.782 | 1.000 |
| [csb_org_incident_haiku_20260225_011700](runs/csb_org_incident_haiku_20260225_011700.md) | `csb_org_incident` | `baseline-local-artifact` | 3 | 0.167 | 0.333 |
| [csb_org_incident_haiku_20260226_035617](runs/csb_org_incident_haiku_20260226_035617.md) | `csb_org_incident` | `mcp-remote-direct` | 6 | 0.753 | 1.000 |
| [csb_org_incident_haiku_20260226_035622_variance](runs/csb_org_incident_haiku_20260226_035622_variance.md) | `csb_org_incident` | `mcp-remote-direct` | 6 | 0.632 | 1.000 |
| [csb_org_incident_haiku_20260226_035628_variance](runs/csb_org_incident_haiku_20260226_035628_variance.md) | `csb_org_incident` | `mcp-remote-direct` | 6 | 0.661 | 1.000 |
| [csb_org_incident_haiku_20260226_035633_variance](runs/csb_org_incident_haiku_20260226_035633_variance.md) | `csb_org_incident` | `mcp-remote-direct` | 6 | 0.669 | 1.000 |
| [csb_org_incident_haiku_20260226_145828](runs/csb_org_incident_haiku_20260226_145828.md) | `csb_org_incident` | `baseline-local-direct` | 6 | 0.672 | 1.000 |
| [csb_org_incident_haiku_20260226_205845](runs/csb_org_incident_haiku_20260226_205845.md) | `csb_org_incident` | `baseline-local-direct` | 6 | 0.722 | 1.000 |
| [csb_org_incident_haiku_20260226_224414](runs/csb_org_incident_haiku_20260226_224414.md) | `csb_org_incident` | `baseline-local-direct` | 1 | 0.667 | 1.000 |
| [csb_org_incident_haiku_20260226_224414](runs/csb_org_incident_haiku_20260226_224414.md) | `csb_org_incident` | `mcp-remote-direct` | 1 | 0.800 | 1.000 |
| [csb_org_incident_haiku_20260228_021904](runs/csb_org_incident_haiku_20260228_021904.md) | `csb_org_incident` | `baseline-local-direct` | 11 | 0.566 | 0.818 |
| [csb_org_incident_haiku_20260228_025547](runs/csb_org_incident_haiku_20260228_025547.md) | `csb_org_incident` | `baseline-local-direct` | 3 | 0.746 | 1.000 |
| [csb_org_incident_haiku_20260228_025547](runs/csb_org_incident_haiku_20260228_025547.md) | `csb_org_incident` | `mcp-remote-direct` | 3 | 0.779 | 1.000 |
| [csb_org_incident_haiku_20260228_123206](runs/csb_org_incident_haiku_20260228_123206.md) | `csb_org_incident` | `baseline-local-direct` | 3 | 0.723 | 1.000 |
| [csb_org_incident_haiku_20260228_124521](runs/csb_org_incident_haiku_20260228_124521.md) | `csb_org_incident` | `mcp-remote-direct` | 1 | 1.000 | 1.000 |
| [csb_org_incident_haiku_20260301_173337](runs/csb_org_incident_haiku_20260301_173337.md) | `csb_org_incident` | `baseline-local-direct` | 2 | 0.000 | 0.000 |
| [csb_org_incident_haiku_20260301_185444](runs/csb_org_incident_haiku_20260301_185444.md) | `csb_org_incident` | `baseline-local-direct` | 6 | 0.426 | 0.833 |
| [csb_org_incident_haiku_20260301_185444](runs/csb_org_incident_haiku_20260301_185444.md) | `csb_org_incident` | `mcp-remote-direct` | 3 | 0.200 | 0.333 |
| [csb_org_incident_haiku_20260301_191250](runs/csb_org_incident_haiku_20260301_191250.md) | `csb_org_incident` | `baseline-local-direct` | 6 | 0.349 | 1.000 |
| [csb_org_incident_haiku_20260301_191250](runs/csb_org_incident_haiku_20260301_191250.md) | `csb_org_incident` | `mcp-remote-direct` | 6 | 0.357 | 1.000 |
| [csb_org_incident_haiku_20260301_195739](runs/csb_org_incident_haiku_20260301_195739.md) | `csb_org_incident` | `baseline-local-direct` | 9 | 0.314 | 0.778 |
| [csb_org_incident_haiku_20260301_195739](runs/csb_org_incident_haiku_20260301_195739.md) | `csb_org_incident` | `mcp-remote-direct` | 9 | 0.410 | 0.889 |
| [csb_org_incident_haiku_20260302_013655](runs/csb_org_incident_haiku_20260302_013655.md) | `csb_org_incident` | `mcp-remote-direct` | 1 | 1.000 | 1.000 |
| [csb_org_incident_haiku_20260302_014939](runs/csb_org_incident_haiku_20260302_014939.md) | `csb_org_incident` | `baseline-local-direct` | 3 | 0.222 | 0.333 |
| [csb_org_incident_haiku_20260302_014939](runs/csb_org_incident_haiku_20260302_014939.md) | `csb_org_incident` | `mcp-remote-direct` | 3 | 0.167 | 0.333 |
| [csb_org_incident_haiku_20260302_022540](runs/csb_org_incident_haiku_20260302_022540.md) | `csb_org_incident` | `mcp-remote-direct` | 1 | 0.933 | 1.000 |
| [csb_org_incident_haiku_20260302_175821](runs/csb_org_incident_haiku_20260302_175821.md) | `csb_org_incident` | `baseline-local-direct` | 15 | 0.466 | 0.800 |
| [csb_org_incident_haiku_20260302_175821](runs/csb_org_incident_haiku_20260302_175821.md) | `csb_org_incident` | `mcp-remote-direct` | 16 | 0.566 | 0.938 |
| [csb_org_incident_haiku_20260302_175827](runs/csb_org_incident_haiku_20260302_175827.md) | `csb_org_incident` | `baseline-local-direct` | 15 | 0.428 | 0.733 |
| [csb_org_incident_haiku_20260302_175827](runs/csb_org_incident_haiku_20260302_175827.md) | `csb_org_incident` | `mcp-remote-direct` | 14 | 0.622 | 1.000 |
| [csb_org_incident_haiku_20260302_183602](runs/csb_org_incident_haiku_20260302_183602.md) | `csb_org_incident` | `baseline-local-direct` | 3 | 0.630 | 0.667 |
| [csb_org_incident_haiku_20260302_183602](runs/csb_org_incident_haiku_20260302_183602.md) | `csb_org_incident` | `mcp-remote-direct` | 3 | 0.968 | 1.000 |
| [csb_org_incident_haiku_20260302_183608](runs/csb_org_incident_haiku_20260302_183608.md) | `csb_org_incident` | `baseline-local-direct` | 3 | 0.619 | 0.667 |
| [csb_org_incident_haiku_20260302_183608](runs/csb_org_incident_haiku_20260302_183608.md) | `csb_org_incident` | `mcp-remote-direct` | 3 | 0.929 | 1.000 |
| [csb_org_incident_haiku_20260303_175840](runs/csb_org_incident_haiku_20260303_175840.md) | `csb_org_incident` | `baseline-local-direct` | 1 | 0.000 | 0.000 |
| [csb_org_incident_sonnet_20260308_034803](runs/csb_org_incident_sonnet_20260308_034803.md) | `csb_org_incident` | `baseline-local-direct` | 13 | 0.635 | 0.846 |
| [csb_org_incident_sonnet_20260308_034803](runs/csb_org_incident_sonnet_20260308_034803.md) | `csb_org_incident` | `mcp-remote-direct` | 13 | 0.666 | 0.923 |
| [csb_org_migration_haiku_20260226_035617](runs/csb_org_migration_haiku_20260226_035617.md) | `csb_org_migration` | `baseline-local-direct` | 1 | 1.000 | 1.000 |
| [csb_org_migration_haiku_20260226_035617](runs/csb_org_migration_haiku_20260226_035617.md) | `csb_org_migration` | `mcp-remote-direct` | 1 | 1.000 | 1.000 |
| [csb_org_migration_haiku_20260226_035622_variance](runs/csb_org_migration_haiku_20260226_035622_variance.md) | `csb_org_migration` | `baseline-local-direct` | 1 | 1.000 | 1.000 |
| [csb_org_migration_haiku_20260226_035622_variance](runs/csb_org_migration_haiku_20260226_035622_variance.md) | `csb_org_migration` | `mcp-remote-direct` | 1 | 1.000 | 1.000 |
| [csb_org_migration_haiku_20260226_035628_variance](runs/csb_org_migration_haiku_20260226_035628_variance.md) | `csb_org_migration` | `baseline-local-direct` | 1 | 1.000 | 1.000 |
| [csb_org_migration_haiku_20260226_035628_variance](runs/csb_org_migration_haiku_20260226_035628_variance.md) | `csb_org_migration` | `mcp-remote-direct` | 1 | 1.000 | 1.000 |
| [csb_org_migration_haiku_20260226_035633_variance](runs/csb_org_migration_haiku_20260226_035633_variance.md) | `csb_org_migration` | `baseline-local-direct` | 1 | 1.000 | 1.000 |
| [csb_org_migration_haiku_20260226_035633_variance](runs/csb_org_migration_haiku_20260226_035633_variance.md) | `csb_org_migration` | `mcp-remote-direct` | 1 | 1.000 | 1.000 |
| [csb_org_migration_haiku_20260226_145828](runs/csb_org_migration_haiku_20260226_145828.md) | `csb_org_migration` | `baseline-local-direct` | 5 | 0.033 | 0.400 |
| [csb_org_migration_haiku_20260226_214446](runs/csb_org_migration_haiku_20260226_214446.md) | `csb_org_migration` | `baseline-local-direct` | 3 | 0.930 | 1.000 |
| [csb_org_migration_haiku_20260226_221038](runs/csb_org_migration_haiku_20260226_221038.md) | `csb_org_migration` | `mcp-remote-direct` | 3 | 0.917 | 1.000 |
| [csb_org_migration_haiku_20260226_231458](runs/csb_org_migration_haiku_20260226_231458.md) | `csb_org_migration` | `baseline-local-direct` | 3 | 0.639 | 1.000 |
| [csb_org_migration_haiku_20260226_231458](runs/csb_org_migration_haiku_20260226_231458.md) | `csb_org_migration` | `mcp-remote-direct` | 3 | 0.771 | 1.000 |
| [csb_org_migration_haiku_20260228_011912](runs/csb_org_migration_haiku_20260228_011912.md) | `csb_org_migration` | `baseline-local-direct` | 7 | 0.801 | 1.000 |
| [csb_org_migration_haiku_20260228_011912](runs/csb_org_migration_haiku_20260228_011912.md) | `csb_org_migration` | `mcp-remote-direct` | 7 | 0.804 | 1.000 |
| [csb_org_migration_haiku_20260301_173337](runs/csb_org_migration_haiku_20260301_173337.md) | `csb_org_migration` | `baseline-local-direct` | 2 | 0.000 | 0.000 |
| [csb_org_migration_haiku_20260301_173337](runs/csb_org_migration_haiku_20260301_173337.md) | `csb_org_migration` | `mcp-remote-direct` | 2 | 0.000 | 0.000 |
| [csb_org_migration_haiku_20260301_185444](runs/csb_org_migration_haiku_20260301_185444.md) | `csb_org_migration` | `baseline-local-direct` | 4 | 0.039 | 0.500 |
| [csb_org_migration_haiku_20260301_185444](runs/csb_org_migration_haiku_20260301_185444.md) | `csb_org_migration` | `mcp-remote-direct` | 6 | 0.151 | 0.667 |
| [csb_org_migration_haiku_20260301_191250](runs/csb_org_migration_haiku_20260301_191250.md) | `csb_org_migration` | `baseline-local-direct` | 12 | 0.115 | 0.917 |
| [csb_org_migration_haiku_20260301_191250](runs/csb_org_migration_haiku_20260301_191250.md) | `csb_org_migration` | `mcp-remote-direct` | 12 | 0.135 | 0.833 |
| [csb_org_migration_haiku_20260301_195739](runs/csb_org_migration_haiku_20260301_195739.md) | `csb_org_migration` | `baseline-local-direct` | 13 | 0.100 | 0.692 |
| [csb_org_migration_haiku_20260301_195739](runs/csb_org_migration_haiku_20260301_195739.md) | `csb_org_migration` | `mcp-remote-direct` | 13 | 0.094 | 0.615 |
| [csb_org_migration_haiku_20260301_231457](runs/csb_org_migration_haiku_20260301_231457.md) | `csb_org_migration` | `baseline-local-direct` | 5 | 0.570 | 1.000 |
| [csb_org_migration_haiku_20260301_231457](runs/csb_org_migration_haiku_20260301_231457.md) | `csb_org_migration` | `mcp-remote-direct` | 6 | 0.632 | 1.000 |
| [csb_org_migration_haiku_20260301_235018](runs/csb_org_migration_haiku_20260301_235018.md) | `csb_org_migration` | `baseline-local-direct` | 1 | 0.741 | 1.000 |
| [csb_org_migration_haiku_20260302_014939](runs/csb_org_migration_haiku_20260302_014939.md) | `csb_org_migration` | `baseline-local-direct` | 7 | 0.492 | 0.857 |
| [csb_org_migration_haiku_20260302_014939](runs/csb_org_migration_haiku_20260302_014939.md) | `csb_org_migration` | `mcp-remote-direct` | 7 | 0.612 | 0.857 |
| [csb_org_migration_haiku_20260302_022538](runs/csb_org_migration_haiku_20260302_022538.md) | `csb_org_migration` | `baseline-local-direct` | 6 | 0.583 | 1.000 |
| [csb_org_migration_haiku_20260302_022538](runs/csb_org_migration_haiku_20260302_022538.md) | `csb_org_migration` | `mcp-remote-direct` | 6 | 0.765 | 1.000 |
| [csb_org_migration_haiku_20260302_175821](runs/csb_org_migration_haiku_20260302_175821.md) | `csb_org_migration` | `baseline-local-direct` | 25 | 0.335 | 0.840 |
| [csb_org_migration_haiku_20260302_175821](runs/csb_org_migration_haiku_20260302_175821.md) | `csb_org_migration` | `mcp-remote-direct` | 24 | 0.344 | 0.750 |
| [csb_org_migration_haiku_20260303_141005](runs/csb_org_migration_haiku_20260303_141005.md) | `csb_org_migration` | `baseline-local-direct` | 1 | 0.769 | 1.000 |
| [csb_org_migration_haiku_20260303_142451](runs/csb_org_migration_haiku_20260303_142451.md) | `csb_org_migration` | `baseline-local-direct` | 1 | 0.850 | 1.000 |
| [csb_org_migration_haiku_20260307_030626](runs/csb_org_migration_haiku_20260307_030626.md) | `csb_org_migration` | `baseline-local-artifact` | 1 | 0.000 | 0.000 |
| [csb_org_migration_haiku_20260307_030626](runs/csb_org_migration_haiku_20260307_030626.md) | `csb_org_migration` | `mcp-remote-artifact` | 2 | 0.000 | 0.000 |
| [csb_org_migration_haiku_20260307_032820](runs/csb_org_migration_haiku_20260307_032820.md) | `csb_org_migration` | `mcp-remote-artifact` | 1 | 0.674 | 1.000 |
| [csb_org_migration_haiku_20260307_033308](runs/csb_org_migration_haiku_20260307_033308.md) | `csb_org_migration` | `baseline-local-artifact` | 1 | 0.568 | 1.000 |
| [csb_org_migration_haiku_20260307_033308](runs/csb_org_migration_haiku_20260307_033308.md) | `csb_org_migration` | `mcp-remote-artifact` | 1 | 0.555 | 1.000 |
| [csb_org_migration_sonnet_20260308_034803](runs/csb_org_migration_sonnet_20260308_034803.md) | `csb_org_migration` | `baseline-local-direct` | 25 | 0.303 | 0.920 |
| [csb_org_migration_sonnet_20260308_034803](runs/csb_org_migration_sonnet_20260308_034803.md) | `csb_org_migration` | `mcp-remote-direct` | 25 | 0.351 | 0.960 |
| [csb_org_onboarding_haiku_022126](runs/csb_org_onboarding_haiku_022126.md) | `csb_org_onboarding` | `baseline-local-artifact` | 3 | 0.639 | 1.000 |
| [csb_org_onboarding_haiku_022126](runs/csb_org_onboarding_haiku_022126.md) | `csb_org_onboarding` | `mcp-remote-artifact` | 3 | 0.778 | 1.000 |
| [csb_org_onboarding_haiku_20260224_181919](runs/csb_org_onboarding_haiku_20260224_181919.md) | `csb_org_onboarding` | `mcp-remote-artifact` | 4 | 0.843 | 1.000 |
| [csb_org_onboarding_haiku_20260225_011700](runs/csb_org_onboarding_haiku_20260225_011700.md) | `csb_org_onboarding` | `baseline-local-artifact` | 4 | 0.000 | 0.000 |
| [csb_org_onboarding_haiku_20260226_035617](runs/csb_org_onboarding_haiku_20260226_035617.md) | `csb_org_onboarding` | `mcp-remote-direct` | 4 | 0.501 | 1.000 |
| [csb_org_onboarding_haiku_20260226_035622_variance](runs/csb_org_onboarding_haiku_20260226_035622_variance.md) | `csb_org_onboarding` | `mcp-remote-direct` | 4 | 0.452 | 1.000 |
| [csb_org_onboarding_haiku_20260226_035628_variance](runs/csb_org_onboarding_haiku_20260226_035628_variance.md) | `csb_org_onboarding` | `mcp-remote-direct` | 4 | 0.550 | 1.000 |
| [csb_org_onboarding_haiku_20260226_035633_variance](runs/csb_org_onboarding_haiku_20260226_035633_variance.md) | `csb_org_onboarding` | `mcp-remote-direct` | 4 | 0.472 | 1.000 |
| [csb_org_onboarding_haiku_20260226_145828](runs/csb_org_onboarding_haiku_20260226_145828.md) | `csb_org_onboarding` | `baseline-local-direct` | 3 | 0.539 | 1.000 |
| [csb_org_onboarding_haiku_20260226_205845](runs/csb_org_onboarding_haiku_20260226_205845.md) | `csb_org_onboarding` | `baseline-local-direct` | 3 | 0.540 | 1.000 |
| [csb_org_onboarding_haiku_20260226_231458](runs/csb_org_onboarding_haiku_20260226_231458.md) | `csb_org_onboarding` | `baseline-local-direct` | 1 | 0.473 | 1.000 |
| [csb_org_onboarding_haiku_20260226_231458](runs/csb_org_onboarding_haiku_20260226_231458.md) | `csb_org_onboarding` | `mcp-remote-direct` | 1 | 0.432 | 1.000 |
| [csb_org_onboarding_haiku_20260227_132300](runs/csb_org_onboarding_haiku_20260227_132300.md) | `csb_org_onboarding` | `baseline-local-direct` | 14 | 0.936 | 1.000 |
| [csb_org_onboarding_haiku_20260227_132300](runs/csb_org_onboarding_haiku_20260227_132300.md) | `csb_org_onboarding` | `mcp-remote-direct` | 12 | 1.000 | 1.000 |
| [csb_org_onboarding_haiku_20260227_132304](runs/csb_org_onboarding_haiku_20260227_132304.md) | `csb_org_onboarding` | `baseline-local-direct` | 14 | 0.864 | 0.929 |
| [csb_org_onboarding_haiku_20260227_132304](runs/csb_org_onboarding_haiku_20260227_132304.md) | `csb_org_onboarding` | `mcp-remote-direct` | 12 | 1.000 | 1.000 |
| [csb_org_onboarding_haiku_20260228_023118](runs/csb_org_onboarding_haiku_20260228_023118.md) | `csb_org_onboarding` | `baseline-local-direct` | 25 | 0.784 | 0.960 |
| [csb_org_onboarding_haiku_20260228_025547](runs/csb_org_onboarding_haiku_20260228_025547.md) | `csb_org_onboarding` | `baseline-local-direct` | 4 | 0.843 | 1.000 |
| [csb_org_onboarding_haiku_20260228_025547](runs/csb_org_onboarding_haiku_20260228_025547.md) | `csb_org_onboarding` | `mcp-remote-direct` | 4 | 0.843 | 1.000 |
| [csb_org_onboarding_haiku_20260228_123206](runs/csb_org_onboarding_haiku_20260228_123206.md) | `csb_org_onboarding` | `baseline-local-direct` | 4 | 0.779 | 1.000 |
| [csb_org_onboarding_haiku_20260228_124521](runs/csb_org_onboarding_haiku_20260228_124521.md) | `csb_org_onboarding` | `mcp-remote-direct` | 17 | 0.931 | 1.000 |
| [csb_org_onboarding_haiku_20260301_173337](runs/csb_org_onboarding_haiku_20260301_173337.md) | `csb_org_onboarding` | `baseline-local-direct` | 2 | 0.000 | 0.000 |
| [csb_org_onboarding_haiku_20260301_173337](runs/csb_org_onboarding_haiku_20260301_173337.md) | `csb_org_onboarding` | `mcp-remote-direct` | 1 | 0.000 | 0.000 |
| [csb_org_onboarding_haiku_20260301_185444](runs/csb_org_onboarding_haiku_20260301_185444.md) | `csb_org_onboarding` | `mcp-remote-direct` | 1 | 0.016 | 1.000 |
| [csb_org_onboarding_haiku_20260301_191250](runs/csb_org_onboarding_haiku_20260301_191250.md) | `csb_org_onboarding` | `baseline-local-direct` | 2 | 0.008 | 0.500 |
| [csb_org_onboarding_haiku_20260301_191250](runs/csb_org_onboarding_haiku_20260301_191250.md) | `csb_org_onboarding` | `mcp-remote-direct` | 2 | 0.015 | 0.500 |
| [csb_org_onboarding_haiku_20260301_195739](runs/csb_org_onboarding_haiku_20260301_195739.md) | `csb_org_onboarding` | `baseline-local-direct` | 2 | 0.036 | 0.500 |
| [csb_org_onboarding_haiku_20260301_195739](runs/csb_org_onboarding_haiku_20260301_195739.md) | `csb_org_onboarding` | `mcp-remote-direct` | 2 | 0.015 | 0.500 |
| [csb_org_onboarding_haiku_20260301_231457](runs/csb_org_onboarding_haiku_20260301_231457.md) | `csb_org_onboarding` | `baseline-local-direct` | 8 | 0.626 | 0.875 |
| [csb_org_onboarding_haiku_20260301_231457](runs/csb_org_onboarding_haiku_20260301_231457.md) | `csb_org_onboarding` | `mcp-remote-direct` | 8 | 0.735 | 1.000 |
| [csb_org_onboarding_haiku_20260302_014939](runs/csb_org_onboarding_haiku_20260302_014939.md) | `csb_org_onboarding` | `baseline-local-direct` | 1 | 0.962 | 1.000 |
| [csb_org_onboarding_haiku_20260302_014939](runs/csb_org_onboarding_haiku_20260302_014939.md) | `csb_org_onboarding` | `mcp-remote-direct` | 1 | 1.000 | 1.000 |
| [csb_org_onboarding_haiku_20260302_022538](runs/csb_org_onboarding_haiku_20260302_022538.md) | `csb_org_onboarding` | `baseline-local-direct` | 1 | 0.928 | 1.000 |
| [csb_org_onboarding_haiku_20260302_022538](runs/csb_org_onboarding_haiku_20260302_022538.md) | `csb_org_onboarding` | `mcp-remote-direct` | 1 | 1.000 | 1.000 |
| [csb_org_onboarding_haiku_20260302_030627](runs/csb_org_onboarding_haiku_20260302_030627.md) | `csb_org_onboarding` | `mcp-remote-direct` | 2 | 1.000 | 1.000 |
| [csb_org_onboarding_haiku_20260302_175821](runs/csb_org_onboarding_haiku_20260302_175821.md) | `csb_org_onboarding` | `baseline-local-direct` | 18 | 0.823 | 0.944 |
| [csb_org_onboarding_haiku_20260302_175821](runs/csb_org_onboarding_haiku_20260302_175821.md) | `csb_org_onboarding` | `mcp-remote-direct` | 18 | 0.769 | 1.000 |
| [csb_org_onboarding_haiku_20260302_175827](runs/csb_org_onboarding_haiku_20260302_175827.md) | `csb_org_onboarding` | `baseline-local-direct` | 21 | 0.807 | 0.952 |
| [csb_org_onboarding_haiku_20260302_175827](runs/csb_org_onboarding_haiku_20260302_175827.md) | `csb_org_onboarding` | `mcp-remote-direct` | 19 | 0.734 | 0.895 |
| [csb_org_onboarding_haiku_20260302_183602](runs/csb_org_onboarding_haiku_20260302_183602.md) | `csb_org_onboarding` | `baseline-local-direct` | 18 | 0.882 | 0.944 |
| [csb_org_onboarding_haiku_20260302_183602](runs/csb_org_onboarding_haiku_20260302_183602.md) | `csb_org_onboarding` | `mcp-remote-direct` | 18 | 0.896 | 1.000 |
| [csb_org_onboarding_haiku_20260302_183608](runs/csb_org_onboarding_haiku_20260302_183608.md) | `csb_org_onboarding` | `baseline-local-direct` | 18 | 0.792 | 0.889 |
| [csb_org_onboarding_haiku_20260302_183608](runs/csb_org_onboarding_haiku_20260302_183608.md) | `csb_org_onboarding` | `mcp-remote-direct` | 18 | 0.917 | 1.000 |
| [csb_org_onboarding_haiku_20260302_210829](runs/csb_org_onboarding_haiku_20260302_210829.md) | `csb_org_onboarding` | `baseline-local-direct` | 1 | 0.000 | 0.000 |
| [csb_org_onboarding_haiku_20260302_210829](runs/csb_org_onboarding_haiku_20260302_210829.md) | `csb_org_onboarding` | `mcp-remote-direct` | 1 | 0.750 | 1.000 |
| [csb_org_onboarding_haiku_20260302_210835](runs/csb_org_onboarding_haiku_20260302_210835.md) | `csb_org_onboarding` | `baseline-local-direct` | 1 | 0.000 | 0.000 |
| [csb_org_onboarding_haiku_20260302_210835](runs/csb_org_onboarding_haiku_20260302_210835.md) | `csb_org_onboarding` | `mcp-remote-direct` | 1 | 0.500 | 1.000 |
| [csb_org_onboarding_haiku_20260302_210842](runs/csb_org_onboarding_haiku_20260302_210842.md) | `csb_org_onboarding` | `mcp-remote-direct` | 1 | 0.500 | 1.000 |
| [csb_org_onboarding_haiku_20260302_212645](runs/csb_org_onboarding_haiku_20260302_212645.md) | `csb_org_onboarding` | `mcp-remote-direct` | 1 | 0.432 | 1.000 |
| [csb_org_onboarding_haiku_20260302_221754](runs/csb_org_onboarding_haiku_20260302_221754.md) | `csb_org_onboarding` | `mcp-remote-direct` | 1 | 0.708 | 1.000 |
| [csb_org_onboarding_haiku_20260303_175913](runs/csb_org_onboarding_haiku_20260303_175913.md) | `csb_org_onboarding` | `baseline-local-direct` | 1 | 0.000 | 0.000 |
| [csb_org_onboarding_haiku_20260309_223654](runs/csb_org_onboarding_haiku_20260309_223654.md) | `csb_org_onboarding` | `baseline-local-direct` | 3 | 0.767 | 0.667 |
| [csb_org_onboarding_haiku_20260309_223654](runs/csb_org_onboarding_haiku_20260309_223654.md) | `csb_org_onboarding` | `mcp-remote-direct` | 3 | 1.000 | 1.000 |
| [csb_org_onboarding_sonnet_20260308_034803](runs/csb_org_onboarding_sonnet_20260308_034803.md) | `csb_org_onboarding` | `baseline-local-direct` | 5 | 0.853 | 1.000 |
| [csb_org_onboarding_sonnet_20260308_034803](runs/csb_org_onboarding_sonnet_20260308_034803.md) | `csb_org_onboarding` | `mcp-remote-direct` | 3 | 0.764 | 1.000 |
| [csb_org_onboarding_sonnet_20260309_013353](runs/csb_org_onboarding_sonnet_20260309_013353.md) | `csb_org_onboarding` | `baseline-local-direct` | 6 | 1.000 | 1.000 |
| [csb_org_onboarding_sonnet_20260309_013354](runs/csb_org_onboarding_sonnet_20260309_013354.md) | `csb_org_onboarding` | `mcp-remote-direct` | 2 | 1.000 | 1.000 |
| [csb_org_onboarding_sonnet_20260309_142738](runs/csb_org_onboarding_sonnet_20260309_142738.md) | `csb_org_onboarding` | `mcp-remote-direct` | 3 | 1.000 | 1.000 |
| [csb_org_org_haiku_20260224_181919](runs/csb_org_org_haiku_20260224_181919.md) | `csb_org_org` | `mcp-remote-artifact` | 2 | 0.705 | 1.000 |
| [csb_org_org_haiku_20260225_011700](runs/csb_org_org_haiku_20260225_011700.md) | `csb_org_org` | `baseline-local-artifact` | 2 | 0.500 | 1.000 |
| [csb_org_org_haiku_20260226_035617](runs/csb_org_org_haiku_20260226_035617.md) | `csb_org_org` | `mcp-remote-direct` | 3 | 0.503 | 1.000 |
| [csb_org_org_haiku_20260226_035622_variance](runs/csb_org_org_haiku_20260226_035622_variance.md) | `csb_org_org` | `mcp-remote-direct` | 3 | 0.557 | 1.000 |
| [csb_org_org_haiku_20260226_035628_variance](runs/csb_org_org_haiku_20260226_035628_variance.md) | `csb_org_org` | `mcp-remote-direct` | 3 | 0.497 | 1.000 |
| [csb_org_org_haiku_20260226_035633_variance](runs/csb_org_org_haiku_20260226_035633_variance.md) | `csb_org_org` | `mcp-remote-direct` | 3 | 0.515 | 1.000 |
| [csb_org_org_haiku_20260226_145828](runs/csb_org_org_haiku_20260226_145828.md) | `csb_org_org` | `baseline-local-direct` | 3 | 0.385 | 1.000 |
| [csb_org_org_haiku_20260226_205845](runs/csb_org_org_haiku_20260226_205845.md) | `csb_org_org` | `baseline-local-direct` | 3 | 0.404 | 1.000 |
| [csb_org_org_haiku_20260228_010402](runs/csb_org_org_haiku_20260228_010402.md) | `csb_org_org` | `baseline-local-direct` | 5 | 0.543 | 1.000 |
| [csb_org_org_haiku_20260228_010402](runs/csb_org_org_haiku_20260228_010402.md) | `csb_org_org` | `mcp-remote-direct` | 5 | 0.592 | 1.000 |
| [csb_org_org_haiku_20260228_051032](runs/csb_org_org_haiku_20260228_051032.md) | `csb_org_org` | `baseline-local-direct` | 1 | 0.720 | 1.000 |
| [csb_org_org_haiku_20260228_123206](runs/csb_org_org_haiku_20260228_123206.md) | `csb_org_org` | `baseline-local-direct` | 2 | 0.683 | 1.000 |
| [csb_org_org_haiku_20260228_133005](runs/csb_org_org_haiku_20260228_133005.md) | `csb_org_org` | `baseline-local-direct` | 1 | 0.574 | 1.000 |
| [csb_org_org_haiku_20260301_173337](runs/csb_org_org_haiku_20260301_173337.md) | `csb_org_org` | `baseline-local-direct` | 2 | 0.000 | 0.000 |
| [csb_org_org_haiku_20260301_173337](runs/csb_org_org_haiku_20260301_173337.md) | `csb_org_org` | `mcp-remote-direct` | 7 | 0.000 | 0.000 |
| [csb_org_org_haiku_20260301_185444](runs/csb_org_org_haiku_20260301_185444.md) | `csb_org_org` | `baseline-local-direct` | 3 | 0.000 | 0.000 |
| [csb_org_org_haiku_20260301_185444](runs/csb_org_org_haiku_20260301_185444.md) | `csb_org_org` | `mcp-remote-direct` | 6 | 0.000 | 0.000 |
| [csb_org_org_haiku_20260301_191250](runs/csb_org_org_haiku_20260301_191250.md) | `csb_org_org` | `baseline-local-direct` | 8 | 0.000 | 0.000 |
| [csb_org_org_haiku_20260301_191250](runs/csb_org_org_haiku_20260301_191250.md) | `csb_org_org` | `mcp-remote-direct` | 13 | 0.000 | 0.000 |
| [csb_org_org_haiku_20260301_195739](runs/csb_org_org_haiku_20260301_195739.md) | `csb_org_org` | `baseline-local-direct` | 10 | 0.411 | 1.000 |
| [csb_org_org_haiku_20260301_195739](runs/csb_org_org_haiku_20260301_195739.md) | `csb_org_org` | `mcp-remote-direct` | 15 | 0.338 | 0.933 |
| [csb_org_org_haiku_20260302_014939](runs/csb_org_org_haiku_20260302_014939.md) | `csb_org_org` | `baseline-local-direct` | 2 | 0.282 | 1.000 |
| [csb_org_org_haiku_20260302_014939](runs/csb_org_org_haiku_20260302_014939.md) | `csb_org_org` | `mcp-remote-direct` | 2 | 0.274 | 1.000 |
| [csb_org_org_haiku_20260302_175821](runs/csb_org_org_haiku_20260302_175821.md) | `csb_org_org` | `baseline-local-direct` | 12 | 0.381 | 1.000 |
| [csb_org_org_haiku_20260302_175821](runs/csb_org_org_haiku_20260302_175821.md) | `csb_org_org` | `mcp-remote-direct` | 12 | 0.427 | 1.000 |
| [csb_org_org_haiku_20260302_175827](runs/csb_org_org_haiku_20260302_175827.md) | `csb_org_org` | `baseline-local-direct` | 11 | 0.402 | 0.909 |
| [csb_org_org_haiku_20260302_175827](runs/csb_org_org_haiku_20260302_175827.md) | `csb_org_org` | `mcp-remote-direct` | 11 | 0.454 | 1.000 |
| [csb_org_org_haiku_20260307_030626](runs/csb_org_org_haiku_20260307_030626.md) | `csb_org_org` | `baseline-local-artifact` | 1 | 0.000 | 0.000 |
| [csb_org_org_haiku_20260307_030626](runs/csb_org_org_haiku_20260307_030626.md) | `csb_org_org` | `mcp-remote-artifact` | 1 | 0.000 | 0.000 |
| [csb_org_org_sonnet_20260308_034803](runs/csb_org_org_sonnet_20260308_034803.md) | `csb_org_org` | `baseline-local-direct` | 11 | 0.380 | 1.000 |
| [csb_org_org_sonnet_20260308_034803](runs/csb_org_org_sonnet_20260308_034803.md) | `csb_org_org` | `mcp-remote-direct` | 11 | 0.400 | 1.000 |
| [csb_org_platform_haiku_20260226_035617](runs/csb_org_platform_haiku_20260226_035617.md) | `csb_org_platform` | `baseline-local-direct` | 2 | 0.744 | 1.000 |
| [csb_org_platform_haiku_20260226_035617](runs/csb_org_platform_haiku_20260226_035617.md) | `csb_org_platform` | `mcp-remote-direct` | 3 | 0.544 | 1.000 |
| [csb_org_platform_haiku_20260226_035622_variance](runs/csb_org_platform_haiku_20260226_035622_variance.md) | `csb_org_platform` | `baseline-local-direct` | 2 | 0.728 | 1.000 |
| [csb_org_platform_haiku_20260226_035622_variance](runs/csb_org_platform_haiku_20260226_035622_variance.md) | `csb_org_platform` | `mcp-remote-direct` | 3 | 0.572 | 1.000 |
| [csb_org_platform_haiku_20260226_035628_variance](runs/csb_org_platform_haiku_20260226_035628_variance.md) | `csb_org_platform` | `baseline-local-direct` | 2 | 0.744 | 1.000 |
| [csb_org_platform_haiku_20260226_035628_variance](runs/csb_org_platform_haiku_20260226_035628_variance.md) | `csb_org_platform` | `mcp-remote-direct` | 3 | 0.635 | 1.000 |
| [csb_org_platform_haiku_20260226_035633_variance](runs/csb_org_platform_haiku_20260226_035633_variance.md) | `csb_org_platform` | `baseline-local-direct` | 2 | 0.717 | 1.000 |
| [csb_org_platform_haiku_20260226_035633_variance](runs/csb_org_platform_haiku_20260226_035633_variance.md) | `csb_org_platform` | `mcp-remote-direct` | 3 | 0.552 | 1.000 |
| [csb_org_platform_haiku_20260226_145828](runs/csb_org_platform_haiku_20260226_145828.md) | `csb_org_platform` | `baseline-local-direct` | 2 | 0.292 | 0.500 |
| [csb_org_platform_haiku_20260226_205845](runs/csb_org_platform_haiku_20260226_205845.md) | `csb_org_platform` | `baseline-local-direct` | 1 | 0.583 | 1.000 |
| [csb_org_platform_haiku_20260226_214446](runs/csb_org_platform_haiku_20260226_214446.md) | `csb_org_platform` | `baseline-local-direct` | 1 | 0.632 | 1.000 |
| [csb_org_platform_haiku_20260226_221038](runs/csb_org_platform_haiku_20260226_221038.md) | `csb_org_platform` | `mcp-remote-direct` | 1 | 0.556 | 1.000 |
| [csb_org_platform_haiku_20260228_010919](runs/csb_org_platform_haiku_20260228_010919.md) | `csb_org_platform` | `baseline-local-direct` | 4 | 0.652 | 1.000 |
| [csb_org_platform_haiku_20260228_010919](runs/csb_org_platform_haiku_20260228_010919.md) | `csb_org_platform` | `mcp-remote-direct` | 5 | 0.597 | 1.000 |
| [csb_org_platform_haiku_20260301_173337](runs/csb_org_platform_haiku_20260301_173337.md) | `csb_org_platform` | `baseline-local-direct` | 2 | 0.000 | 0.000 |
| [csb_org_platform_haiku_20260301_173337](runs/csb_org_platform_haiku_20260301_173337.md) | `csb_org_platform` | `mcp-remote-direct` | 5 | 0.000 | 0.000 |
| [csb_org_platform_haiku_20260301_185444](runs/csb_org_platform_haiku_20260301_185444.md) | `csb_org_platform` | `baseline-local-direct` | 8 | 0.233 | 1.000 |
| [csb_org_platform_haiku_20260301_185444](runs/csb_org_platform_haiku_20260301_185444.md) | `csb_org_platform` | `mcp-remote-direct` | 9 | 0.112 | 0.889 |
| [csb_org_platform_haiku_20260301_191250](runs/csb_org_platform_haiku_20260301_191250.md) | `csb_org_platform` | `baseline-local-direct` | 9 | 0.216 | 1.000 |
| [csb_org_platform_haiku_20260301_191250](runs/csb_org_platform_haiku_20260301_191250.md) | `csb_org_platform` | `mcp-remote-direct` | 11 | 0.192 | 0.909 |
| [csb_org_platform_haiku_20260301_195739](runs/csb_org_platform_haiku_20260301_195739.md) | `csb_org_platform` | `baseline-local-direct` | 14 | 0.204 | 1.000 |
| [csb_org_platform_haiku_20260301_195739](runs/csb_org_platform_haiku_20260301_195739.md) | `csb_org_platform` | `mcp-remote-direct` | 16 | 0.147 | 0.938 |
| [csb_org_platform_haiku_20260302_014939](runs/csb_org_platform_haiku_20260302_014939.md) | `csb_org_platform` | `baseline-local-direct` | 5 | 0.241 | 1.000 |
| [csb_org_platform_haiku_20260302_014939](runs/csb_org_platform_haiku_20260302_014939.md) | `csb_org_platform` | `mcp-remote-direct` | 5 | 0.173 | 1.000 |
| [csb_org_platform_haiku_20260302_175821](runs/csb_org_platform_haiku_20260302_175821.md) | `csb_org_platform` | `baseline-local-direct` | 14 | 0.277 | 0.929 |
| [csb_org_platform_haiku_20260302_175821](runs/csb_org_platform_haiku_20260302_175821.md) | `csb_org_platform` | `mcp-remote-direct` | 15 | 0.251 | 0.933 |
| [csb_org_platform_haiku_20260302_175827](runs/csb_org_platform_haiku_20260302_175827.md) | `csb_org_platform` | `baseline-local-direct` | 16 | 0.224 | 0.812 |
| [csb_org_platform_haiku_20260302_175827](runs/csb_org_platform_haiku_20260302_175827.md) | `csb_org_platform` | `mcp-remote-direct` | 14 | 0.233 | 0.929 |
| [csb_org_platform_haiku_20260302_183602](runs/csb_org_platform_haiku_20260302_183602.md) | `csb_org_platform` | `baseline-local-direct` | 2 | 0.753 | 1.000 |
| [csb_org_platform_haiku_20260302_183602](runs/csb_org_platform_haiku_20260302_183602.md) | `csb_org_platform` | `mcp-remote-direct` | 2 | 0.567 | 1.000 |
| [csb_org_platform_haiku_20260302_183608](runs/csb_org_platform_haiku_20260302_183608.md) | `csb_org_platform` | `baseline-local-direct` | 2 | 0.762 | 1.000 |
| [csb_org_platform_haiku_20260302_183608](runs/csb_org_platform_haiku_20260302_183608.md) | `csb_org_platform` | `mcp-remote-direct` | 2 | 0.507 | 1.000 |
| [csb_org_platform_haiku_20260307_030626](runs/csb_org_platform_haiku_20260307_030626.md) | `csb_org_platform` | `baseline-local-artifact` | 2 | 0.000 | 0.000 |
| [csb_org_platform_haiku_20260307_030626](runs/csb_org_platform_haiku_20260307_030626.md) | `csb_org_platform` | `mcp-remote-artifact` | 2 | 0.000 | 0.000 |
| [csb_org_platform_sonnet_20260308_034803](runs/csb_org_platform_sonnet_20260308_034803.md) | `csb_org_platform` | `baseline-local-direct` | 13 | 0.340 | 0.923 |
| [csb_org_platform_sonnet_20260308_034803](runs/csb_org_platform_sonnet_20260308_034803.md) | `csb_org_platform` | `mcp-remote-direct` | 13 | 0.328 | 0.923 |
| [csb_org_security_haiku_022126](runs/csb_org_security_haiku_022126.md) | `csb_org_security` | `baseline-local-artifact` | 2 | 0.500 | 1.000 |
| [csb_org_security_haiku_022126](runs/csb_org_security_haiku_022126.md) | `csb_org_security` | `mcp-remote-artifact` | 2 | 0.821 | 1.000 |
| [csb_org_security_haiku_20260224_181919](runs/csb_org_security_haiku_20260224_181919.md) | `csb_org_security` | `mcp-remote-artifact` | 4 | 0.777 | 1.000 |
| [csb_org_security_haiku_20260225_011700](runs/csb_org_security_haiku_20260225_011700.md) | `csb_org_security` | `baseline-local-artifact` | 4 | 0.000 | 0.000 |
| [csb_org_security_haiku_20260226_035617](runs/csb_org_security_haiku_20260226_035617.md) | `csb_org_security` | `baseline-local-direct` | 1 | 0.433 | 1.000 |
| [csb_org_security_haiku_20260226_035617](runs/csb_org_security_haiku_20260226_035617.md) | `csb_org_security` | `mcp-remote-direct` | 4 | 0.744 | 1.000 |
| [csb_org_security_haiku_20260226_035622_variance](runs/csb_org_security_haiku_20260226_035622_variance.md) | `csb_org_security` | `baseline-local-direct` | 1 | 0.514 | 1.000 |
| [csb_org_security_haiku_20260226_035622_variance](runs/csb_org_security_haiku_20260226_035622_variance.md) | `csb_org_security` | `mcp-remote-direct` | 4 | 0.578 | 1.000 |
| [csb_org_security_haiku_20260226_035628_variance](runs/csb_org_security_haiku_20260226_035628_variance.md) | `csb_org_security` | `baseline-local-direct` | 1 | 0.367 | 1.000 |
| [csb_org_security_haiku_20260226_035628_variance](runs/csb_org_security_haiku_20260226_035628_variance.md) | `csb_org_security` | `mcp-remote-direct` | 4 | 0.767 | 1.000 |
| [csb_org_security_haiku_20260226_035633_variance](runs/csb_org_security_haiku_20260226_035633_variance.md) | `csb_org_security` | `baseline-local-direct` | 1 | 0.586 | 1.000 |
| [csb_org_security_haiku_20260226_035633_variance](runs/csb_org_security_haiku_20260226_035633_variance.md) | `csb_org_security` | `mcp-remote-direct` | 4 | 0.731 | 1.000 |
| [csb_org_security_haiku_20260226_145828](runs/csb_org_security_haiku_20260226_145828.md) | `csb_org_security` | `baseline-local-direct` | 3 | 0.641 | 1.000 |
| [csb_org_security_haiku_20260226_205845](runs/csb_org_security_haiku_20260226_205845.md) | `csb_org_security` | `baseline-local-direct` | 3 | 0.682 | 1.000 |
| [csb_org_security_haiku_20260228_012337](runs/csb_org_security_haiku_20260228_012337.md) | `csb_org_security` | `baseline-local-direct` | 7 | 0.420 | 0.714 |
| [csb_org_security_haiku_20260228_012337](runs/csb_org_security_haiku_20260228_012337.md) | `csb_org_security` | `mcp-remote-direct` | 5 | 0.690 | 1.000 |
| [csb_org_security_haiku_20260228_020502](runs/csb_org_security_haiku_20260228_020502.md) | `csb_org_security` | `baseline-local-direct` | 9 | 0.496 | 0.778 |
| [csb_org_security_haiku_20260228_025547](runs/csb_org_security_haiku_20260228_025547.md) | `csb_org_security` | `baseline-local-direct` | 4 | 0.662 | 1.000 |
| [csb_org_security_haiku_20260228_025547](runs/csb_org_security_haiku_20260228_025547.md) | `csb_org_security` | `mcp-remote-direct` | 4 | 0.811 | 1.000 |
| [csb_org_security_haiku_20260228_123206](runs/csb_org_security_haiku_20260228_123206.md) | `csb_org_security` | `baseline-local-direct` | 4 | 0.731 | 1.000 |
| [csb_org_security_haiku_20260301_173337](runs/csb_org_security_haiku_20260301_173337.md) | `csb_org_security` | `baseline-local-direct` | 3 | 0.000 | 0.000 |
| [csb_org_security_haiku_20260301_173337](runs/csb_org_security_haiku_20260301_173337.md) | `csb_org_security` | `mcp-remote-direct` | 4 | 0.000 | 0.000 |
| [csb_org_security_haiku_20260301_185444](runs/csb_org_security_haiku_20260301_185444.md) | `csb_org_security` | `baseline-local-direct` | 3 | 0.000 | 0.000 |
| [csb_org_security_haiku_20260301_185444](runs/csb_org_security_haiku_20260301_185444.md) | `csb_org_security` | `mcp-remote-direct` | 2 | 0.000 | 0.000 |
| [csb_org_security_haiku_20260301_201904](runs/csb_org_security_haiku_20260301_201904.md) | `csb_org_security` | `baseline-local-artifact` | 10 | 0.411 | 0.800 |
| [csb_org_security_haiku_20260301_201904](runs/csb_org_security_haiku_20260301_201904.md) | `csb_org_security` | `mcp-remote-artifact` | 20 | 0.494 | 1.000 |
| [csb_org_security_haiku_20260301_231457](runs/csb_org_security_haiku_20260301_231457.md) | `csb_org_security` | `baseline-local-direct` | 3 | 0.786 | 1.000 |
| [csb_org_security_haiku_20260301_231457](runs/csb_org_security_haiku_20260301_231457.md) | `csb_org_security` | `mcp-remote-direct` | 4 | 0.753 | 1.000 |
| [csb_org_security_haiku_20260301_235018](runs/csb_org_security_haiku_20260301_235018.md) | `csb_org_security` | `baseline-local-direct` | 1 | 0.673 | 1.000 |
| [csb_org_security_haiku_20260302_014939](runs/csb_org_security_haiku_20260302_014939.md) | `csb_org_security` | `baseline-local-direct` | 6 | 0.718 | 1.000 |
| [csb_org_security_haiku_20260302_014939](runs/csb_org_security_haiku_20260302_014939.md) | `csb_org_security` | `mcp-remote-direct` | 6 | 0.731 | 1.000 |
| [csb_org_security_haiku_20260302_022538](runs/csb_org_security_haiku_20260302_022538.md) | `csb_org_security` | `baseline-local-direct` | 4 | 0.767 | 1.000 |
| [csb_org_security_haiku_20260302_022538](runs/csb_org_security_haiku_20260302_022538.md) | `csb_org_security` | `mcp-remote-direct` | 4 | 0.737 | 1.000 |
| [csb_org_security_haiku_20260302_175821](runs/csb_org_security_haiku_20260302_175821.md) | `csb_org_security` | `baseline-local-direct` | 10 | 0.305 | 0.900 |
| [csb_org_security_haiku_20260302_175821](runs/csb_org_security_haiku_20260302_175821.md) | `csb_org_security` | `mcp-remote-direct` | 13 | 0.478 | 1.000 |
| [csb_org_security_haiku_20260302_175827](runs/csb_org_security_haiku_20260302_175827.md) | `csb_org_security` | `baseline-local-direct` | 11 | 0.417 | 0.909 |
| [csb_org_security_haiku_20260302_175827](runs/csb_org_security_haiku_20260302_175827.md) | `csb_org_security` | `mcp-remote-direct` | 14 | 0.448 | 1.000 |
| [csb_org_security_haiku_20260302_183602](runs/csb_org_security_haiku_20260302_183602.md) | `csb_org_security` | `baseline-local-direct` | 6 | 0.515 | 0.667 |
| [csb_org_security_haiku_20260302_183602](runs/csb_org_security_haiku_20260302_183602.md) | `csb_org_security` | `mcp-remote-direct` | 6 | 0.697 | 0.833 |
| [csb_org_security_haiku_20260302_183608](runs/csb_org_security_haiku_20260302_183608.md) | `csb_org_security` | `baseline-local-direct` | 6 | 0.588 | 0.833 |
| [csb_org_security_haiku_20260302_183608](runs/csb_org_security_haiku_20260302_183608.md) | `csb_org_security` | `mcp-remote-direct` | 6 | 0.771 | 1.000 |
| [csb_org_security_haiku_20260302_210829](runs/csb_org_security_haiku_20260302_210829.md) | `csb_org_security` | `baseline-local-direct` | 1 | 0.000 | 0.000 |
| [csb_org_security_haiku_20260302_210829](runs/csb_org_security_haiku_20260302_210829.md) | `csb_org_security` | `mcp-remote-direct` | 3 | 0.158 | 0.667 |
| [csb_org_security_haiku_20260302_210835](runs/csb_org_security_haiku_20260302_210835.md) | `csb_org_security` | `baseline-local-direct` | 1 | 0.000 | 0.000 |
| [csb_org_security_haiku_20260302_210835](runs/csb_org_security_haiku_20260302_210835.md) | `csb_org_security` | `mcp-remote-direct` | 2 | 0.386 | 1.000 |
| [csb_org_security_haiku_20260302_210842](runs/csb_org_security_haiku_20260302_210842.md) | `csb_org_security` | `mcp-remote-direct` | 2 | 0.400 | 1.000 |
| [csb_org_security_haiku_20260302_212645](runs/csb_org_security_haiku_20260302_212645.md) | `csb_org_security` | `baseline-local-direct` | 2 | 0.346 | 1.000 |
| [csb_org_security_haiku_20260302_212645](runs/csb_org_security_haiku_20260302_212645.md) | `csb_org_security` | `mcp-remote-direct` | 2 | 0.191 | 1.000 |
| [csb_org_security_haiku_20260303_141005](runs/csb_org_security_haiku_20260303_141005.md) | `csb_org_security` | `baseline-local-direct` | 1 | 0.673 | 1.000 |
| [csb_org_security_haiku_20260303_142451](runs/csb_org_security_haiku_20260303_142451.md) | `csb_org_security` | `baseline-local-direct` | 1 | 0.700 | 1.000 |
| [csb_org_security_haiku_20260303_175947](runs/csb_org_security_haiku_20260303_175947.md) | `csb_org_security` | `baseline-local-direct` | 1 | 0.000 | 0.000 |
| [csb_org_security_haiku_20260303_180027](runs/csb_org_security_haiku_20260303_180027.md) | `csb_org_security` | `baseline-local-direct` | 1 | 0.000 | 0.000 |
| [csb_org_security_haiku_20260303_180027](runs/csb_org_security_haiku_20260303_180027.md) | `csb_org_security` | `mcp-remote-direct` | 1 | 0.667 | 1.000 |
| [csb_org_security_haiku_20260307_030626](runs/csb_org_security_haiku_20260307_030626.md) | `csb_org_security` | `baseline-local-artifact` | 2 | 0.000 | 0.000 |
| [csb_org_security_haiku_20260307_030626](runs/csb_org_security_haiku_20260307_030626.md) | `csb_org_security` | `mcp-remote-artifact` | 2 | 0.000 | 0.000 |
| [csb_org_security_sonnet_20260308_034803](runs/csb_org_security_sonnet_20260308_034803.md) | `csb_org_security` | `baseline-local-direct` | 13 | 0.443 | 0.923 |
| [csb_org_security_sonnet_20260308_034803](runs/csb_org_security_sonnet_20260308_034803.md) | `csb_org_security` | `mcp-remote-direct` | 13 | 0.613 | 1.000 |
| [csb_sdlc_build_haiku_20260227_025524](runs/csb_sdlc_build_haiku_20260227_025524.md) | `csb_sdlc_build` | `baseline-local-direct` | 3 | 0.513 | 1.000 |
| [csb_sdlc_build_haiku_20260227_034711](runs/csb_sdlc_build_haiku_20260227_034711.md) | `csb_sdlc_build` | `baseline-local-direct` | 1 | 0.000 | 0.000 |
| [csb_sdlc_build_haiku_20260227_123839](runs/csb_sdlc_build_haiku_20260227_123839.md) | `csb_sdlc_build` | `baseline-local-direct` | 8 | 0.641 | 1.000 |
| [csb_sdlc_build_haiku_20260227_123839](runs/csb_sdlc_build_haiku_20260227_123839.md) | `csb_sdlc_build` | `mcp-remote-direct` | 7 | 0.571 | 1.000 |
| [csb_sdlc_build_haiku_20260228_025547](runs/csb_sdlc_build_haiku_20260228_025547.md) | `csb_sdlc_build` | `baseline-local-direct` | 13 | 0.554 | 0.692 |
| [csb_sdlc_build_haiku_20260228_025547](runs/csb_sdlc_build_haiku_20260228_025547.md) | `csb_sdlc_build` | `mcp-remote-direct` | 10 | 0.595 | 0.700 |
| [csb_sdlc_build_haiku_20260228_124521](runs/csb_sdlc_build_haiku_20260228_124521.md) | `csb_sdlc_build` | `mcp-remote-direct` | 1 | 0.880 | 1.000 |
| [csb_sdlc_build_haiku_20260228_160517](runs/csb_sdlc_build_haiku_20260228_160517.md) | `csb_sdlc_build` | `baseline-local-direct` | 1 | 1.000 | 1.000 |
| [csb_sdlc_build_haiku_20260228_161037](runs/csb_sdlc_build_haiku_20260228_161037.md) | `csb_sdlc_build` | `baseline-local-direct` | 1 | 1.000 | 1.000 |
| [csb_sdlc_build_haiku_20260228_161037](runs/csb_sdlc_build_haiku_20260228_161037.md) | `csb_sdlc_build` | `mcp-remote-direct` | 1 | 1.000 | 1.000 |
| [csb_sdlc_build_haiku_20260228_161452](runs/csb_sdlc_build_haiku_20260228_161452.md) | `csb_sdlc_build` | `baseline-local-direct` | 1 | 1.000 | 1.000 |
| [csb_sdlc_build_haiku_20260228_161452](runs/csb_sdlc_build_haiku_20260228_161452.md) | `csb_sdlc_build` | `mcp-remote-direct` | 1 | 0.000 | 0.000 |
| [csb_sdlc_debug_haiku_20260228_025547](runs/csb_sdlc_debug_haiku_20260228_025547.md) | `csb_sdlc_debug` | `baseline-local-direct` | 5 | 0.500 | 1.000 |
| [csb_sdlc_debug_haiku_20260228_025547](runs/csb_sdlc_debug_haiku_20260228_025547.md) | `csb_sdlc_debug` | `mcp-remote-direct` | 5 | 0.000 | 0.000 |
| [csb_sdlc_debug_haiku_20260228_051032](runs/csb_sdlc_debug_haiku_20260228_051032.md) | `csb_sdlc_debug` | `baseline-local-direct` | 3 | 0.900 | 1.000 |
| [csb_sdlc_debug_haiku_20260228_123206](runs/csb_sdlc_debug_haiku_20260228_123206.md) | `csb_sdlc_debug` | `baseline-local-direct` | 2 | 0.300 | 1.000 |
| [csb_sdlc_debug_haiku_20260301_230240](runs/csb_sdlc_debug_haiku_20260301_230240.md) | `csb_sdlc_debug` | `baseline-local-direct` | 2 | 0.500 | 1.000 |
| [csb_sdlc_debug_haiku_20260301_230240](runs/csb_sdlc_debug_haiku_20260301_230240.md) | `csb_sdlc_debug` | `mcp-remote-direct` | 2 | 0.500 | 1.000 |
| [csb_sdlc_debug_haiku_20260302_004746](runs/csb_sdlc_debug_haiku_20260302_004746.md) | `csb_sdlc_debug` | `baseline-local-direct` | 2 | 0.750 | 1.000 |
| [csb_sdlc_debug_haiku_20260302_004746](runs/csb_sdlc_debug_haiku_20260302_004746.md) | `csb_sdlc_debug` | `mcp-remote-direct` | 2 | 0.500 | 1.000 |
| [csb_sdlc_debug_haiku_20260302_013712](runs/csb_sdlc_debug_haiku_20260302_013712.md) | `csb_sdlc_debug` | `baseline-local-direct` | 1 | 0.500 | 1.000 |
| [csb_sdlc_debug_haiku_20260302_013713](runs/csb_sdlc_debug_haiku_20260302_013713.md) | `csb_sdlc_debug` | `mcp-remote-direct` | 1 | 0.500 | 1.000 |
| [csb_sdlc_debug_haiku_20260302_022552](runs/csb_sdlc_debug_haiku_20260302_022552.md) | `csb_sdlc_debug` | `baseline-local-direct` | 1 | 0.500 | 1.000 |
| [csb_sdlc_debug_haiku_20260302_022553](runs/csb_sdlc_debug_haiku_20260302_022553.md) | `csb_sdlc_debug` | `mcp-remote-direct` | 1 | 0.500 | 1.000 |
| [csb_sdlc_debug_haiku_20260302_221730](runs/csb_sdlc_debug_haiku_20260302_221730.md) | `csb_sdlc_debug` | `baseline-local-direct` | 9 | 0.496 | 0.667 |
| [csb_sdlc_debug_haiku_20260302_221730](runs/csb_sdlc_debug_haiku_20260302_221730.md) | `csb_sdlc_debug` | `mcp-remote-direct` | 6 | 0.825 | 1.000 |
| [csb_sdlc_debug_haiku_20260302_224010](runs/csb_sdlc_debug_haiku_20260302_224010.md) | `csb_sdlc_debug` | `baseline-local-direct` | 9 | 0.830 | 1.000 |
| [csb_sdlc_debug_haiku_20260302_224010](runs/csb_sdlc_debug_haiku_20260302_224010.md) | `csb_sdlc_debug` | `mcp-remote-direct` | 9 | 0.781 | 1.000 |
| [csb_sdlc_debug_haiku_20260302_224219](runs/csb_sdlc_debug_haiku_20260302_224219.md) | `csb_sdlc_debug` | `baseline-local-direct` | 5 | 0.836 | 1.000 |
| [csb_sdlc_debug_haiku_20260302_224219](runs/csb_sdlc_debug_haiku_20260302_224219.md) | `csb_sdlc_debug` | `mcp-remote-direct` | 7 | 0.759 | 1.000 |
| [csb_sdlc_debug_haiku_20260302_224437](runs/csb_sdlc_debug_haiku_20260302_224437.md) | `csb_sdlc_debug` | `baseline-local-direct` | 7 | 0.429 | 0.857 |
| [csb_sdlc_debug_haiku_20260302_224437](runs/csb_sdlc_debug_haiku_20260302_224437.md) | `csb_sdlc_debug` | `mcp-remote-direct` | 7 | 0.429 | 0.857 |
| [csb_sdlc_debug_haiku_20260302_230235](runs/csb_sdlc_debug_haiku_20260302_230235.md) | `csb_sdlc_debug` | `baseline-local-direct` | 1 | 0.500 | 1.000 |
| [csb_sdlc_debug_haiku_20260302_230948](runs/csb_sdlc_debug_haiku_20260302_230948.md) | `csb_sdlc_debug` | `mcp-remote-direct` | 1 | 0.500 | 1.000 |
| [csb_sdlc_debug_haiku_20260302_231522](runs/csb_sdlc_debug_haiku_20260302_231522.md) | `csb_sdlc_debug` | `baseline-local-direct` | 7 | 0.500 | 1.000 |
| [csb_sdlc_debug_haiku_20260302_231522](runs/csb_sdlc_debug_haiku_20260302_231522.md) | `csb_sdlc_debug` | `mcp-remote-direct` | 7 | 0.429 | 0.857 |
| [csb_sdlc_debug_haiku_20260302_232613](runs/csb_sdlc_debug_haiku_20260302_232613.md) | `csb_sdlc_debug` | `mcp-remote-direct` | 2 | 0.800 | 1.000 |
| [csb_sdlc_debug_haiku_20260302_232614](runs/csb_sdlc_debug_haiku_20260302_232614.md) | `csb_sdlc_debug` | `baseline-local-direct` | 2 | 0.250 | 0.500 |
| [csb_sdlc_debug_haiku_20260302_232614](runs/csb_sdlc_debug_haiku_20260302_232614.md) | `csb_sdlc_debug` | `mcp-remote-direct` | 2 | 0.500 | 1.000 |
| [csb_sdlc_debug_haiku_20260302_232923](runs/csb_sdlc_debug_haiku_20260302_232923.md) | `csb_sdlc_debug` | `baseline-local-direct` | 1 | 0.500 | 1.000 |
| [csb_sdlc_debug_haiku_20260302_232923](runs/csb_sdlc_debug_haiku_20260302_232923.md) | `csb_sdlc_debug` | `mcp-remote-direct` | 1 | 0.500 | 1.000 |
| [csb_sdlc_debug_haiku_20260303_180241](runs/csb_sdlc_debug_haiku_20260303_180241.md) | `csb_sdlc_debug` | `baseline-local-direct` | 1 | 0.000 | 0.000 |
| [csb_sdlc_debug_haiku_20260303_180441](runs/csb_sdlc_debug_haiku_20260303_180441.md) | `csb_sdlc_debug` | `baseline-local-direct` | 1 | 0.000 | 0.000 |
| [csb_sdlc_debug_haiku_20260303_180441](runs/csb_sdlc_debug_haiku_20260303_180441.md) | `csb_sdlc_debug` | `mcp-remote-direct` | 1 | 0.700 | 1.000 |
| [csb_sdlc_debug_haiku_20260303_180859](runs/csb_sdlc_debug_haiku_20260303_180859.md) | `csb_sdlc_debug` | `mcp-remote-direct` | 1 | 0.000 | 0.000 |
| [csb_sdlc_debug_haiku_20260307_001927](runs/csb_sdlc_debug_haiku_20260307_001927.md) | `csb_sdlc_debug` | `baseline-local-direct` | 1 | 1.000 | 1.000 |
| [csb_sdlc_debug_haiku_20260307_001927](runs/csb_sdlc_debug_haiku_20260307_001927.md) | `csb_sdlc_debug` | `mcp-remote-direct` | 1 | 1.000 | 1.000 |
| [csb_sdlc_debug_sonnet_20260308_034803](runs/csb_sdlc_debug_sonnet_20260308_034803.md) | `csb_sdlc_debug` | `baseline-local-direct` | 5 | 0.800 | 1.000 |
| [csb_sdlc_debug_sonnet_20260308_034803](runs/csb_sdlc_debug_sonnet_20260308_034803.md) | `csb_sdlc_debug` | `mcp-remote-direct` | 5 | 0.740 | 1.000 |
| [csb_sdlc_design_haiku_022326](runs/csb_sdlc_design_haiku_022326.md) | `csb_sdlc_design` | `baseline-local-direct` | 9 | 0.823 | 1.000 |
| [csb_sdlc_design_haiku_022326](runs/csb_sdlc_design_haiku_022326.md) | `csb_sdlc_design` | `mcp-remote-direct` | 20 | 0.718 | 1.000 |
| [csb_sdlc_design_haiku_20260225_234223](runs/csb_sdlc_design_haiku_20260225_234223.md) | `csb_sdlc_design` | `baseline-local-direct` | 5 | 0.666 | 0.800 |
| [csb_sdlc_design_haiku_20260226_015500_backfill](runs/csb_sdlc_design_haiku_20260226_015500_backfill.md) | `csb_sdlc_design` | `baseline-local-direct` | 5 | 0.666 | 0.800 |
| [csb_sdlc_design_haiku_20260228_025547](runs/csb_sdlc_design_haiku_20260228_025547.md) | `csb_sdlc_design` | `baseline-local-direct` | 9 | 0.569 | 1.000 |
| [csb_sdlc_design_haiku_20260228_025547](runs/csb_sdlc_design_haiku_20260228_025547.md) | `csb_sdlc_design` | `mcp-remote-direct` | 13 | 0.751 | 1.000 |
| [csb_sdlc_design_haiku_20260302_221730](runs/csb_sdlc_design_haiku_20260302_221730.md) | `csb_sdlc_design` | `baseline-local-direct` | 10 | 0.811 | 1.000 |
| [csb_sdlc_design_haiku_20260302_221730](runs/csb_sdlc_design_haiku_20260302_221730.md) | `csb_sdlc_design` | `mcp-remote-direct` | 9 | 0.742 | 1.000 |
| [csb_sdlc_design_haiku_20260302_224010](runs/csb_sdlc_design_haiku_20260302_224010.md) | `csb_sdlc_design` | `mcp-remote-direct` | 5 | 0.669 | 1.000 |
| [csb_sdlc_design_haiku_20260303_141005](runs/csb_sdlc_design_haiku_20260303_141005.md) | `csb_sdlc_design` | `baseline-local-direct` | 4 | 0.830 | 1.000 |
| [csb_sdlc_design_haiku_20260303_142451](runs/csb_sdlc_design_haiku_20260303_142451.md) | `csb_sdlc_design` | `baseline-local-direct` | 4 | 0.608 | 0.750 |
| [csb_sdlc_design_haiku_20260303_143323](runs/csb_sdlc_design_haiku_20260303_143323.md) | `csb_sdlc_design` | `baseline-local-direct` | 4 | 0.805 | 1.000 |
| [csb_sdlc_design_haiku_20260307_001927](runs/csb_sdlc_design_haiku_20260307_001927.md) | `csb_sdlc_design` | `baseline-local-direct` | 1 | 1.000 | 1.000 |
| [csb_sdlc_design_haiku_20260307_001927](runs/csb_sdlc_design_haiku_20260307_001927.md) | `csb_sdlc_design` | `mcp-remote-direct` | 1 | 1.000 | 1.000 |
| [csb_sdlc_design_sonnet_20260308_034803](runs/csb_sdlc_design_sonnet_20260308_034803.md) | `csb_sdlc_design` | `baseline-local-direct` | 11 | 0.896 | 1.000 |
| [csb_sdlc_design_sonnet_20260308_034803](runs/csb_sdlc_design_sonnet_20260308_034803.md) | `csb_sdlc_design` | `mcp-remote-direct` | 11 | 0.788 | 0.909 |
| [csb_sdlc_document_haiku_022326](runs/csb_sdlc_document_haiku_022326.md) | `csb_sdlc_document` | `baseline-local-direct` | 8 | 0.839 | 1.000 |
| [csb_sdlc_document_haiku_022326](runs/csb_sdlc_document_haiku_022326.md) | `csb_sdlc_document` | `mcp-remote-direct` | 15 | 0.953 | 1.000 |
| [csb_sdlc_document_haiku_20260224_174311](runs/csb_sdlc_document_haiku_20260224_174311.md) | `csb_sdlc_document` | `baseline-local-direct` | 5 | 0.658 | 1.000 |
| [csb_sdlc_document_haiku_20260224_174311](runs/csb_sdlc_document_haiku_20260224_174311.md) | `csb_sdlc_document` | `mcp-remote-direct` | 5 | 0.720 | 1.000 |
| [csb_sdlc_document_haiku_20260228_025547](runs/csb_sdlc_document_haiku_20260228_025547.md) | `csb_sdlc_document` | `baseline-local-direct` | 13 | 0.833 | 1.000 |
| [csb_sdlc_document_haiku_20260228_025547](runs/csb_sdlc_document_haiku_20260228_025547.md) | `csb_sdlc_document` | `mcp-remote-direct` | 18 | 0.887 | 1.000 |
| [csb_sdlc_document_haiku_20260228_124521](runs/csb_sdlc_document_haiku_20260228_124521.md) | `csb_sdlc_document` | `mcp-remote-direct` | 1 | 1.000 | 1.000 |
| [csb_sdlc_document_haiku_20260302_221730](runs/csb_sdlc_document_haiku_20260302_221730.md) | `csb_sdlc_document` | `baseline-local-direct` | 8 | 0.776 | 1.000 |
| [csb_sdlc_document_haiku_20260302_221730](runs/csb_sdlc_document_haiku_20260302_221730.md) | `csb_sdlc_document` | `mcp-remote-direct` | 9 | 0.844 | 1.000 |
| [csb_sdlc_document_haiku_20260303_141005](runs/csb_sdlc_document_haiku_20260303_141005.md) | `csb_sdlc_document` | `baseline-local-direct` | 5 | 0.874 | 1.000 |
| [csb_sdlc_document_haiku_20260303_142451](runs/csb_sdlc_document_haiku_20260303_142451.md) | `csb_sdlc_document` | `baseline-local-direct` | 5 | 0.752 | 1.000 |
| [csb_sdlc_document_haiku_20260303_143323](runs/csb_sdlc_document_haiku_20260303_143323.md) | `csb_sdlc_document` | `baseline-local-direct` | 5 | 0.846 | 1.000 |
| [csb_sdlc_document_haiku_20260307_001927](runs/csb_sdlc_document_haiku_20260307_001927.md) | `csb_sdlc_document` | `baseline-local-direct` | 2 | 1.000 | 1.000 |
| [csb_sdlc_document_haiku_20260307_001927](runs/csb_sdlc_document_haiku_20260307_001927.md) | `csb_sdlc_document` | `mcp-remote-direct` | 2 | 0.500 | 0.500 |
| [csb_sdlc_document_sonnet_20260308_034803](runs/csb_sdlc_document_sonnet_20260308_034803.md) | `csb_sdlc_document` | `baseline-local-direct` | 11 | 0.833 | 1.000 |
| [csb_sdlc_document_sonnet_20260308_034803](runs/csb_sdlc_document_sonnet_20260308_034803.md) | `csb_sdlc_document` | `mcp-remote-direct` | 11 | 0.704 | 1.000 |
| [csb_sdlc_feature_haiku_20260301_212230](runs/csb_sdlc_feature_haiku_20260301_212230.md) | `csb_sdlc_feature` | `baseline-local-direct` | 3 | 0.500 | 0.667 |
| [csb_sdlc_feature_haiku_20260301_212230](runs/csb_sdlc_feature_haiku_20260301_212230.md) | `csb_sdlc_feature` | `mcp-remote-direct` | 3 | 0.500 | 0.667 |
| [csb_sdlc_feature_haiku_20260301_230003](runs/csb_sdlc_feature_haiku_20260301_230003.md) | `csb_sdlc_feature` | `baseline-local-direct` | 4 | 0.358 | 0.750 |
| [csb_sdlc_feature_haiku_20260301_230003](runs/csb_sdlc_feature_haiku_20260301_230003.md) | `csb_sdlc_feature` | `mcp-remote-direct` | 4 | 0.407 | 0.750 |
| [csb_sdlc_feature_haiku_20260301_230048](runs/csb_sdlc_feature_haiku_20260301_230048.md) | `csb_sdlc_feature` | `baseline-local-direct` | 3 | 0.478 | 1.000 |
| [csb_sdlc_feature_haiku_20260301_230048](runs/csb_sdlc_feature_haiku_20260301_230048.md) | `csb_sdlc_feature` | `mcp-remote-direct` | 4 | 0.375 | 0.500 |
| [csb_sdlc_feature_haiku_20260302_004743](runs/csb_sdlc_feature_haiku_20260302_004743.md) | `csb_sdlc_feature` | `baseline-local-direct` | 3 | 0.444 | 0.667 |
| [csb_sdlc_feature_haiku_20260302_004743](runs/csb_sdlc_feature_haiku_20260302_004743.md) | `csb_sdlc_feature` | `mcp-remote-direct` | 3 | 0.500 | 0.667 |
| [csb_sdlc_feature_haiku_20260302_005828](runs/csb_sdlc_feature_haiku_20260302_005828.md) | `csb_sdlc_feature` | `baseline-local-direct` | 3 | 0.222 | 0.667 |
| [csb_sdlc_feature_haiku_20260302_005828](runs/csb_sdlc_feature_haiku_20260302_005828.md) | `csb_sdlc_feature` | `mcp-remote-direct` | 3 | 0.500 | 0.667 |
| [csb_sdlc_feature_haiku_20260302_005948](runs/csb_sdlc_feature_haiku_20260302_005948.md) | `csb_sdlc_feature` | `mcp-remote-direct` | 1 | 0.140 | 1.000 |
| [csb_sdlc_feature_haiku_20260302_022544](runs/csb_sdlc_feature_haiku_20260302_022544.md) | `csb_sdlc_feature` | `baseline-local-direct` | 1 | 0.000 | 0.000 |
| [csb_sdlc_feature_haiku_20260302_221730](runs/csb_sdlc_feature_haiku_20260302_221730.md) | `csb_sdlc_feature` | `baseline-local-direct` | 17 | 0.481 | 0.765 |
| [csb_sdlc_feature_haiku_20260302_221730](runs/csb_sdlc_feature_haiku_20260302_221730.md) | `csb_sdlc_feature` | `mcp-remote-direct` | 11 | 0.714 | 0.818 |
| [csb_sdlc_feature_haiku_20260302_221754](runs/csb_sdlc_feature_haiku_20260302_221754.md) | `csb_sdlc_feature` | `baseline-local-direct` | 1 | 0.110 | 1.000 |
| [csb_sdlc_feature_haiku_20260302_221754](runs/csb_sdlc_feature_haiku_20260302_221754.md) | `csb_sdlc_feature` | `mcp-remote-direct` | 1 | 0.500 | 1.000 |
| [csb_sdlc_feature_haiku_20260302_224010](runs/csb_sdlc_feature_haiku_20260302_224010.md) | `csb_sdlc_feature` | `baseline-local-direct` | 17 | 0.723 | 0.941 |
| [csb_sdlc_feature_haiku_20260302_224010](runs/csb_sdlc_feature_haiku_20260302_224010.md) | `csb_sdlc_feature` | `mcp-remote-direct` | 18 | 0.636 | 0.889 |
| [csb_sdlc_feature_haiku_20260302_224219](runs/csb_sdlc_feature_haiku_20260302_224219.md) | `csb_sdlc_feature` | `baseline-local-direct` | 1 | 0.833 | 1.000 |
| [csb_sdlc_feature_haiku_20260302_224219](runs/csb_sdlc_feature_haiku_20260302_224219.md) | `csb_sdlc_feature` | `mcp-remote-direct` | 3 | 0.620 | 1.000 |
| [csb_sdlc_feature_haiku_20260303_034215](runs/csb_sdlc_feature_haiku_20260303_034215.md) | `csb_sdlc_feature` | `baseline-local-direct` | 3 | 0.833 | 1.000 |
| [csb_sdlc_feature_haiku_20260303_034215](runs/csb_sdlc_feature_haiku_20260303_034215.md) | `csb_sdlc_feature` | `mcp-remote-direct` | 3 | 0.778 | 1.000 |
| [csb_sdlc_feature_haiku_20260303_141005](runs/csb_sdlc_feature_haiku_20260303_141005.md) | `csb_sdlc_feature` | `baseline-local-direct` | 10 | 0.833 | 0.900 |
| [csb_sdlc_feature_haiku_20260303_142451](runs/csb_sdlc_feature_haiku_20260303_142451.md) | `csb_sdlc_feature` | `baseline-local-direct` | 7 | 0.833 | 0.857 |
| [csb_sdlc_feature_haiku_20260303_152731](runs/csb_sdlc_feature_haiku_20260303_152731.md) | `csb_sdlc_feature` | `mcp-remote-direct` | 1 | 0.000 | 0.000 |
| [csb_sdlc_feature_haiku_20260303_180956](runs/csb_sdlc_feature_haiku_20260303_180956.md) | `csb_sdlc_feature` | `baseline-local-direct` | 6 | 0.467 | 0.667 |
| [csb_sdlc_feature_haiku_20260303_181304](runs/csb_sdlc_feature_haiku_20260303_181304.md) | `csb_sdlc_feature` | `baseline-local-direct` | 1 | 0.000 | 0.000 |
| [csb_sdlc_feature_haiku_20260303_183926](runs/csb_sdlc_feature_haiku_20260303_183926.md) | `csb_sdlc_feature` | `mcp-remote-direct` | 1 | 0.000 | 0.000 |
| [csb_sdlc_feature_haiku_20260303_184719](runs/csb_sdlc_feature_haiku_20260303_184719.md) | `csb_sdlc_feature` | `baseline-local-direct` | 8 | 0.540 | 0.625 |
| [csb_sdlc_feature_haiku_20260303_184719](runs/csb_sdlc_feature_haiku_20260303_184719.md) | `csb_sdlc_feature` | `mcp-remote-direct` | 7 | 0.571 | 0.571 |
| [csb_sdlc_feature_haiku_20260303_190739](runs/csb_sdlc_feature_haiku_20260303_190739.md) | `csb_sdlc_feature` | `mcp-remote-direct` | 4 | 0.812 | 1.000 |
| [csb_sdlc_feature_sonnet_20260308_034803](runs/csb_sdlc_feature_sonnet_20260308_034803.md) | `csb_sdlc_feature` | `baseline-local-direct` | 22 | 0.660 | 0.955 |
| [csb_sdlc_feature_sonnet_20260308_034803](runs/csb_sdlc_feature_sonnet_20260308_034803.md) | `csb_sdlc_feature` | `mcp-remote-direct` | 20 | 0.629 | 0.900 |
| [csb_sdlc_feature_sonnet_20260309_013354](runs/csb_sdlc_feature_sonnet_20260309_013354.md) | `csb_sdlc_feature` | `mcp-remote-direct` | 1 | 0.700 | 1.000 |
| [csb_sdlc_feature_sonnet_20260309_142738](runs/csb_sdlc_feature_sonnet_20260309_142738.md) | `csb_sdlc_feature` | `mcp-remote-direct` | 1 | 1.000 | 1.000 |
| [csb_sdlc_fix_haiku_20260228_185835](runs/csb_sdlc_fix_haiku_20260228_185835.md) | `csb_sdlc_fix` | `baseline-local-direct` | 25 | 0.471 | 0.640 |
| [csb_sdlc_fix_haiku_20260228_185835](runs/csb_sdlc_fix_haiku_20260228_185835.md) | `csb_sdlc_fix` | `mcp-remote-direct` | 25 | 0.592 | 0.720 |
| [csb_sdlc_fix_haiku_20260228_203750](runs/csb_sdlc_fix_haiku_20260228_203750.md) | `csb_sdlc_fix` | `baseline-local-direct` | 3 | 0.457 | 1.000 |
| [csb_sdlc_fix_haiku_20260228_205741](runs/csb_sdlc_fix_haiku_20260228_205741.md) | `csb_sdlc_fix` | `baseline-local-direct` | 25 | 0.440 | 0.600 |
| [csb_sdlc_fix_haiku_20260228_205741](runs/csb_sdlc_fix_haiku_20260228_205741.md) | `csb_sdlc_fix` | `mcp-remote-direct` | 25 | 0.536 | 0.680 |
| [csb_sdlc_fix_haiku_20260228_230722](runs/csb_sdlc_fix_haiku_20260228_230722.md) | `csb_sdlc_fix` | `baseline-local-direct` | 20 | 0.510 | 0.650 |
| [csb_sdlc_fix_haiku_20260228_230722](runs/csb_sdlc_fix_haiku_20260228_230722.md) | `csb_sdlc_fix` | `mcp-remote-direct` | 20 | 0.593 | 0.750 |
| [csb_sdlc_fix_haiku_20260301_173337](runs/csb_sdlc_fix_haiku_20260301_173337.md) | `csb_sdlc_fix` | `baseline-local-direct` | 9 | 0.597 | 0.889 |
| [csb_sdlc_fix_haiku_20260301_173337](runs/csb_sdlc_fix_haiku_20260301_173337.md) | `csb_sdlc_fix` | `mcp-remote-direct` | 5 | 0.646 | 1.000 |
| [csb_sdlc_fix_haiku_20260301_173342](runs/csb_sdlc_fix_haiku_20260301_173342.md) | `csb_sdlc_fix` | `mcp-remote-direct` | 8 | 0.621 | 0.625 |
| [csb_sdlc_fix_haiku_20260301_212230](runs/csb_sdlc_fix_haiku_20260301_212230.md) | `csb_sdlc_fix` | `baseline-local-direct` | 1 | 0.000 | 0.000 |
| [csb_sdlc_fix_haiku_20260301_212230](runs/csb_sdlc_fix_haiku_20260301_212230.md) | `csb_sdlc_fix` | `mcp-remote-direct` | 1 | 0.000 | 0.000 |
| [csb_sdlc_fix_haiku_20260301_214459](runs/csb_sdlc_fix_haiku_20260301_214459.md) | `csb_sdlc_fix` | `baseline-local-direct` | 1 | 0.500 | 1.000 |
| [csb_sdlc_fix_haiku_20260301_214459](runs/csb_sdlc_fix_haiku_20260301_214459.md) | `csb_sdlc_fix` | `mcp-remote-direct` | 1 | 0.500 | 1.000 |
| [csb_sdlc_fix_haiku_20260301_230003](runs/csb_sdlc_fix_haiku_20260301_230003.md) | `csb_sdlc_fix` | `baseline-local-direct` | 1 | 0.667 | 1.000 |
| [csb_sdlc_fix_haiku_20260301_230048](runs/csb_sdlc_fix_haiku_20260301_230048.md) | `csb_sdlc_fix` | `baseline-local-direct` | 3 | 0.413 | 0.667 |
| [csb_sdlc_fix_haiku_20260301_230048](runs/csb_sdlc_fix_haiku_20260301_230048.md) | `csb_sdlc_fix` | `mcp-remote-direct` | 1 | 0.500 | 1.000 |
| [csb_sdlc_fix_haiku_20260301_230240](runs/csb_sdlc_fix_haiku_20260301_230240.md) | `csb_sdlc_fix` | `baseline-local-direct` | 3 | 0.537 | 0.667 |
| [csb_sdlc_fix_haiku_20260301_230240](runs/csb_sdlc_fix_haiku_20260301_230240.md) | `csb_sdlc_fix` | `mcp-remote-direct` | 3 | 0.667 | 0.667 |
| [csb_sdlc_fix_haiku_20260302_005828](runs/csb_sdlc_fix_haiku_20260302_005828.md) | `csb_sdlc_fix` | `baseline-local-direct` | 1 | 0.500 | 1.000 |
| [csb_sdlc_fix_haiku_20260302_005828](runs/csb_sdlc_fix_haiku_20260302_005828.md) | `csb_sdlc_fix` | `mcp-remote-direct` | 1 | 0.500 | 1.000 |
| [csb_sdlc_fix_haiku_20260302_005945](runs/csb_sdlc_fix_haiku_20260302_005945.md) | `csb_sdlc_fix` | `baseline-local-direct` | 2 | 0.191 | 0.500 |
| [csb_sdlc_fix_haiku_20260302_013712](runs/csb_sdlc_fix_haiku_20260302_013712.md) | `csb_sdlc_fix` | `baseline-local-direct` | 2 | 0.333 | 0.500 |
| [csb_sdlc_fix_haiku_20260302_013713](runs/csb_sdlc_fix_haiku_20260302_013713.md) | `csb_sdlc_fix` | `mcp-remote-direct` | 1 | 1.000 | 1.000 |
| [csb_sdlc_fix_haiku_20260302_015531](runs/csb_sdlc_fix_haiku_20260302_015531.md) | `csb_sdlc_fix` | `mcp-remote-direct` | 1 | 1.000 | 1.000 |
| [csb_sdlc_fix_haiku_20260302_020340](runs/csb_sdlc_fix_haiku_20260302_020340.md) | `csb_sdlc_fix` | `mcp-remote-direct` | 2 | 0.280 | 0.500 |
| [csb_sdlc_fix_haiku_20260302_021447](runs/csb_sdlc_fix_haiku_20260302_021447.md) | `csb_sdlc_fix` | `baseline-local-direct` | 2 | 0.429 | 0.500 |
| [csb_sdlc_fix_haiku_20260302_022542](runs/csb_sdlc_fix_haiku_20260302_022542.md) | `csb_sdlc_fix` | `baseline-local-direct` | 1 | 0.667 | 1.000 |
| [csb_sdlc_fix_haiku_20260302_022542](runs/csb_sdlc_fix_haiku_20260302_022542.md) | `csb_sdlc_fix` | `mcp-remote-direct` | 1 | 0.500 | 1.000 |
| [csb_sdlc_fix_haiku_20260302_022550](runs/csb_sdlc_fix_haiku_20260302_022550.md) | `csb_sdlc_fix` | `baseline-local-direct` | 1 | 0.667 | 1.000 |
| [csb_sdlc_fix_haiku_20260302_022550](runs/csb_sdlc_fix_haiku_20260302_022550.md) | `csb_sdlc_fix` | `mcp-remote-direct` | 1 | 1.000 | 1.000 |
| [csb_sdlc_fix_haiku_20260302_022552](runs/csb_sdlc_fix_haiku_20260302_022552.md) | `csb_sdlc_fix` | `baseline-local-direct` | 1 | 0.000 | 0.000 |
| [csb_sdlc_fix_haiku_20260302_230235](runs/csb_sdlc_fix_haiku_20260302_230235.md) | `csb_sdlc_fix` | `baseline-local-direct` | 1 | 0.000 | 0.000 |
| [csb_sdlc_fix_haiku_20260303_162648](runs/csb_sdlc_fix_haiku_20260303_162648.md) | `csb_sdlc_fix` | `baseline-local-direct` | 1 | 0.000 | 0.000 |
| [csb_sdlc_fix_haiku_20260303_162648](runs/csb_sdlc_fix_haiku_20260303_162648.md) | `csb_sdlc_fix` | `mcp-remote-direct` | 1 | 0.000 | 0.000 |
| [csb_sdlc_fix_haiku_20260303_163626](runs/csb_sdlc_fix_haiku_20260303_163626.md) | `csb_sdlc_fix` | `baseline-local-direct` | 4 | 0.000 | 0.000 |
| [csb_sdlc_fix_haiku_20260303_163626](runs/csb_sdlc_fix_haiku_20260303_163626.md) | `csb_sdlc_fix` | `mcp-remote-direct` | 5 | 0.000 | 0.000 |
| [csb_sdlc_fix_haiku_20260303_175203](runs/csb_sdlc_fix_haiku_20260303_175203.md) | `csb_sdlc_fix` | `mcp-remote-direct` | 1 | 0.000 | 0.000 |
| [csb_sdlc_fix_haiku_20260303_180659](runs/csb_sdlc_fix_haiku_20260303_180659.md) | `csb_sdlc_fix` | `baseline-local-direct` | 1 | 0.000 | 0.000 |
| [csb_sdlc_fix_haiku_20260303_181313](runs/csb_sdlc_fix_haiku_20260303_181313.md) | `csb_sdlc_fix` | `baseline-local-direct` | 1 | 0.000 | 0.000 |
| [csb_sdlc_fix_haiku_20260303_181313](runs/csb_sdlc_fix_haiku_20260303_181313.md) | `csb_sdlc_fix` | `mcp-remote-direct` | 1 | 0.667 | 1.000 |
| [csb_sdlc_fix_haiku_20260303_183926](runs/csb_sdlc_fix_haiku_20260303_183926.md) | `csb_sdlc_fix` | `mcp-remote-direct` | 1 | 0.000 | 0.000 |
| [csb_sdlc_fix_haiku_20260303_190206](runs/csb_sdlc_fix_haiku_20260303_190206.md) | `csb_sdlc_fix` | `baseline-local-direct` | 1 | 0.000 | 0.000 |
| [csb_sdlc_fix_haiku_20260309_223654](runs/csb_sdlc_fix_haiku_20260309_223654.md) | `csb_sdlc_fix` | `baseline-local-direct` | 1 | 0.000 | 0.000 |
| [csb_sdlc_fix_haiku_20260309_223654](runs/csb_sdlc_fix_haiku_20260309_223654.md) | `csb_sdlc_fix` | `mcp-remote-direct` | 2 | 0.500 | 0.500 |
| [csb_sdlc_fix_sonnet_20260308_034803](runs/csb_sdlc_fix_sonnet_20260308_034803.md) | `csb_sdlc_fix` | `baseline-local-direct` | 13 | 0.547 | 0.692 |
| [csb_sdlc_fix_sonnet_20260308_034803](runs/csb_sdlc_fix_sonnet_20260308_034803.md) | `csb_sdlc_fix` | `mcp-remote-direct` | 13 | 0.491 | 0.615 |
| [csb_sdlc_fix_sonnet_20260309_013353](runs/csb_sdlc_fix_sonnet_20260309_013353.md) | `csb_sdlc_fix` | `baseline-local-direct` | 1 | 0.000 | 0.000 |
| [csb_sdlc_fix_sonnet_20260309_013354](runs/csb_sdlc_fix_sonnet_20260309_013354.md) | `csb_sdlc_fix` | `mcp-remote-direct` | 2 | 0.000 | 0.000 |
| [csb_sdlc_fix_sonnet_20260309_142738](runs/csb_sdlc_fix_sonnet_20260309_142738.md) | `csb_sdlc_fix` | `mcp-remote-direct` | 2 | 0.250 | 0.500 |
| [csb_sdlc_refactor_haiku_20260301_133910](runs/csb_sdlc_refactor_haiku_20260301_133910.md) | `csb_sdlc_refactor` | `baseline-local-direct` | 1 | 0.800 | 1.000 |
| [csb_sdlc_refactor_haiku_20260302_221730](runs/csb_sdlc_refactor_haiku_20260302_221730.md) | `csb_sdlc_refactor` | `baseline-local-direct` | 14 | 0.451 | 0.714 |
| [csb_sdlc_refactor_haiku_20260302_221730](runs/csb_sdlc_refactor_haiku_20260302_221730.md) | `csb_sdlc_refactor` | `mcp-remote-direct` | 10 | 0.754 | 0.900 |
| [csb_sdlc_refactor_haiku_20260302_224010](runs/csb_sdlc_refactor_haiku_20260302_224010.md) | `csb_sdlc_refactor` | `baseline-local-direct` | 11 | 0.682 | 1.000 |
| [csb_sdlc_refactor_haiku_20260302_224010](runs/csb_sdlc_refactor_haiku_20260302_224010.md) | `csb_sdlc_refactor` | `mcp-remote-direct` | 11 | 0.602 | 1.000 |
| [csb_sdlc_refactor_haiku_20260302_224219](runs/csb_sdlc_refactor_haiku_20260302_224219.md) | `csb_sdlc_refactor` | `baseline-local-direct` | 1 | 0.500 | 1.000 |
| [csb_sdlc_refactor_haiku_20260302_224219](runs/csb_sdlc_refactor_haiku_20260302_224219.md) | `csb_sdlc_refactor` | `mcp-remote-direct` | 3 | 0.222 | 0.667 |
| [csb_sdlc_refactor_haiku_20260303_034215](runs/csb_sdlc_refactor_haiku_20260303_034215.md) | `csb_sdlc_refactor` | `baseline-local-direct` | 6 | 0.889 | 1.000 |
| [csb_sdlc_refactor_haiku_20260303_034215](runs/csb_sdlc_refactor_haiku_20260303_034215.md) | `csb_sdlc_refactor` | `mcp-remote-direct` | 6 | 0.694 | 0.833 |
| [csb_sdlc_refactor_haiku_20260303_140132](runs/csb_sdlc_refactor_haiku_20260303_140132.md) | `csb_sdlc_refactor` | `baseline-local-direct` | 1 | 0.667 | 1.000 |
| [csb_sdlc_refactor_haiku_20260303_140132](runs/csb_sdlc_refactor_haiku_20260303_140132.md) | `csb_sdlc_refactor` | `mcp-remote-direct` | 1 | 0.667 | 1.000 |
| [csb_sdlc_refactor_haiku_20260303_141005](runs/csb_sdlc_refactor_haiku_20260303_141005.md) | `csb_sdlc_refactor` | `baseline-local-direct` | 8 | 0.854 | 1.000 |
| [csb_sdlc_refactor_haiku_20260303_142451](runs/csb_sdlc_refactor_haiku_20260303_142451.md) | `csb_sdlc_refactor` | `baseline-local-direct` | 5 | 0.800 | 1.000 |
| [csb_sdlc_refactor_haiku_20260303_190647](runs/csb_sdlc_refactor_haiku_20260303_190647.md) | `csb_sdlc_refactor` | `baseline-local-direct` | 5 | 0.677 | 0.800 |
| [csb_sdlc_refactor_haiku_20260303_190739](runs/csb_sdlc_refactor_haiku_20260303_190739.md) | `csb_sdlc_refactor` | `mcp-remote-direct` | 1 | 0.550 | 1.000 |
| [csb_sdlc_refactor_haiku_20260307_001927](runs/csb_sdlc_refactor_haiku_20260307_001927.md) | `csb_sdlc_refactor` | `baseline-local-direct` | 2 | 0.583 | 1.000 |
| [csb_sdlc_refactor_haiku_20260307_001927](runs/csb_sdlc_refactor_haiku_20260307_001927.md) | `csb_sdlc_refactor` | `mcp-remote-direct` | 2 | 0.500 | 0.500 |
| [csb_sdlc_refactor_sonnet_20260308_034803](runs/csb_sdlc_refactor_sonnet_20260308_034803.md) | `csb_sdlc_refactor` | `baseline-local-direct` | 18 | 0.769 | 0.944 |
| [csb_sdlc_refactor_sonnet_20260308_034803](runs/csb_sdlc_refactor_sonnet_20260308_034803.md) | `csb_sdlc_refactor` | `mcp-remote-direct` | 15 | 0.671 | 0.867 |
| [csb_sdlc_refactor_sonnet_20260309_013354](runs/csb_sdlc_refactor_sonnet_20260309_013354.md) | `csb_sdlc_refactor` | `mcp-remote-direct` | 2 | 0.850 | 1.000 |
| [csb_sdlc_secure_haiku_022326](runs/csb_sdlc_secure_haiku_022326.md) | `csb_sdlc_secure` | `baseline-local-direct` | 10 | 0.616 | 0.900 |
| [csb_sdlc_secure_haiku_022326](runs/csb_sdlc_secure_haiku_022326.md) | `csb_sdlc_secure` | `mcp-remote-direct` | 18 | 0.705 | 1.000 |
| [csb_sdlc_secure_haiku_20260224_213146](runs/csb_sdlc_secure_haiku_20260224_213146.md) | `csb_sdlc_secure` | `baseline-local-direct` | 2 | 0.500 | 1.000 |
| [csb_sdlc_secure_haiku_20260224_213146](runs/csb_sdlc_secure_haiku_20260224_213146.md) | `csb_sdlc_secure` | `mcp-remote-direct` | 2 | 0.250 | 0.500 |
| [csb_sdlc_secure_haiku_20260228_124521](runs/csb_sdlc_secure_haiku_20260228_124521.md) | `csb_sdlc_secure` | `mcp-remote-direct` | 2 | 0.555 | 1.000 |
| [csb_sdlc_secure_haiku_20260302_221730](runs/csb_sdlc_secure_haiku_20260302_221730.md) | `csb_sdlc_secure` | `baseline-local-direct` | 10 | 0.499 | 0.800 |
| [csb_sdlc_secure_haiku_20260302_221730](runs/csb_sdlc_secure_haiku_20260302_221730.md) | `csb_sdlc_secure` | `mcp-remote-direct` | 8 | 0.805 | 1.000 |
| [csb_sdlc_secure_haiku_20260302_224010](runs/csb_sdlc_secure_haiku_20260302_224010.md) | `csb_sdlc_secure` | `baseline-local-direct` | 5 | 0.676 | 1.000 |
| [csb_sdlc_secure_haiku_20260302_224010](runs/csb_sdlc_secure_haiku_20260302_224010.md) | `csb_sdlc_secure` | `mcp-remote-direct` | 4 | 0.627 | 1.000 |
| [csb_sdlc_secure_haiku_20260302_232613](runs/csb_sdlc_secure_haiku_20260302_232613.md) | `csb_sdlc_secure` | `mcp-remote-direct` | 1 | 0.700 | 1.000 |
| [csb_sdlc_secure_haiku_20260303_034215](runs/csb_sdlc_secure_haiku_20260303_034215.md) | `csb_sdlc_secure` | `baseline-local-direct` | 4 | 0.738 | 1.000 |
| [csb_sdlc_secure_haiku_20260303_034215](runs/csb_sdlc_secure_haiku_20260303_034215.md) | `csb_sdlc_secure` | `mcp-remote-direct` | 4 | 0.688 | 1.000 |
| [csb_sdlc_secure_haiku_20260303_140132](runs/csb_sdlc_secure_haiku_20260303_140132.md) | `csb_sdlc_secure` | `baseline-local-direct` | 1 | 0.550 | 1.000 |
| [csb_sdlc_secure_haiku_20260303_140132](runs/csb_sdlc_secure_haiku_20260303_140132.md) | `csb_sdlc_secure` | `mcp-remote-direct` | 1 | 0.550 | 1.000 |
| [csb_sdlc_secure_haiku_20260303_141005](runs/csb_sdlc_secure_haiku_20260303_141005.md) | `csb_sdlc_secure` | `baseline-local-direct` | 6 | 0.857 | 1.000 |
| [csb_sdlc_secure_haiku_20260303_142451](runs/csb_sdlc_secure_haiku_20260303_142451.md) | `csb_sdlc_secure` | `baseline-local-direct` | 4 | 0.910 | 1.000 |
| [csb_sdlc_secure_haiku_20260303_143323](runs/csb_sdlc_secure_haiku_20260303_143323.md) | `csb_sdlc_secure` | `baseline-local-direct` | 1 | 1.000 | 1.000 |
| [csb_sdlc_secure_haiku_20260303_152731](runs/csb_sdlc_secure_haiku_20260303_152731.md) | `csb_sdlc_secure` | `mcp-remote-direct` | 1 | 0.600 | 1.000 |
| [csb_sdlc_secure_haiku_20260307_001927](runs/csb_sdlc_secure_haiku_20260307_001927.md) | `csb_sdlc_secure` | `baseline-local-direct` | 1 | 0.800 | 1.000 |
| [csb_sdlc_secure_haiku_20260307_001927](runs/csb_sdlc_secure_haiku_20260307_001927.md) | `csb_sdlc_secure` | `mcp-remote-direct` | 3 | 0.937 | 1.000 |
| [csb_sdlc_secure_haiku_20260309_223654](runs/csb_sdlc_secure_haiku_20260309_223654.md) | `csb_sdlc_secure` | `baseline-local-direct` | 1 | 0.800 | 1.000 |
| [csb_sdlc_secure_haiku_20260309_223654](runs/csb_sdlc_secure_haiku_20260309_223654.md) | `csb_sdlc_secure` | `mcp-remote-direct` | 1 | 1.000 | 1.000 |
| [csb_sdlc_secure_sonnet_20260308_034803](runs/csb_sdlc_secure_sonnet_20260308_034803.md) | `csb_sdlc_secure` | `baseline-local-direct` | 10 | 0.792 | 1.000 |
| [csb_sdlc_secure_sonnet_20260308_034803](runs/csb_sdlc_secure_sonnet_20260308_034803.md) | `csb_sdlc_secure` | `mcp-remote-direct` | 12 | 0.749 | 1.000 |
| [csb_sdlc_secure_sonnet_20260309_013353](runs/csb_sdlc_secure_sonnet_20260309_013353.md) | `csb_sdlc_secure` | `baseline-local-direct` | 1 | 0.500 | 1.000 |
| [csb_sdlc_secure_sonnet_20260309_013354](runs/csb_sdlc_secure_sonnet_20260309_013354.md) | `csb_sdlc_secure` | `mcp-remote-direct` | 1 | 0.000 | 0.000 |
| [csb_sdlc_secure_sonnet_20260309_142738](runs/csb_sdlc_secure_sonnet_20260309_142738.md) | `csb_sdlc_secure` | `mcp-remote-direct` | 1 | 0.700 | 1.000 |
| [csb_sdlc_test_haiku_20260224_180149](runs/csb_sdlc_test_haiku_20260224_180149.md) | `csb_sdlc_test` | `baseline-local-direct` | 11 | 0.486 | 0.727 |
| [csb_sdlc_test_haiku_20260224_180149](runs/csb_sdlc_test_haiku_20260224_180149.md) | `csb_sdlc_test` | `mcp-remote-direct` | 11 | 0.387 | 0.727 |
| [csb_sdlc_test_haiku_20260226_015500_backfill](runs/csb_sdlc_test_haiku_20260226_015500_backfill.md) | `csb_sdlc_test` | `baseline-local-direct` | 1 | 0.370 | 1.000 |
| [csb_sdlc_test_haiku_20260226_015500_backfill](runs/csb_sdlc_test_haiku_20260226_015500_backfill.md) | `csb_sdlc_test` | `mcp-remote-direct` | 1 | 0.900 | 1.000 |
| [csb_sdlc_test_haiku_20260228_124521](runs/csb_sdlc_test_haiku_20260228_124521.md) | `csb_sdlc_test` | `mcp-remote-direct` | 4 | 0.985 | 1.000 |
| [csb_sdlc_test_haiku_20260301_230048](runs/csb_sdlc_test_haiku_20260301_230048.md) | `csb_sdlc_test` | `baseline-local-direct` | 13 | 0.644 | 0.923 |
| [csb_sdlc_test_haiku_20260301_230048](runs/csb_sdlc_test_haiku_20260301_230048.md) | `csb_sdlc_test` | `mcp-remote-direct` | 6 | 0.798 | 1.000 |
| [csb_sdlc_test_haiku_20260302_004743](runs/csb_sdlc_test_haiku_20260302_004743.md) | `csb_sdlc_test` | `baseline-local-direct` | 3 | 0.660 | 1.000 |
| [csb_sdlc_test_haiku_20260302_005945](runs/csb_sdlc_test_haiku_20260302_005945.md) | `csb_sdlc_test` | `baseline-local-direct` | 1 | 0.500 | 1.000 |
| [csb_sdlc_test_haiku_20260302_005945](runs/csb_sdlc_test_haiku_20260302_005945.md) | `csb_sdlc_test` | `mcp-remote-direct` | 1 | 0.370 | 1.000 |
| [csb_sdlc_test_haiku_20260302_005947](runs/csb_sdlc_test_haiku_20260302_005947.md) | `csb_sdlc_test` | `baseline-local-direct` | 5 | 0.732 | 1.000 |
| [csb_sdlc_test_haiku_20260302_013712](runs/csb_sdlc_test_haiku_20260302_013712.md) | `csb_sdlc_test` | `baseline-local-direct` | 1 | 0.000 | 0.000 |
| [csb_sdlc_test_haiku_20260302_013713](runs/csb_sdlc_test_haiku_20260302_013713.md) | `csb_sdlc_test` | `mcp-remote-direct` | 1 | 0.000 | 0.000 |
| [csb_sdlc_test_haiku_20260302_020340](runs/csb_sdlc_test_haiku_20260302_020340.md) | `csb_sdlc_test` | `mcp-remote-direct` | 6 | 0.450 | 1.000 |
| [csb_sdlc_test_haiku_20260302_021358](runs/csb_sdlc_test_haiku_20260302_021358.md) | `csb_sdlc_test` | `mcp-remote-direct` | 1 | 0.620 | 1.000 |
| [csb_sdlc_test_haiku_20260302_021447](runs/csb_sdlc_test_haiku_20260302_021447.md) | `csb_sdlc_test` | `baseline-local-direct` | 7 | 0.627 | 1.000 |
| [csb_sdlc_test_haiku_20260302_022542](runs/csb_sdlc_test_haiku_20260302_022542.md) | `csb_sdlc_test` | `baseline-local-direct` | 1 | 0.440 | 1.000 |
| [csb_sdlc_test_haiku_20260302_022542](runs/csb_sdlc_test_haiku_20260302_022542.md) | `csb_sdlc_test` | `mcp-remote-direct` | 1 | 0.290 | 1.000 |
| [csb_sdlc_test_haiku_20260302_022544](runs/csb_sdlc_test_haiku_20260302_022544.md) | `csb_sdlc_test` | `baseline-local-direct` | 4 | 0.775 | 1.000 |
| [csb_sdlc_test_haiku_20260302_022552](runs/csb_sdlc_test_haiku_20260302_022552.md) | `csb_sdlc_test` | `baseline-local-direct` | 2 | 0.240 | 0.500 |
| [csb_sdlc_test_haiku_20260302_022553](runs/csb_sdlc_test_haiku_20260302_022553.md) | `csb_sdlc_test` | `mcp-remote-direct` | 1 | 0.000 | 0.000 |
| [csb_sdlc_test_haiku_20260302_032307](runs/csb_sdlc_test_haiku_20260302_032307.md) | `csb_sdlc_test` | `baseline-local-direct` | 3 | 0.670 | 1.000 |
| [csb_sdlc_test_haiku_20260302_041201](runs/csb_sdlc_test_haiku_20260302_041201.md) | `csb_sdlc_test` | `mcp-remote-direct` | 3 | 0.503 | 1.000 |
| [csb_sdlc_test_haiku_20260302_221730](runs/csb_sdlc_test_haiku_20260302_221730.md) | `csb_sdlc_test` | `baseline-local-direct` | 2 | 0.225 | 1.000 |
| [csb_sdlc_test_haiku_20260302_221730](runs/csb_sdlc_test_haiku_20260302_221730.md) | `csb_sdlc_test` | `mcp-remote-direct` | 1 | 0.900 | 1.000 |
| [csb_sdlc_test_haiku_20260302_221754](runs/csb_sdlc_test_haiku_20260302_221754.md) | `csb_sdlc_test` | `mcp-remote-direct` | 3 | 0.987 | 1.000 |
| [csb_sdlc_test_haiku_20260302_224010](runs/csb_sdlc_test_haiku_20260302_224010.md) | `csb_sdlc_test` | `baseline-local-direct` | 2 | 0.615 | 1.000 |
| [csb_sdlc_test_haiku_20260302_224010](runs/csb_sdlc_test_haiku_20260302_224010.md) | `csb_sdlc_test` | `mcp-remote-direct` | 2 | 0.490 | 1.000 |
| [csb_sdlc_test_haiku_20260302_224219](runs/csb_sdlc_test_haiku_20260302_224219.md) | `csb_sdlc_test` | `baseline-local-direct` | 1 | 0.370 | 1.000 |
| [csb_sdlc_test_haiku_20260307_001927](runs/csb_sdlc_test_haiku_20260307_001927.md) | `csb_sdlc_test` | `baseline-local-direct` | 2 | 0.833 | 1.000 |
| [csb_sdlc_test_haiku_20260307_001927](runs/csb_sdlc_test_haiku_20260307_001927.md) | `csb_sdlc_test` | `mcp-remote-direct` | 2 | 0.917 | 1.000 |
| [csb_sdlc_test_sonnet_20260308_034803](runs/csb_sdlc_test_sonnet_20260308_034803.md) | `csb_sdlc_test` | `baseline-local-direct` | 12 | 0.722 | 1.000 |
| [csb_sdlc_test_sonnet_20260308_034803](runs/csb_sdlc_test_sonnet_20260308_034803.md) | `csb_sdlc_test` | `mcp-remote-direct` | 9 | 0.681 | 0.889 |
| [csb_sdlc_test_sonnet_20260309_013354](runs/csb_sdlc_test_sonnet_20260309_013354.md) | `csb_sdlc_test` | `mcp-remote-direct` | 3 | 0.517 | 1.000 |
| [csb_sdlc_understand_haiku_022426](runs/csb_sdlc_understand_haiku_022426.md) | `csb_sdlc_understand` | `baseline-local-direct` | 7 | 0.281 | 0.429 |
| [csb_sdlc_understand_haiku_022426](runs/csb_sdlc_understand_haiku_022426.md) | `csb_sdlc_understand` | `mcp-remote-direct` | 13 | 0.841 | 1.000 |
| [csb_sdlc_understand_haiku_20260227_132300](runs/csb_sdlc_understand_haiku_20260227_132300.md) | `csb_sdlc_understand` | `mcp-remote-direct` | 4 | 1.000 | 1.000 |
| [csb_sdlc_understand_haiku_20260227_132304](runs/csb_sdlc_understand_haiku_20260227_132304.md) | `csb_sdlc_understand` | `mcp-remote-direct` | 5 | 1.000 | 1.000 |
| [csb_sdlc_understand_haiku_20260228_124521](runs/csb_sdlc_understand_haiku_20260228_124521.md) | `csb_sdlc_understand` | `mcp-remote-direct` | 4 | 0.823 | 1.000 |
| [csb_sdlc_understand_haiku_20260302_221730](runs/csb_sdlc_understand_haiku_20260302_221730.md) | `csb_sdlc_understand` | `baseline-local-direct` | 10 | 0.522 | 0.700 |
| [csb_sdlc_understand_haiku_20260302_221730](runs/csb_sdlc_understand_haiku_20260302_221730.md) | `csb_sdlc_understand` | `mcp-remote-direct` | 7 | 0.787 | 1.000 |
| [csb_sdlc_understand_haiku_20260302_224010](runs/csb_sdlc_understand_haiku_20260302_224010.md) | `csb_sdlc_understand` | `baseline-local-direct` | 8 | 0.818 | 1.000 |
| [csb_sdlc_understand_haiku_20260302_224010](runs/csb_sdlc_understand_haiku_20260302_224010.md) | `csb_sdlc_understand` | `mcp-remote-direct` | 3 | 0.857 | 1.000 |
| [csb_sdlc_understand_haiku_20260303_034215](runs/csb_sdlc_understand_haiku_20260303_034215.md) | `csb_sdlc_understand` | `baseline-local-direct` | 2 | 0.945 | 1.000 |
| [csb_sdlc_understand_haiku_20260303_034215](runs/csb_sdlc_understand_haiku_20260303_034215.md) | `csb_sdlc_understand` | `mcp-remote-direct` | 2 | 0.880 | 1.000 |
| [csb_sdlc_understand_haiku_20260303_140132](runs/csb_sdlc_understand_haiku_20260303_140132.md) | `csb_sdlc_understand` | `baseline-local-direct` | 1 | 0.840 | 1.000 |
| [csb_sdlc_understand_haiku_20260303_140132](runs/csb_sdlc_understand_haiku_20260303_140132.md) | `csb_sdlc_understand` | `mcp-remote-direct` | 1 | 0.950 | 1.000 |
| [csb_sdlc_understand_haiku_20260303_141005](runs/csb_sdlc_understand_haiku_20260303_141005.md) | `csb_sdlc_understand` | `baseline-local-direct` | 1 | 0.840 | 1.000 |
| [csb_sdlc_understand_haiku_20260303_152731](runs/csb_sdlc_understand_haiku_20260303_152731.md) | `csb_sdlc_understand` | `mcp-remote-direct` | 1 | 0.870 | 1.000 |
| [csb_sdlc_understand_haiku_20260303_190739](runs/csb_sdlc_understand_haiku_20260303_190739.md) | `csb_sdlc_understand` | `mcp-remote-direct` | 1 | 0.850 | 1.000 |
| [csb_sdlc_understand_haiku_20260307_001927](runs/csb_sdlc_understand_haiku_20260307_001927.md) | `csb_sdlc_understand` | `baseline-local-direct` | 1 | 0.100 | 1.000 |
| [csb_sdlc_understand_haiku_20260307_001927](runs/csb_sdlc_understand_haiku_20260307_001927.md) | `csb_sdlc_understand` | `mcp-remote-direct` | 2 | 0.550 | 1.000 |
| [csb_sdlc_understand_sonnet_20260308_034803](runs/csb_sdlc_understand_sonnet_20260308_034803.md) | `csb_sdlc_understand` | `baseline-local-direct` | 9 | 0.919 | 1.000 |
| [csb_sdlc_understand_sonnet_20260308_034803](runs/csb_sdlc_understand_sonnet_20260308_034803.md) | `csb_sdlc_understand` | `mcp-remote-direct` | 10 | 0.902 | 1.000 |
| [csb_sdlc_understand_sonnet_20260309_013353](runs/csb_sdlc_understand_sonnet_20260309_013353.md) | `csb_sdlc_understand` | `baseline-local-direct` | 1 | 1.000 | 1.000 |
| [csb_sdlc_understand_sonnet_20260309_013354](runs/csb_sdlc_understand_sonnet_20260309_013354.md) | `csb_sdlc_understand` | `mcp-remote-direct` | 1 | 0.933 | 1.000 |
| [csb_sdlc_understand_sonnet_20260309_142738](runs/csb_sdlc_understand_sonnet_20260309_142738.md) | `csb_sdlc_understand` | `mcp-remote-direct` | 1 | 1.000 | 1.000 |
| [debug_haiku_20260228_230112](runs/debug_haiku_20260228_230112.md) | `csb_sdlc_debug` | `baseline-local-direct` | 10 | 0.833 | 1.000 |
| [debug_haiku_20260228_230112](runs/debug_haiku_20260228_230112.md) | `csb_sdlc_debug` | `mcp-remote-direct` | 8 | 0.730 | 1.000 |
| [debug_haiku_20260228_230648](runs/debug_haiku_20260228_230648.md) | `csb_sdlc_debug` | `baseline-local-direct` | 11 | 0.864 | 1.000 |
| [debug_haiku_20260228_230648](runs/debug_haiku_20260228_230648.md) | `csb_sdlc_debug` | `mcp-remote-direct` | 2 | 1.000 | 1.000 |
| [debug_haiku_20260228_231033](runs/debug_haiku_20260228_231033.md) | `csb_sdlc_debug` | `baseline-local-direct` | 9 | 0.826 | 1.000 |
| [debug_haiku_20260228_231033](runs/debug_haiku_20260228_231033.md) | `csb_sdlc_debug` | `mcp-remote-direct` | 10 | 0.804 | 1.000 |
| [debug_haiku_20260301_021540](runs/debug_haiku_20260301_021540.md) | `csb_sdlc_debug` | `baseline-local-direct` | 9 | 0.813 | 1.000 |
| [debug_haiku_20260301_021540](runs/debug_haiku_20260301_021540.md) | `csb_sdlc_debug` | `mcp-remote-direct` | 11 | 0.813 | 1.000 |
| [debug_haiku_20260301_030159](runs/debug_haiku_20260301_030159.md) | `csb_sdlc_debug` | `baseline-local-direct` | 9 | 0.801 | 1.000 |
| [debug_haiku_20260301_030159](runs/debug_haiku_20260301_030159.md) | `csb_sdlc_debug` | `mcp-remote-direct` | 11 | 0.801 | 1.000 |
| [debug_haiku_20260301_031844](runs/debug_haiku_20260301_031844.md) | `csb_sdlc_debug` | `baseline-local-direct` | 9 | 0.763 | 1.000 |
| [debug_haiku_20260301_031844](runs/debug_haiku_20260301_031844.md) | `csb_sdlc_debug` | `mcp-remote-direct` | 11 | 0.750 | 1.000 |
| [debug_haiku_20260301_033225](runs/debug_haiku_20260301_033225.md) | `csb_sdlc_debug` | `baseline-local-direct` | 9 | 0.444 | 0.889 |
| [debug_haiku_20260301_033225](runs/debug_haiku_20260301_033225.md) | `csb_sdlc_debug` | `mcp-remote-direct` | 9 | 0.389 | 0.778 |
| [debug_haiku_20260301_035030](runs/debug_haiku_20260301_035030.md) | `csb_sdlc_debug` | `baseline-local-direct` | 9 | 0.333 | 0.667 |
| [debug_haiku_20260301_035030](runs/debug_haiku_20260301_035030.md) | `csb_sdlc_debug` | `mcp-remote-direct` | 9 | 0.278 | 0.556 |
| [debug_haiku_20260301_040300](runs/debug_haiku_20260301_040300.md) | `csb_sdlc_debug` | `baseline-local-direct` | 9 | 0.500 | 1.000 |
| [debug_haiku_20260301_040300](runs/debug_haiku_20260301_040300.md) | `csb_sdlc_debug` | `mcp-remote-direct` | 9 | 0.389 | 0.778 |
| [debug_haiku_20260301_071226](runs/debug_haiku_20260301_071226.md) | `csb_sdlc_debug` | `baseline-local-direct` | 9 | 0.807 | 1.000 |
| [debug_haiku_20260301_071226](runs/debug_haiku_20260301_071226.md) | `csb_sdlc_debug` | `mcp-remote-direct` | 11 | 0.841 | 1.000 |
| [debug_sonnet_20260219_123545](runs/debug_sonnet_20260219_123545.md) | `csb_sdlc_debug` | `baseline-local-direct` | 2 | 0.750 | 1.000 |
| [debug_sonnet_20260219_123545](runs/debug_sonnet_20260219_123545.md) | `csb_sdlc_debug` | `sourcegraph_full` | 1 | 1.000 | 1.000 |
| [debug_sonnet_20260219_123557](runs/debug_sonnet_20260219_123557.md) | `csb_sdlc_debug` | `baseline-local-direct` | 2 | 0.750 | 1.000 |
| [debug_sonnet_20260219_123557](runs/debug_sonnet_20260219_123557.md) | `csb_sdlc_debug` | `sourcegraph_full` | 2 | 0.750 | 1.000 |
| [dependeval_opus_20260203_192907](runs/dependeval_opus_20260203_192907.md) | `ccb_dependeval` | `baseline` | 6 | 0.561 | 0.667 |
| [design_haiku_20260301_022406](runs/design_haiku_20260301_022406.md) | `csb_sdlc_design` | `baseline-local-direct` | 14 | 0.784 | 1.000 |
| [design_haiku_20260301_022406](runs/design_haiku_20260301_022406.md) | `csb_sdlc_design` | `mcp-remote-direct` | 20 | 0.734 | 1.000 |
| [design_haiku_20260301_031030](runs/design_haiku_20260301_031030.md) | `csb_sdlc_design` | `baseline-local-direct` | 14 | 0.786 | 0.929 |
| [design_haiku_20260301_031030](runs/design_haiku_20260301_031030.md) | `csb_sdlc_design` | `mcp-remote-direct` | 20 | 0.747 | 1.000 |
| [design_haiku_20260301_031845](runs/design_haiku_20260301_031845.md) | `csb_sdlc_design` | `baseline-local-direct` | 14 | 0.833 | 1.000 |
| [design_haiku_20260301_031845](runs/design_haiku_20260301_031845.md) | `csb_sdlc_design` | `mcp-remote-direct` | 19 | 0.701 | 1.000 |
| [design_haiku_20260301_071227](runs/design_haiku_20260301_071227.md) | `csb_sdlc_design` | `baseline-local-direct` | 14 | 0.791 | 1.000 |
| [design_haiku_20260301_071227](runs/design_haiku_20260301_071227.md) | `csb_sdlc_design` | `mcp-remote-direct` | 20 | 0.699 | 0.950 |
| [dibench_opus_20260203_224544__duplicate_rerun](runs/dibench_opus_20260203_224544__duplicate_rerun.md) | `ccb_dibench` | `sourcegraph_base` | 4 | 0.250 | 0.250 |
| [dibench_opus_20260203_224544__duplicate_rerun](runs/dibench_opus_20260203_224544__duplicate_rerun.md) | `ccb_dibench` | `sourcegraph_full` | 4 | 0.250 | 0.250 |
| [document_haiku_20260223_164240](runs/document_haiku_20260223_164240.md) | `csb_sdlc_document` | `baseline-local-direct` | 13 | 0.787 | 1.000 |
| [document_haiku_20260223_164240](runs/document_haiku_20260223_164240.md) | `csb_sdlc_document` | `mcp-remote-direct` | 20 | 0.822 | 1.000 |
| [document_haiku_20260301_031846](runs/document_haiku_20260301_031846.md) | `csb_sdlc_document` | `baseline-local-direct` | 13 | 0.810 | 1.000 |
| [document_haiku_20260301_031846](runs/document_haiku_20260301_031846.md) | `csb_sdlc_document` | `mcp-remote-direct` | 20 | 0.908 | 1.000 |
| [document_haiku_20260301_071228](runs/document_haiku_20260301_071228.md) | `csb_sdlc_document` | `baseline-local-direct` | 13 | 0.762 | 1.000 |
| [document_haiku_20260301_071228](runs/document_haiku_20260301_071228.md) | `csb_sdlc_document` | `mcp-remote-direct` | 20 | 0.898 | 1.000 |
| [document_opus_20260218_184321__sgfull_invalid_truncation_gap](runs/document_opus_20260218_184321__sgfull_invalid_truncation_gap.md) | `csb_sdlc_document` | `baseline-local-direct` | 1 | 0.520 | 1.000 |
| [document_opus_20260218_184321__sgfull_invalid_truncation_gap](runs/document_opus_20260218_184321__sgfull_invalid_truncation_gap.md) | `csb_sdlc_document` | `sourcegraph_full` | 1 | 0.570 | 1.000 |
| [document_sonnet_20260218_190929__sgfull_invalid_truncation_gap](runs/document_sonnet_20260218_190929__sgfull_invalid_truncation_gap.md) | `csb_sdlc_document` | `baseline-local-direct` | 9 | 0.828 | 1.000 |
| [document_sonnet_20260218_190929__sgfull_invalid_truncation_gap](runs/document_sonnet_20260218_190929__sgfull_invalid_truncation_gap.md) | `csb_sdlc_document` | `sourcegraph_full` | 12 | 0.883 | 1.000 |
| [document_sonnet_20260218_200522__sgfull_invalid_writeonly_misclass](runs/document_sonnet_20260218_200522__sgfull_invalid_writeonly_misclass.md) | `csb_sdlc_document` | `sourcegraph_full` | 13 | 0.838 | 1.000 |
| [document_sonnet_20260218_210956](runs/document_sonnet_20260218_210956.md) | `csb_sdlc_document` | `sourcegraph_full` | 1 | 0.450 | 1.000 |
| [document_sonnet_20260218_211905](runs/document_sonnet_20260218_211905.md) | `csb_sdlc_document` | `sourcegraph_full` | 1 | 1.000 | 1.000 |
| [document_sonnet_20260218_212520](runs/document_sonnet_20260218_212520.md) | `csb_sdlc_document` | `sourcegraph_full` | 1 | 1.000 | 1.000 |
| [document_sonnet_20260218_213037](runs/document_sonnet_20260218_213037.md) | `csb_sdlc_document` | `sourcegraph_full` | 1 | 0.830 | 1.000 |
| [document_sonnet_20260218_220101](runs/document_sonnet_20260218_220101.md) | `csb_sdlc_document` | `sourcegraph_full` | 1 | 0.320 | 1.000 |
| [document_sonnet_20260219_012208](runs/document_sonnet_20260219_012208.md) | `csb_sdlc_document` | `sourcegraph_full` | 1 | 0.880 | 1.000 |
| [document_sonnet_20260219_012939](runs/document_sonnet_20260219_012939.md) | `csb_sdlc_document` | `sourcegraph_full` | 1 | 1.000 | 1.000 |
| [document_sonnet_20260219_013628](runs/document_sonnet_20260219_013628.md) | `csb_sdlc_document` | `sourcegraph_full` | 1 | 0.830 | 1.000 |
| [document_sonnet_20260219_014229](runs/document_sonnet_20260219_014229.md) | `csb_sdlc_document` | `sourcegraph_full` | 1 | 0.650 | 1.000 |
| [document_sonnet_20260219_014831](runs/document_sonnet_20260219_014831.md) | `csb_sdlc_document` | `sourcegraph_full` | 1 | 0.320 | 1.000 |
| [feature_haiku_20260228_190114](runs/feature_haiku_20260228_190114.md) | `csb_sdlc_feature` | `baseline-local-direct` | 5 | 0.507 | 0.600 |
| [feature_haiku_20260228_190114](runs/feature_haiku_20260228_190114.md) | `csb_sdlc_feature` | `mcp-remote-direct` | 6 | 0.550 | 0.833 |
| [feature_haiku_20260228_211127](runs/feature_haiku_20260228_211127.md) | `csb_sdlc_feature` | `baseline-local-direct` | 17 | 0.664 | 0.941 |
| [feature_haiku_20260228_211127](runs/feature_haiku_20260228_211127.md) | `csb_sdlc_feature` | `mcp-remote-direct` | 16 | 0.586 | 0.875 |
| [feature_haiku_20260228_220733](runs/feature_haiku_20260228_220733.md) | `csb_sdlc_feature` | `baseline-local-direct` | 4 | 0.375 | 0.500 |
| [feature_haiku_20260228_220733](runs/feature_haiku_20260228_220733.md) | `csb_sdlc_feature` | `mcp-remote-direct` | 4 | 0.542 | 0.750 |
| [feature_haiku_20260228_230114](runs/feature_haiku_20260228_230114.md) | `csb_sdlc_feature` | `mcp-remote-direct` | 1 | 0.280 | 1.000 |
| [feature_haiku_20260228_231035](runs/feature_haiku_20260228_231035.md) | `csb_sdlc_feature` | `mcp-remote-direct` | 3 | 0.222 | 0.333 |
| [feature_haiku_20260228_231041](runs/feature_haiku_20260228_231041.md) | `csb_sdlc_feature` | `baseline-local-direct` | 4 | 0.557 | 1.000 |
| [feature_haiku_20260301_023333](runs/feature_haiku_20260301_023333.md) | `csb_sdlc_feature` | `baseline-local-direct` | 8 | 0.835 | 1.000 |
| [feature_haiku_20260301_023333](runs/feature_haiku_20260301_023333.md) | `csb_sdlc_feature` | `mcp-remote-direct` | 6 | 0.867 | 1.000 |
| [feature_haiku_20260301_031848](runs/feature_haiku_20260301_031848.md) | `csb_sdlc_feature` | `baseline-local-direct` | 19 | 0.638 | 0.895 |
| [feature_haiku_20260301_031848](runs/feature_haiku_20260301_031848.md) | `csb_sdlc_feature` | `mcp-remote-direct` | 18 | 0.644 | 0.889 |
| [feature_haiku_20260301_071229](runs/feature_haiku_20260301_071229.md) | `csb_sdlc_feature` | `baseline-local-direct` | 20 | 0.631 | 0.850 |
| [feature_haiku_20260301_071229](runs/feature_haiku_20260301_071229.md) | `csb_sdlc_feature` | `mcp-remote-direct` | 19 | 0.582 | 0.842 |
| [feature_haiku_vscode_rerun_20260301_023018](runs/feature_haiku_vscode_rerun_20260301_023018.md) | `csb_sdlc_feature` | `baseline-local-direct` | 1 | 0.500 | 1.000 |
| [fix_haiku_20260222_045038__pre_sgenv_fix](runs/fix_haiku_20260222_045038__pre_sgenv_fix.md) | `csb_sdlc_fix` | `baseline-local-artifact` | 1 | 0.550 | 1.000 |
| [fix_haiku_20260222_123712__pre_sgenv_fix](runs/fix_haiku_20260222_123712__pre_sgenv_fix.md) | `csb_sdlc_fix` | `baseline-local-artifact` | 1 | 0.640 | 1.000 |
| [fix_haiku_20260222_123712__pre_sgenv_fix](runs/fix_haiku_20260222_123712__pre_sgenv_fix.md) | `csb_sdlc_fix` | `mcp-remote-artifact` | 1 | 0.200 | 1.000 |
| [fix_haiku_20260223_171232](runs/fix_haiku_20260223_171232.md) | `csb_sdlc_fix` | `mcp-remote-direct` | 17 | 0.538 | 0.647 |
| [fix_haiku_20260224_011821](runs/fix_haiku_20260224_011821.md) | `csb_sdlc_fix` | `mcp-remote-direct` | 1 | 0.780 | 1.000 |
| [fix_haiku_20260226_024454](runs/fix_haiku_20260226_024454.md) | `csb_sdlc_fix` | `mcp-remote-direct` | 2 | 0.000 | 0.000 |
| [fix_haiku_20260226_new3tasks](runs/fix_haiku_20260226_new3tasks.md) | `csb_sdlc_fix` | `mcp-remote-direct` | 3 | 0.801 | 1.000 |
| [fix_haiku_20260301_190026](runs/fix_haiku_20260301_190026.md) | `csb_sdlc_fix` | `baseline-local-direct` | 2 | 0.000 | 0.000 |
| [fix_haiku_20260301_190026](runs/fix_haiku_20260301_190026.md) | `csb_sdlc_fix` | `mcp-remote-direct` | 2 | 0.000 | 0.000 |
| [fix_haiku_20260308_003505](runs/fix_haiku_20260308_003505.md) | `csb_sdlc_fix` | `baseline-local-direct` | 1 | 1.000 | 1.000 |
| [fix_haiku_20260308_003505](runs/fix_haiku_20260308_003505.md) | `csb_sdlc_fix` | `mcp-remote-direct` | 1 | 0.000 | 0.000 |
| [fix_haiku_20260308_011252](runs/fix_haiku_20260308_011252.md) | `csb_sdlc_fix` | `mcp-remote-direct` | 1 | 1.000 | 1.000 |
| [investigation_haiku_20260207_150959](runs/investigation_haiku_20260207_150959.md) | `ccb_investigation` | `baseline` | 1 | 1.000 | 1.000 |
| [investigation_haiku_20260207_150959](runs/investigation_haiku_20260207_150959.md) | `ccb_investigation` | `sourcegraph_base` | 1 | 0.900 | 1.000 |
| [investigation_haiku_20260207_150959](runs/investigation_haiku_20260207_150959.md) | `ccb_investigation` | `sourcegraph_full` | 1 | 1.000 | 1.000 |
| [investigation_haiku_20260207_151000](runs/investigation_haiku_20260207_151000.md) | `ccb_investigation` | `baseline` | 1 | 1.000 | 1.000 |
| [investigation_haiku_20260207_151000](runs/investigation_haiku_20260207_151000.md) | `ccb_investigation` | `sourcegraph_base` | 1 | 0.700 | 1.000 |
| [investigation_haiku_20260207_151000](runs/investigation_haiku_20260207_151000.md) | `ccb_investigation` | `sourcegraph_full` | 1 | 0.700 | 1.000 |
| [investigation_haiku_20260207_151001](runs/investigation_haiku_20260207_151001.md) | `ccb_investigation` | `baseline` | 1 | 0.880 | 1.000 |
| [investigation_haiku_20260207_151001](runs/investigation_haiku_20260207_151001.md) | `ccb_investigation` | `sourcegraph_base` | 1 | 0.380 | 1.000 |
| [investigation_haiku_20260207_151001](runs/investigation_haiku_20260207_151001.md) | `ccb_investigation` | `sourcegraph_full` | 1 | 0.840 | 1.000 |
| [investigation_haiku_20260207_151002](runs/investigation_haiku_20260207_151002.md) | `ccb_investigation` | `baseline` | 1 | 1.000 | 1.000 |
| [investigation_haiku_20260207_151002](runs/investigation_haiku_20260207_151002.md) | `ccb_investigation` | `sourcegraph_base` | 1 | 1.000 | 1.000 |
| [investigation_haiku_20260207_151002](runs/investigation_haiku_20260207_151002.md) | `ccb_investigation` | `sourcegraph_full` | 1 | 1.000 | 1.000 |
| [investigation_opus_20260207_134633](runs/investigation_opus_20260207_134633.md) | `ccb_investigation` | `baseline` | 1 | 0.920 | 1.000 |
| [investigation_opus_20260207_134633](runs/investigation_opus_20260207_134633.md) | `ccb_investigation` | `sourcegraph_base` | 1 | 1.000 | 1.000 |
| [investigation_opus_20260207_134633](runs/investigation_opus_20260207_134633.md) | `ccb_investigation` | `sourcegraph_full` | 1 | 0.920 | 1.000 |
| [investigation_opus_20260207_142354](runs/investigation_opus_20260207_142354.md) | `ccb_investigation` | `baseline` | 1 | 0.900 | 1.000 |
| [investigation_opus_20260207_142354](runs/investigation_opus_20260207_142354.md) | `ccb_investigation` | `sourcegraph_base` | 1 | 0.900 | 1.000 |
| [investigation_opus_20260207_142354](runs/investigation_opus_20260207_142354.md) | `ccb_investigation` | `sourcegraph_full` | 1 | 0.900 | 1.000 |
| [investigation_opus_20260207_142924](runs/investigation_opus_20260207_142924.md) | `ccb_investigation` | `baseline` | 1 | 0.940 | 1.000 |
| [investigation_opus_20260207_142924](runs/investigation_opus_20260207_142924.md) | `ccb_investigation` | `sourcegraph_base` | 1 | 0.940 | 1.000 |
| [investigation_opus_20260207_142924](runs/investigation_opus_20260207_142924.md) | `ccb_investigation` | `sourcegraph_full` | 1 | 0.940 | 1.000 |
| [investigation_opus_20260207_142925](runs/investigation_opus_20260207_142925.md) | `ccb_investigation` | `baseline` | 1 | 1.000 | 1.000 |
| [investigation_opus_20260207_142925](runs/investigation_opus_20260207_142925.md) | `ccb_investigation` | `sourcegraph_base` | 1 | 1.000 | 1.000 |
| [investigation_opus_20260207_142925](runs/investigation_opus_20260207_142925.md) | `ccb_investigation` | `sourcegraph_full` | 1 | 1.000 | 1.000 |
| [k8s_docs_opus_20260203_160607](runs/k8s_docs_opus_20260203_160607.md) | `ccb_k8sdocs` | `sourcegraph_base` | 4 | 0.925 | 1.000 |
| [k8s_docs_opus_20260204_133210](runs/k8s_docs_opus_20260204_133210.md) | `ccb_k8sdocs` | `baseline` | 1 | 0.900 | 1.000 |
| [k8s_docs_opus_20260204_133210](runs/k8s_docs_opus_20260204_133210.md) | `ccb_k8sdocs` | `sourcegraph_base` | 1 | 0.900 | 1.000 |
| [linuxflbench_opus_20260206_164001__doubled_prefix](runs/linuxflbench_opus_20260206_164001__doubled_prefix.md) | `ccb_linuxflbench` | `sourcegraph_base` | 5 | 0.740 | 1.000 |
| [linuxflbench_opus_20260206_173138](runs/linuxflbench_opus_20260206_173138.md) | `ccb_linuxflbench` | `sourcegraph_full` | 2 | 1.000 | 1.000 |
| [linuxflbench_opus_20260206_174506](runs/linuxflbench_opus_20260206_174506.md) | `ccb_linuxflbench` | `sourcegraph_full` | 1 | 1.000 | 1.000 |
| [linuxflbench_opus_20260206_180131__doubled_prefix_ds_compromised](runs/linuxflbench_opus_20260206_180131__doubled_prefix_ds_compromised.md) | `ccb_linuxflbench` | `sourcegraph_full` | 5 | 0.860 | 1.000 |
| [locobench_079_empty_repo_20260206](runs/locobench_079_empty_repo_20260206.md) | `ccb_locobench` | `sourcegraph_base` | 2 | 0.501 | 1.000 |
| [locobench_50_tasks_opus_20260202_184142](runs/locobench_50_tasks_opus_20260202_184142.md) | `ccb_locobench` | `baseline` | 41 | 0.489 | 1.000 |
| [locobench_50_tasks_opus_20260202_211105](runs/locobench_50_tasks_opus_20260202_211105.md) | `ccb_locobench` | `sourcegraph_full` | 24 | 0.500 | 1.000 |
| [locobench_preamble_test_v3_opus_20260207_022151](runs/locobench_preamble_test_v3_opus_20260207_022151.md) | `ccb_locobench` | `sourcegraph_base` | 1 | 0.501 | 1.000 |
| [locobench_selected_opus_20260203_060731](runs/locobench_selected_opus_20260203_060731.md) | `ccb_locobench` | `baseline` | 5 | 0.486 | 1.000 |
| [locobench_selected_opus_20260203_085551](runs/locobench_selected_opus_20260203_085551.md) | `ccb_locobench` | `sourcegraph_full` | 1 | 0.563 | 1.000 |
| [locobench_selected_opus_20260203_160607](runs/locobench_selected_opus_20260203_160607.md) | `ccb_locobench` | `sourcegraph_base` | 5 | 0.503 | 1.000 |
| [locobench_selected_opus_20260203_224544__duplicate_rerun](runs/locobench_selected_opus_20260203_224544__duplicate_rerun.md) | `ccb_locobench` | `sourcegraph_full` | 2 | 0.499 | 1.000 |
| [openhands_sonnet46_20260308_190933](runs/openhands_sonnet46_20260308_190933.md) | `unknown` | `baseline-local-direct` | 121 | 0.366 | 0.719 |
| [openhands_sonnet46_20260308_190933](runs/openhands_sonnet46_20260308_190933.md) | `unknown` | `mcp-remote-direct` | 142 | 0.441 | 0.817 |
| [openhands_sonnet46_20260309_014704](runs/openhands_sonnet46_20260309_014704.md) | `unknown` | `baseline-local-direct` | 5 | 0.350 | 1.000 |
| [openhands_sonnet46_20260309_014704](runs/openhands_sonnet46_20260309_014704.md) | `unknown` | `mcp-remote-direct` | 4 | 0.213 | 1.000 |
| [openhands_sonnet46_20260309_210054](runs/openhands_sonnet46_20260309_210054.md) | `unknown` | `baseline-local-direct` | 1 | 0.050 | 0.000 |
| [openhands_sonnet46_20260309_210054](runs/openhands_sonnet46_20260309_210054.md) | `unknown` | `mcp-remote-direct` | 2 | 0.525 | 0.500 |
| [openhands_sonnet46_20260309_223658](runs/openhands_sonnet46_20260309_223658.md) | `unknown` | `baseline-local-direct` | 1 | 0.050 | 0.000 |
| [openhands_sonnet46_20260309_232133](runs/openhands_sonnet46_20260309_232133.md) | `unknown` | `baseline-local-direct` | 2 | 0.060 | 0.000 |
| [openhands_sonnet46_20260309_232947](runs/openhands_sonnet46_20260309_232947.md) | `unknown` | `baseline-local-direct` | 2 | 0.060 | 0.000 |
| [openhands_sonnet46_20260309_233609](runs/openhands_sonnet46_20260309_233609.md) | `unknown` | `baseline-local-direct` | 1 | 0.490 | 0.000 |
| [openhands_sonnet46_20260310_161619](runs/openhands_sonnet46_20260310_161619.md) | `unknown` | `baseline-local-direct` | 3 | 0.017 | 0.000 |
| [openhands_sonnet46_20260310_163513](runs/openhands_sonnet46_20260310_163513.md) | `unknown` | `baseline-local-direct` | 3 | 0.520 | 0.667 |
| [openhands_sonnet46_20260310_163513](runs/openhands_sonnet46_20260310_163513.md) | `unknown` | `mcp-remote-direct` | 2 | 0.545 | 1.000 |
| [openhands_sonnet46_20260310_164503](runs/openhands_sonnet46_20260310_164503.md) | `unknown` | `baseline-local-direct` | 3 | 0.517 | 0.667 |
| [openhands_sonnet46_20260310_164503](runs/openhands_sonnet46_20260310_164503.md) | `unknown` | `mcp-remote-direct` | 2 | 0.519 | 1.000 |
| [openhands_sonnet46_20260310_170342](runs/openhands_sonnet46_20260310_170342.md) | `unknown` | `baseline-local-direct` | 3 | 0.517 | 0.667 |
| [openhands_sonnet46_20260310_170342](runs/openhands_sonnet46_20260310_170342.md) | `unknown` | `mcp-remote-direct` | 3 | 0.678 | 1.000 |
| [openhands_sonnet46_20260310_171305](runs/openhands_sonnet46_20260310_171305.md) | `unknown` | `baseline-local-direct` | 3 | 0.630 | 1.000 |
| [openhands_sonnet46_20260310_171305](runs/openhands_sonnet46_20260310_171305.md) | `unknown` | `mcp-remote-direct` | 2 | 0.516 | 1.000 |
| [openhands_sonnet46_20260310_173833](runs/openhands_sonnet46_20260310_173833.md) | `unknown` | `baseline-local-direct` | 11 | 0.502 | 0.727 |
| [openhands_sonnet46_20260310_173833](runs/openhands_sonnet46_20260310_173833.md) | `unknown` | `mcp-remote-direct` | 5 | 0.720 | 0.800 |
| [openhands_sonnet46_20260310_191427](runs/openhands_sonnet46_20260310_191427.md) | `unknown` | `mcp-remote-direct` | 5 | 0.659 | 1.000 |
| [pytorch_gapfill_opus_20260205_040301](runs/pytorch_gapfill_opus_20260205_040301.md) | `ccb_pytorch` | `baseline` | 3 | 1.000 | 1.000 |
| [pytorch_gapfill_opus_20260205_040301](runs/pytorch_gapfill_opus_20260205_040301.md) | `ccb_pytorch` | `sourcegraph_base` | 5 | 0.800 | 0.800 |
| [pytorch_gapfill_opus_20260205_040301](runs/pytorch_gapfill_opus_20260205_040301.md) | `ccb_pytorch` | `sourcegraph_full` | 3 | 1.000 | 1.000 |
| [pytorch_opus_20260203_160607](runs/pytorch_opus_20260203_160607.md) | `ccb_pytorch` | `baseline` | 4 | 1.000 | 1.000 |
| [pytorch_opus_20260203_160607](runs/pytorch_opus_20260203_160607.md) | `ccb_pytorch` | `sourcegraph_full` | 1 | 1.000 | 1.000 |
| [pytorch_opus_20260204_133210](runs/pytorch_opus_20260204_133210.md) | `ccb_pytorch` | `baseline` | 5 | 1.000 | 1.000 |
| [pytorch_opus_20260204_133210](runs/pytorch_opus_20260204_133210.md) | `ccb_pytorch` | `sourcegraph_base` | 4 | 1.000 | 1.000 |
| [pytorch_opus_20260204_133210](runs/pytorch_opus_20260204_133210.md) | `ccb_pytorch` | `sourcegraph_full` | 5 | 1.000 | 1.000 |
| [pytorch_opus_20260205_192410](runs/pytorch_opus_20260205_192410.md) | `ccb_pytorch` | `baseline` | 1 | 0.000 | 0.000 |
| [pytorch_opus_20260205_204033](runs/pytorch_opus_20260205_204033.md) | `ccb_pytorch` | `baseline` | 4 | 0.000 | 0.000 |
| [pytorch_opus_20260205_204033](runs/pytorch_opus_20260205_204033.md) | `ccb_pytorch` | `sourcegraph_base` | 12 | 0.080 | 0.083 |
| [pytorch_opus_20260205_204033](runs/pytorch_opus_20260205_204033.md) | `ccb_pytorch` | `sourcegraph_full` | 8 | 0.120 | 0.125 |
| [refactor_haiku_20260228_210652](runs/refactor_haiku_20260228_210652.md) | `csb_sdlc_refactor` | `baseline-local-direct` | 1 | 0.750 | 1.000 |
| [refactor_haiku_20260228_210652](runs/refactor_haiku_20260228_210652.md) | `csb_sdlc_refactor` | `mcp-remote-direct` | 1 | 0.790 | 1.000 |
| [refactor_haiku_20260228_231037](runs/refactor_haiku_20260228_231037.md) | `csb_sdlc_refactor` | `mcp-remote-direct` | 4 | 0.592 | 1.000 |
| [refactor_haiku_20260228_231045](runs/refactor_haiku_20260228_231045.md) | `csb_sdlc_refactor` | `baseline-local-direct` | 4 | 0.463 | 1.000 |
| [refactor_haiku_20260301_010758](runs/refactor_haiku_20260301_010758.md) | `csb_sdlc_refactor` | `baseline-local-direct` | 16 | 0.758 | 0.938 |
| [refactor_haiku_20260301_010758](runs/refactor_haiku_20260301_010758.md) | `csb_sdlc_refactor` | `mcp-remote-direct` | 20 | 0.737 | 0.950 |
| [refactor_haiku_20260301_023530](runs/refactor_haiku_20260301_023530.md) | `csb_sdlc_refactor` | `baseline-local-direct` | 10 | 0.950 | 1.000 |
| [refactor_haiku_20260301_023530](runs/refactor_haiku_20260301_023530.md) | `csb_sdlc_refactor` | `mcp-remote-direct` | 10 | 0.717 | 0.900 |
| [refactor_haiku_20260301_031849](runs/refactor_haiku_20260301_031849.md) | `csb_sdlc_refactor` | `baseline-local-direct` | 16 | 0.701 | 1.000 |
| [refactor_haiku_20260301_031849](runs/refactor_haiku_20260301_031849.md) | `csb_sdlc_refactor` | `mcp-remote-direct` | 20 | 0.671 | 1.000 |
| [refactor_haiku_20260301_071230](runs/refactor_haiku_20260301_071230.md) | `csb_sdlc_refactor` | `baseline-local-direct` | 16 | 0.768 | 0.938 |
| [refactor_haiku_20260301_071230](runs/refactor_haiku_20260301_071230.md) | `csb_sdlc_refactor` | `mcp-remote-direct` | 19 | 0.713 | 1.000 |
| [sdlc_rep_opus_20260218_035119](runs/sdlc_rep_opus_20260218_035119.md) | `ccb_sdlc_representative` | `sourcegraph_full` | 5 | 0.590 | 0.800 |
| [sdlc_rep_opus_20260218_152638](runs/sdlc_rep_opus_20260218_152638.md) | `ccb_sdlc_representative` | `baseline` | 8 | 0.098 | 0.125 |
| [sdlc_rep_opus_20260218_152638](runs/sdlc_rep_opus_20260218_152638.md) | `ccb_sdlc_representative` | `sourcegraph_full` | 8 | 0.227 | 0.250 |
| [secure_haiku_20260223_232545](runs/secure_haiku_20260223_232545.md) | `csb_sdlc_secure` | `baseline-local-direct` | 12 | 0.597 | 0.917 |
| [secure_haiku_20260223_232545](runs/secure_haiku_20260223_232545.md) | `csb_sdlc_secure` | `mcp-remote-direct` | 18 | 0.705 | 1.000 |
| [secure_haiku_20260224_011825](runs/secure_haiku_20260224_011825.md) | `csb_sdlc_secure` | `mcp-remote-direct` | 2 | 0.500 | 0.500 |
| [secure_haiku_20260301_031850](runs/secure_haiku_20260301_031850.md) | `csb_sdlc_secure` | `baseline-local-direct` | 12 | 0.714 | 0.917 |
| [secure_haiku_20260301_031850](runs/secure_haiku_20260301_031850.md) | `csb_sdlc_secure` | `mcp-remote-direct` | 20 | 0.728 | 1.000 |
| [secure_haiku_20260301_071231](runs/secure_haiku_20260301_071231.md) | `csb_sdlc_secure` | `baseline-local-direct` | 12 | 0.667 | 1.000 |
| [secure_haiku_20260301_071231](runs/secure_haiku_20260301_071231.md) | `csb_sdlc_secure` | `mcp-remote-direct` | 20 | 0.767 | 1.000 |
| [swebenchpro_selected_opus_20260202_024115](runs/swebenchpro_selected_opus_20260202_024115.md) | `ccb_swebenchpro` | `baseline` | 9 | 0.667 | 0.667 |
| [swebenchpro_selected_opus_20260203_160607](runs/swebenchpro_selected_opus_20260203_160607.md) | `ccb_swebenchpro` | `sourcegraph_base` | 17 | 0.412 | 0.412 |
| [swebenchpro_selected_opus_20260204_191918](runs/swebenchpro_selected_opus_20260204_191918.md) | `ccb_swebenchpro` | `sourcegraph_base` | 8 | 0.875 | 0.875 |
| [swebenchpro_selected_opus_20260204_191937](runs/swebenchpro_selected_opus_20260204_191937.md) | `ccb_swebenchpro` | `sourcegraph_full` | 6 | 0.833 | 0.833 |
| [swebenchpro_selected_opus_20260207_032046](runs/swebenchpro_selected_opus_20260207_032046.md) | `ccb_swebenchpro` | `sourcegraph` | 1 | 0.000 | 0.000 |
| [sweperf_opus_20260203_160835](runs/sweperf_opus_20260203_160835.md) | `ccb_sweperf` | `baseline` | 3 | 0.000 | 0.000 |
| [sweperf_opus_20260203_160835](runs/sweperf_opus_20260203_160835.md) | `ccb_sweperf` | `sourcegraph_base` | 3 | 0.000 | 0.000 |
| [sweperf_opus_20260203_224544__duplicate](runs/sweperf_opus_20260203_224544__duplicate.md) | `ccb_sweperf` | `sourcegraph_base` | 1 | 0.000 | 0.000 |
| [tac_opus_20260203_160607](runs/tac_opus_20260203_160607.md) | `ccb_tac` | `baseline` | 8 | 0.000 | 0.000 |
| [tac_opus_20260203_221123__python_default_bug](runs/tac_opus_20260203_221123__python_default_bug.md) | `ccb_tac` | `sourcegraph_base` | 6 | 0.000 | 0.000 |
| [tac_opus_20260204_190539](runs/tac_opus_20260204_190539.md) | `ccb_tac` | `sourcegraph_full` | 2 | 0.000 | 0.000 |
| [tac_opus_20260205_010555__python_default_bug](runs/tac_opus_20260205_010555__python_default_bug.md) | `ccb_tac` | `baseline` | 6 | 0.000 | 0.000 |
| [test_haiku_20260223_235732](runs/test_haiku_20260223_235732.md) | `csb_sdlc_test` | `mcp-remote-direct` | 4 | 0.250 | 0.500 |
| [test_haiku_20260224_011816](runs/test_haiku_20260224_011816.md) | `csb_sdlc_test` | `baseline-local-direct` | 11 | 0.295 | 0.545 |
| [test_haiku_20260224_011816](runs/test_haiku_20260224_011816.md) | `csb_sdlc_test` | `mcp-remote-direct` | 8 | 0.360 | 0.625 |
| [test_haiku_20260228_230654](runs/test_haiku_20260228_230654.md) | `csb_sdlc_test` | `mcp-remote-direct` | 1 | 0.000 | 0.000 |
| [test_haiku_20260228_231039](runs/test_haiku_20260228_231039.md) | `csb_sdlc_test` | `mcp-remote-direct` | 1 | 0.200 | 1.000 |
| [test_haiku_20260301_031851](runs/test_haiku_20260301_031851.md) | `csb_sdlc_test` | `baseline-local-direct` | 15 | 0.647 | 0.933 |
| [test_haiku_20260301_031851](runs/test_haiku_20260301_031851.md) | `csb_sdlc_test` | `mcp-remote-direct` | 8 | 0.769 | 1.000 |
| [test_haiku_20260301_071232](runs/test_haiku_20260301_071232.md) | `csb_sdlc_test` | `baseline-local-direct` | 15 | 0.645 | 0.933 |
| [test_haiku_20260301_071232](runs/test_haiku_20260301_071232.md) | `csb_sdlc_test` | `mcp-remote-direct` | 8 | 0.780 | 1.000 |
| [test_haiku_20260301_192246](runs/test_haiku_20260301_192246.md) | `csb_sdlc_test` | `baseline-local-direct` | 4 | 0.128 | 0.250 |
| [test_haiku_20260301_192246](runs/test_haiku_20260301_192246.md) | `csb_sdlc_test` | `mcp-remote-direct` | 3 | 0.000 | 0.000 |
| [test_sonnet_20260219_032202](runs/test_sonnet_20260219_032202.md) | `csb_sdlc_test` | `sourcegraph_full` | 13 | 0.592 | 0.692 |
| [test_sonnet_20260219_032207](runs/test_sonnet_20260219_032207.md) | `csb_sdlc_test` | `sourcegraph_full` | 13 | 0.641 | 0.769 |
| [understand_haiku_20260224_001815](runs/understand_haiku_20260224_001815.md) | `csb_sdlc_understand` | `baseline-local-direct` | 10 | 0.309 | 0.500 |
| [understand_haiku_20260224_001815](runs/understand_haiku_20260224_001815.md) | `csb_sdlc_understand` | `mcp-remote-direct` | 20 | 0.679 | 0.850 |
| [understand_haiku_20260225_211346](runs/understand_haiku_20260225_211346.md) | `csb_sdlc_understand` | `baseline-local-direct` | 3 | 0.747 | 1.000 |
| [understand_haiku_20260225_211346](runs/understand_haiku_20260225_211346.md) | `csb_sdlc_understand` | `mcp-remote-direct` | 7 | 0.870 | 1.000 |
| [understand_haiku_20260226_232745](runs/understand_haiku_20260226_232745.md) | `csb_sdlc_understand` | `baseline-local-direct` | 4 | 1.000 | 1.000 |
| [understand_haiku_20260226_232745](runs/understand_haiku_20260226_232745.md) | `csb_sdlc_understand` | `mcp-remote-direct` | 3 | 1.000 | 1.000 |
| [understand_haiku_20260301_031852](runs/understand_haiku_20260301_031852.md) | `csb_sdlc_understand` | `baseline-local-direct` | 10 | 0.649 | 0.800 |
| [understand_haiku_20260301_031852](runs/understand_haiku_20260301_031852.md) | `csb_sdlc_understand` | `mcp-remote-direct` | 20 | 0.832 | 0.950 |
| [understand_haiku_20260301_071233](runs/understand_haiku_20260301_071233.md) | `csb_sdlc_understand` | `baseline-local-direct` | 10 | 0.874 | 1.000 |
| [understand_haiku_20260301_071233](runs/understand_haiku_20260301_071233.md) | `csb_sdlc_understand` | `mcp-remote-direct` | 32 | 0.900 | 1.000 |
| [understand_opus_20260218_031653](runs/understand_opus_20260218_031653.md) | `csb_sdlc_understand` | `baseline-local-direct` | 1 | 0.890 | 1.000 |
| [understand_opus_20260218_031653](runs/understand_opus_20260218_031653.md) | `csb_sdlc_understand` | `sourcegraph_full` | 1 | 0.830 | 1.000 |
| [understand_opus_20260218_033108](runs/understand_opus_20260218_033108.md) | `csb_sdlc_understand` | `baseline-local-direct` | 1 | 0.830 | 1.000 |
| [understand_opus_20260218_033108](runs/understand_opus_20260218_033108.md) | `csb_sdlc_understand` | `sourcegraph_full` | 1 | 0.830 | 1.000 |
| [understand_opus_20260218_034822](runs/understand_opus_20260218_034822.md) | `csb_sdlc_understand` | `baseline-local-direct` | 1 | 1.000 | 1.000 |
| [understand_opus_20260218_034822](runs/understand_opus_20260218_034822.md) | `csb_sdlc_understand` | `sourcegraph_full` | 1 | 1.000 | 1.000 |

</details>

`index.html`, `data/official_results.json`, and `audits/*.json` provide GitHub-auditable artifacts.