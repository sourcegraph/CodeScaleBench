# Script Index

Generated from `scripts/registry.json` by `scripts/generate_script_index.py`.

## When To Read This
- You need to find the right script without opening many files.
- You need to identify maintained vs one-off scripts.

## Do Not Read First If
- You already know the workflow: use `docs/START_HERE_BY_TASK.md` first.
- You are working in a single script and only need that file.

## Usage
- Filter by category first, then open the specific script.
- Treat `one_off` scripts as historical unless explicitly needed.

## Core Operations

- `scripts/aggregate_status.py` - Scans run directories, classifies task status, and supports watch mode for active runs.
- `scripts/check_infra.py` - Pre-run infrastructure readiness checker (tokens, Docker, disk, Harbor CLI).
- `scripts/docs_consistency_check.py` - Validates documentation references, agent-guide sync/size budgets, and generated navigation artifacts.
- `scripts/generate_eval_report.py` - Builds the deterministic aggregate evaluation report for completed runs.
- `scripts/generate_manifest.py` - Rebuilds `MANIFEST.json` from on-disk run results.
- `scripts/generate_script_index.py` - Generates `docs/ops/SCRIPT_INDEX.md` from `scripts/registry.json`.
- `scripts/generate_script_registry.py` - Generates `scripts/registry.json`, the machine-readable script inventory used for agent navigation.
- `scripts/refresh_agent_navigation.py` - One-command refresh/check for generated agent-navigation artifacts (guides + script registry/index).
- `scripts/repo_health.py` - Repo health gate that runs required pre-commit/push checks (docs drift, selection file, task preflight).
- `scripts/status_fingerprints.py` - Known failure regex fingerprints used by status/triage tooling.
- `scripts/sync_agent_guides.py` - Syncs generated root/local `AGENTS.md` and `CLAUDE.md` files from canonical sources in `docs/ops/`.
- `scripts/validate_task_run.py` - Post-run validation for a run/task output directory (`result.json`, scoring, anomalies).
- `scripts/validate_tasks_preflight.py` - Pre-flight task validator (static checks plus optional no-agent runtime smoke).

## Analysis & Comparison

- `scripts/analyze_harness_design.py` - Analysis/comparison script for analyze harness design.
- `scripts/analyze_mcp_unique_haiku.py` - Analysis/comparison script for analyze mcp unique haiku.
- `scripts/analyze_minimum_subset.py` - Analysis/comparison script for analyze minimum subset.
- `scripts/analyze_paired_cost_official_raw.py` - Analysis/comparison script for analyze paired cost official raw.
- `scripts/analyze_rq_power.py` - Analysis/comparison script for analyze rq power.
- `scripts/analyze_run_coverage.py` - Analysis/comparison script for analyze run coverage.
- `scripts/analyze_size_effects.py` - Analysis/comparison script for analyze size effects.
- `scripts/audit_traces.py` - Analysis/comparison script for audit traces.
- `scripts/compare_configs.py` - Compares benchmark outcomes across configs on matched task sets.
- `scripts/comprehensive_analysis.py` - Analysis/comparison script for comprehensive analysis.
- `scripts/compute_retrieval_metrics.py` - Analysis/comparison script for compute retrieval metrics.
- `scripts/cost_breakdown_analysis.py` - Analysis/comparison script for cost breakdown analysis.
- `scripts/cost_report.py` - Aggregates token and cost metrics per run, suite, and config.
- `scripts/doe_variance_analysis.py` - Analysis/comparison script for doe variance analysis.
- `scripts/ds_audit.py` - Analysis/comparison script for ds audit.
- `scripts/economic_analysis.py` - Analysis/comparison script for economic analysis.
- `scripts/failure_analysis.py` - Analysis/comparison script for failure analysis.
- `scripts/ir_analysis.py` - Runs retrieval/IR analysis over normalized events and evaluation outputs.
- `scripts/mcp_audit.py` - Audits MCP tool usage patterns and reward/time deltas across runs.
- `scripts/mcp_cost_analysis.py` - Analysis/comparison script for mcp cost analysis.
- `scripts/normalize_retrieval_events.py` - Analysis/comparison script for normalize retrieval events.
- `scripts/oracle_ir_analysis.py` - Analysis/comparison script for oracle ir analysis.
- `scripts/oracle_retrieval_analysis.py` - Analysis/comparison script for oracle retrieval analysis.
- `scripts/reliability_analysis.py` - Analysis/comparison script for reliability analysis.
- `scripts/retrieval_eval_pipeline.py` - Analysis/comparison script for retrieval eval pipeline.
- `scripts/retrieval_impact_analysis.py` - Analysis/comparison script for retrieval impact analysis.
- `scripts/suite_power_analysis.py` - Analysis/comparison script for suite power analysis.
- `scripts/variance_gap_analysis.py` - Analysis/comparison script for variance gap analysis.

## QA & Quality

- `scripts/abc_audit.py` - QA/validation script for abc audit.
- `scripts/abc_criteria.py` - QA/validation script for abc criteria.
- `scripts/abc_score_task.py` - QA/validation script for abc score task.
- `scripts/governance_evaluator.py` - QA/validation script for governance evaluator.
- `scripts/official_integrity.py` - QA/validation script for official integrity.
- `scripts/official_runs.py` - QA/validation script for official runs.
- `scripts/quarantine_invalid_tasks.py` - QA/validation script for quarantine invalid tasks.
- `scripts/validate_artifact_golden.py` - QA/validation script for validate artifact golden.
- `scripts/validate_official_integrity.py` - QA/validation script for validate official integrity.
- `scripts/validate_org_task_instance.py` - QA/validation script for validate org task instance.

## Data Management

- `scripts/archive_non_manifest_runs.py` - Data/run management script for archive non manifest runs.
- `scripts/archive_run.py` - Data/run management script for archive run.
- `scripts/consolidate_staging.py` - Data/run management script for consolidate staging.
- `scripts/extract_task_metrics.py` - Data/run management script for extract task metrics.
- `scripts/migrate_results.py` - Data/run management script for migrate results.
- `scripts/organize_staging_to_official.py` - Data/run management script for organize staging to official.
- `scripts/promote_run.py` - Promotes a staged run into the official results flow with integrity checks.
- `scripts/reextract_all_metrics.py` - Data/run management script for reextract all metrics.
- `scripts/rerun_failed.py` - Generates targeted rerun commands for failed tasks (despite `rerun_` prefix, this is part of normal ops).
- `scripts/sync_task_metadata.py` - Reconciles `task.toml` metadata with the canonical task selection registry (`--fix` to apply changes).

## Submission & Reporting

- `scripts/generate_comprehensive_report.py` - Submission/reporting script for generate comprehensive report.
- `scripts/generate_enterprise_report.py` - Submission/reporting script for generate enterprise report.
- `scripts/generate_leaderboard.py` - Submission/reporting script for generate leaderboard.
- `scripts/generate_retrieval_report.py` - Submission/reporting script for generate retrieval report.
- `scripts/ingest_judge_results.py` - Submission/reporting script for ingest judge results.
- `scripts/package_submission.py` - Submission/reporting script for package submission.
- `scripts/validate_submission.py` - Submission/reporting script for validate submission.

## Task Creation & Selection

- `scripts/curate_oracle.py` - Task creation/selection script for curate oracle.
- `scripts/customize_mcp_skeletons.py` - Task creation/selection script for customize mcp skeletons.
- `scripts/generate_csb_org_tasks.py` - Task creation/selection script for generate csb org tasks.
- `scripts/generate_dependeval_tasks.py` - Task creation/selection script for generate dependeval tasks.
- `scripts/generate_pytorch_expected_diffs.py` - Task creation/selection script for generate pytorch expected diffs.
- `scripts/materialize_dependeval_repos.py` - Task creation/selection script for materialize dependeval repos.
- `scripts/materialize_sdlc_suites.py` - Task creation/selection script for materialize sdlc suites.
- `scripts/mine_bug_tasks.py` - Task creation/selection script for mine bug tasks.
- `scripts/register_new_org_tasks.py` - Task creation/selection script for register new org tasks.
- `scripts/rename_tasks.py` - Task creation/selection script for rename tasks.
- `scripts/select_benchmark_tasks.py` - Task creation/selection script for select benchmark tasks.
- `scripts/select_dependeval_tasks.py` - Task creation/selection script for select dependeval tasks.
- `scripts/select_subset.py` - Selects a representative task subset stratified by suite effect-size bucket, language, difficulty, and codebase size. Outputs JSON selection file and plain-text task list.

## Infra & Mirrors

- `scripts/build_conversation_db.py` - Infrastructure or mirror management script for build conversation db.
- `scripts/build_core_manifest.py` - Infrastructure or mirror management script for build core manifest.
- `scripts/build_daytona_registry.py` - Infrastructure or mirror management script for build daytona registry.
- `scripts/build_linux_base_images.sh` - Infrastructure or mirror management script for build linux base images.
- `scripts/build_unified_manifest.py` - Infrastructure or mirror management script for build unified manifest.
- `scripts/create_mcp_expansion_mirrors.sh` - Infrastructure or mirror management script for create mcp expansion mirrors.
- `scripts/create_missing_mcp_mirrors.sh` - Infrastructure or mirror management script for create missing mcp mirrors.
- `scripts/create_scip_branches.sh` - Infrastructure or mirror management script for create scip branches.
- `scripts/create_sg_benchmark_repos.sh` - Infrastructure or mirror management script for create sg benchmark repos.
- `scripts/create_sg_mirrors.py` - Infrastructure or mirror management script for create sg mirrors.
- `scripts/create_sg_tac_repos.sh` - Infrastructure or mirror management script for create sg tac repos.
- `scripts/headless_login.py` - Infrastructure or mirror management script for headless login.
- `scripts/inject_sg_repo_env.py` - Infrastructure or mirror management script for inject sg repo env.
- `scripts/monitor_and_queue.sh` - Infrastructure or mirror management script for monitor and queue.
- `scripts/prebuild_images.sh` - Infrastructure or mirror management script for prebuild images.
- `scripts/prebuild_with_credentials.sh` - Infrastructure or mirror management script for prebuild with credentials.
- `scripts/stop_task.sh` - Infrastructure or mirror management script for stop task.
- `scripts/swap_default_branch.sh` - Infrastructure or mirror management script for swap default branch.
- `scripts/sync_oracle_files.py` - Infrastructure or mirror management script for sync oracle files.
- `scripts/sync_pytorch_verifiers.sh` - Infrastructure or mirror management script for sync pytorch verifiers.
- `scripts/update_gt_registry.py` - Infrastructure or mirror management script for update gt registry.
- `scripts/update_loc_from_cloc.py` - Infrastructure or mirror management script for update loc from cloc.
- `scripts/update_sg_only_mirrors.py` - Infrastructure or mirror management script for update sg only mirrors.

## Library / Helpers

- `scripts/answer_json_verifier_lib.sh` - Helper library/wrapper used by other scripts (answer json verifier lib).
- `scripts/artifact_verifier_lib.sh` - Helper library/wrapper used by other scripts (artifact verifier lib).
- `scripts/config_utils.py` - Helper library/wrapper used by other scripts (config utils).
- `scripts/eval_matrix.py` - Helper library/wrapper used by other scripts (eval matrix).
- `scripts/sgonly_verifier_wrapper.sh` - Helper library/wrapper used by other scripts (sgonly verifier wrapper).
- `scripts/workflow_metrics.py` - Helper library/wrapper used by other scripts (workflow metrics).
- `scripts/workflow_taxonomy.py` - Helper library/wrapper used by other scripts (workflow taxonomy).

## Validation

- `scripts/validate_core_manifest.py` - Validation script for validate core manifest.
- `scripts/validate_enterprise_readiness.py` - Validation script for validate enterprise readiness.
- `scripts/validate_on_contextbench.py` - Validation script for validate on contextbench.

## Generation

- `scripts/generate_artifact_dockerfiles.py` - Generation script for generate artifact dockerfiles.
- `scripts/generate_artifact_only_dockerfiles.py` - Generation script for generate artifact only dockerfiles.
- `scripts/generate_coverage_gap_configs.py` - Generation script for generate coverage gap configs.
- `scripts/generate_instruction_mcp.py` - Generation script for generate instruction mcp.
- `scripts/generate_promoted_verifiers.py` - Generation script for generate promoted verifiers.
- `scripts/generate_repoqa_largerepo_tasks.py` - Generation script for generate repoqa largerepo tasks.
- `scripts/generate_sgonly_dockerfiles.py` - Generation script for generate sgonly dockerfiles.
- `scripts/generate_start_here_by_task.py` - Generation script for generate start here by task.
- `scripts/generate_verifier_labels.py` - Generation script for generate verifier labels.

## Migration

- `scripts/migrate_dockerfiles_clone_as_claude.py` - Migration script for migrate dockerfiles clone as claude.
- `scripts/migrate_dockerfiles_to_mirrors.py` - Migration script for migrate dockerfiles to mirrors.
- `scripts/migrate_to_sg_evals.sh` - Migration script for migrate to sg evals.
- `scripts/migrate_to_sg_evals_batch2.sh` - Migration script for migrate to sg evals batch2.

## Misc

- `scripts/add_verification_metadata.py` - Utility script for add verification metadata.
- `scripts/audit_gt_coverage.py` - Utility script for audit gt coverage.
- `scripts/audit_official_scores.py` - Utility script for audit official scores.
- `scripts/audit_unpinned_repos.py` - Utility script for audit unpinned repos.
- `scripts/audit_v2_report_data.py` - Utility script for audit v2 report data.
- `scripts/backfill_instruction_artifacts.py` [one_off] - Historical one-off script: backfill instruction artifacts.
- `scripts/backfill_reviewers.py` [one_off] - Historical one-off script: backfill reviewers.
- `scripts/backfill_size_metadata.py` [one_off] - Historical one-off script: backfill size metadata.
- `scripts/backfill_triage_from_manifest.py` [one_off] - Historical one-off script: backfill triage from manifest.
- `scripts/check_harness_readiness.py` - Utility script for check harness readiness.
- `scripts/collect_repo_cloc.py` - Utility script for collect repo cloc.
- `scripts/compare_contextbench_results.py` - Utility script for compare contextbench results.
- `scripts/compare_old_new_ground_truth.py` - Utility script for compare old new ground truth.
- `scripts/compute_analysis_ir_metrics.py` - Utility script for compute analysis ir metrics.
- `scripts/compute_bootstrap_cis.py` - Utility script for compute bootstrap cis.
- `scripts/context_retrieval_agent.py` - Utility script for context retrieval agent.
- `scripts/control_plane.py` - Utility script for control plane.
- `scripts/convert_harbor_to_contextbench.py` - Utility script for convert harbor to contextbench.
- `scripts/cross_validate_gt.py` - Utility script for cross validate gt.
- `scripts/cross_validate_oracles.py` - Utility script for cross validate oracles.
- `scripts/daytona_cost_guard.py` - Utility script for daytona cost guard.
- `scripts/daytona_curator_runner.py` - Utility script for daytona curator runner.
- `scripts/daytona_poc_runner.py` - Utility script for daytona poc runner.
- `scripts/daytona_runner.py` - Utility script for daytona runner.
- `scripts/daytona_snapshot_cleanup.py` - Utility script for daytona snapshot cleanup.
- `scripts/dependeval_eval_dr.py` - Utility script for dependeval eval dr.
- `scripts/dependeval_eval_me.py` - Utility script for dependeval eval me.
- `scripts/derive_n_repos.py` - Utility script for derive n repos.
- `scripts/docgen_quality_sweep.py` - Utility script for docgen quality sweep.
- `scripts/doe_power_curves.py` - Utility script for doe power curves.
- `scripts/doe_select_tasks.py` - Utility script for doe select tasks.
- `scripts/ds_hybrid_retrieval.py` - Utility script for ds hybrid retrieval.
- `scripts/ds_wrapper.sh` - Utility script for ds wrapper.
- `scripts/export_conversation_blog_assets.py` - Utility script for export conversation blog assets.
- `scripts/export_engineering_diary_assets.py` - Utility script for export engineering diary assets.
- `scripts/export_official_results.py` - Utility script for export official results.
- `scripts/extract_analysis_metrics.py` - Utility script for extract analysis metrics.
- `scripts/extract_build_diary.py` - Utility script for extract build diary.
- `scripts/extract_build_narrative.py` - Utility script for extract build narrative.
- `scripts/extract_v2_report_data.py` - Utility script for extract v2 report data.
- `scripts/find_mcp_distracted.py` - Utility script for find mcp distracted.
- `scripts/fix_h3_tokens.py` [one_off] - Historical one-off script: fix h3 tokens.
- `scripts/fix_workspace_perms.py` [one_off] - Historical one-off script: fix workspace perms.
- `scripts/handoff_monitor_scrollend.sh` - Utility script for handoff monitor scrollend.
- `scripts/hybrid_retrieval_pipeline.py` - Utility script for hybrid retrieval pipeline.
- `scripts/hydrate_task_specs.py` - Utility script for hydrate task specs.
- `scripts/icp_profiles.py` - Utility script for icp profiles.
- `scripts/integrate_answer_json_wave1.py` - Utility script for integrate answer json wave1.
- `scripts/integrate_answer_json_wave2.py` - Utility script for integrate answer json wave2.
- `scripts/integrate_answer_json_wave3.py` - Utility script for integrate answer json wave3.
- `scripts/judge_demo.py` - Utility script for judge demo.
- `scripts/list_gemini_models.py` - Utility script for list gemini models.
- `scripts/mirror_largerepo_expansion.sh` - Utility script for mirror largerepo expansion.
- `scripts/organize_official_by_model.py` - Utility script for organize official by model.
- `scripts/plan_variance_runs.py` - Utility script for plan variance runs.
- `scripts/plot_build_diary.py` - Utility script for plot build diary.
- `scripts/plot_build_diary_supplementary.py` - Utility script for plot build diary supplementary.
- `scripts/plot_build_narrative.py` - Utility script for plot build narrative.
- `scripts/plot_conversation_blog_svgs.py` - Utility script for plot conversation blog svgs.
- `scripts/plot_csb_mcp_blog_figures.py` - Utility script for plot csb mcp blog figures.
- `scripts/prepare_analysis_runs.py` - Utility script for prepare analysis runs.
- `scripts/promote_agent_oracles.py` - Utility script for promote agent oracles.
- `scripts/promote_blocked.py` - Utility script for promote blocked.
- `scripts/promoted_verifier.py` - Utility script for promoted verifier.
- `scripts/push_base_images_ghcr.sh` - Utility script for push base images ghcr.
- `scripts/regenerate_artifact_dockerfiles.py` - Utility script for regenerate artifact dockerfiles.
- `scripts/rehost_sweap_images.py` - Utility script for rehost sweap images.
- `scripts/remirror_org_repos.sh` - Utility script for remirror org repos.
- `scripts/rename_project.py` - Utility script for rename project.
- `scripts/repair_h3_trajectories.py` [one_off] - Historical one-off script: repair h3 trajectories.
- `scripts/rerun_crossrepo_2tasks.sh` [one_off] - Historical one-off script: rerun crossrepo 2tasks.
- `scripts/rerun_crossrepo_all4.sh` [one_off] - Historical one-off script: rerun crossrepo all4.
- `scripts/rerun_crossrepo_fixed.sh` [one_off] - Historical one-off script: rerun crossrepo fixed.
- `scripts/rerun_errored_tasks.sh` [one_off] - Historical one-off script: rerun errored tasks.
- `scripts/rerun_fixed_tasks.sh` [one_off] - Historical one-off script: rerun fixed tasks.
- `scripts/rerun_zero_mcp_tasks.sh` [one_off] - Historical one-off script: rerun zero mcp tasks.
- `scripts/rescore_difficulty.py` - Utility script for rescore difficulty.
- `scripts/run_judge.py` - Utility script for run judge.
- `scripts/run_missing_oracles.sh` - Utility script for run missing oracles.
- `scripts/run_scaling_gap_oracles.sh` - Utility script for run scaling gap oracles.
- `scripts/run_sg_local.sh` - Utility script for run sg local.
- `scripts/run_sg_validation.py` - Utility script for run sg validation.
- `scripts/scaffold_contextbench_tasks.py` - Utility script for scaffold contextbench tasks.
- `scripts/scaffold_feature_tasks.py` - Utility script for scaffold feature tasks.
- `scripts/scaffold_refactor_tasks.py` - Utility script for scaffold refactor tasks.
- `scripts/scaffold_scaling_gap_sdlc_tasks.py` - Utility script for scaffold scaling gap sdlc tasks.
- `scripts/scaffold_swebench_pro_tasks.py` - Utility script for scaffold swebench pro tasks.
- `scripts/scaffold_task_expansion_wave1.py` - Utility script for scaffold task expansion wave1.
- `scripts/scan_swebench_errors.py` - Utility script for scan swebench errors.
- `scripts/sdlc_anomaly_scan.py` - Utility script for sdlc anomaly scan.
- `scripts/select_contextbench_pilot.py` - Utility script for select contextbench pilot.
- `scripts/smoke_artifact_verifier.py` - Utility script for smoke artifact verifier.
- `scripts/smoke_test_tasks.py` - Utility script for smoke test tasks.
- `scripts/verify_oracle_fail2pass.py` - Utility script for verify oracle fail2pass.
- `scripts/verify_retrieval_eval_smoke.py` - Utility script for verify retrieval eval smoke.

## Regeneration
```bash
python3 scripts/generate_script_registry.py
python3 scripts/generate_script_index.py
```
