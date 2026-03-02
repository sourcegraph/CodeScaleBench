# ccb_feature

## Run/Config Summary

| Run | Config | Valid Tasks | Mean Reward | Pass Rate |
|---|---|---:|---:|---:|
| [ccb_feature_haiku_20260301_212230](../runs/ccb_feature_haiku_20260301_212230.md) | `mcp-remote-direct` | 3 | 0.500 | 0.667 |
| [ccb_feature_haiku_20260301_230003](../runs/ccb_feature_haiku_20260301_230003.md) | `baseline-local-direct` | 1 | 0.100 | 1.000 |
| [ccb_feature_haiku_20260301_230003](../runs/ccb_feature_haiku_20260301_230003.md) | `mcp-remote-direct` | 4 | 0.407 | 0.750 |
| [ccb_feature_haiku_20260302_004743](../runs/ccb_feature_haiku_20260302_004743.md) | `mcp-remote-direct` | 3 | 0.500 | 0.667 |
| [ccb_feature_haiku_20260302_005828](../runs/ccb_feature_haiku_20260302_005828.md) | `baseline-local-direct` | 2 | 0.333 | 1.000 |
| [ccb_feature_haiku_20260302_005828](../runs/ccb_feature_haiku_20260302_005828.md) | `mcp-remote-direct` | 3 | 0.500 | 0.667 |
| [ccb_feature_haiku_20260302_005948](../runs/ccb_feature_haiku_20260302_005948.md) | `mcp-remote-direct` | 1 | 0.140 | 1.000 |
| [ccb_feature_haiku_20260302_022544](../runs/ccb_feature_haiku_20260302_022544.md) | `baseline-local-direct` | 1 | 0.000 | 0.000 |
| [feature_haiku_20260228_220733](../runs/feature_haiku_20260228_220733.md) | `mcp-remote-direct` | 1 | 0.000 | 0.000 |
| [feature_haiku_20260301_071229](../runs/feature_haiku_20260301_071229.md) | `baseline-local-direct` | 19 | 0.685 | 0.895 |
| [feature_haiku_20260301_071229](../runs/feature_haiku_20260301_071229.md) | `mcp-remote-direct` | 19 | 0.608 | 0.895 |

## Tasks

| Task | Benchmark | Config | Status | Reward | Runs | MCP Ratio |
|---|---|---|---|---:|---:|---:|
| [bustub-hyperloglog-impl-001](../tasks/feature_haiku_20260301_071229--baseline-local-direct--bustub-hyperloglog-impl-001.html) | [source](../../../benchmarks/ccb_feature/bustub-hyperloglog-impl-001) | `baseline-local-direct` | `failed` | 0.000 | 3 | 0.000 |
| [sgonly_bustub-hyperloglog-impl-001](../tasks/feature_haiku_20260301_071229--mcp-remote-direct--sgonly_bustub-hyperloglog-impl-001.html) | [source](../../../benchmarks/ccb_feature/bustub-hyperloglog-impl-001) | `mcp-remote-direct` | `passed` | 0.167 | 4 | 0.165 |
| [camel-fix-protocol-feat-001](../tasks/feature_haiku_20260301_071229--baseline-local-direct--camel-fix-protocol-feat-001.html) | [source](../../../benchmarks/ccb_feature/camel-fix-protocol-feat-001) | `baseline-local-direct` | `passed` | 0.330 | 4 | 0.000 |
| [sgonly_camel-fix-protocol-feat-001](../tasks/feature_haiku_20260301_071229--mcp-remote-direct--sgonly_camel-fix-protocol-feat-001.html) | [source](../../../benchmarks/ccb_feature/camel-fix-protocol-feat-001) | `mcp-remote-direct` | `passed` | 0.340 | 5 | 0.605 |
| [cilium-policy-audit-logger-feat-001](../tasks/feature_haiku_20260301_071229--baseline-local-direct--cilium-policy-audit-logger-feat-001.html) | [source](../../../benchmarks/ccb_feature/cilium-policy-audit-logger-feat-001) | `baseline-local-direct` | `passed` | 1.000 | 4 | 0.000 |
| [sgonly_cilium-policy-audit-logger-feat-001](../tasks/feature_haiku_20260301_071229--mcp-remote-direct--sgonly_cilium-policy-audit-logger-feat-001.html) | [source](../../../benchmarks/ccb_feature/cilium-policy-audit-logger-feat-001) | `mcp-remote-direct` | `passed` | 1.000 | 4 | 0.426 |
| [cilium-policy-quota-feat-001](../tasks/feature_haiku_20260301_071229--baseline-local-direct--cilium-policy-quota-feat-001.html) | [source](../../../benchmarks/ccb_feature/cilium-policy-quota-feat-001) | `baseline-local-direct` | `passed` | 1.000 | 4 | 0.000 |
| [sgonly_cilium-policy-quota-feat-001](../tasks/feature_haiku_20260301_071229--mcp-remote-direct--sgonly_cilium-policy-quota-feat-001.html) | [source](../../../benchmarks/ccb_feature/cilium-policy-quota-feat-001) | `mcp-remote-direct` | `passed` | 1.000 | 4 | 0.361 |
| [curl-http3-priority-feat-001](../tasks/feature_haiku_20260301_071229--baseline-local-direct--curl-http3-priority-feat-001.html) | [source](../../../benchmarks/ccb_feature/curl-http3-priority-feat-001) | `baseline-local-direct` | `passed` | 0.833 | 5 | 0.000 |
| [sgonly_curl-http3-priority-feat-001](../tasks/feature_haiku_20260301_071229--mcp-remote-direct--sgonly_curl-http3-priority-feat-001.html) | [source](../../../benchmarks/ccb_feature/curl-http3-priority-feat-001) | `mcp-remote-direct` | `passed` | 0.833 | 4 | 0.266 |
| [django-rate-limit-middleware-feat-001](../tasks/feature_haiku_20260301_071229--baseline-local-direct--django-rate-limit-middleware-feat-001.html) | [source](../../../benchmarks/ccb_feature/django-rate-limit-middleware-feat-001) | `baseline-local-direct` | `passed` | 1.000 | 4 | 0.000 |
| [sgonly_django-rate-limit-middleware-feat-001](../tasks/feature_haiku_20260301_071229--mcp-remote-direct--sgonly_django-rate-limit-middleware-feat-001.html) | [source](../../../benchmarks/ccb_feature/django-rate-limit-middleware-feat-001) | `mcp-remote-direct` | `passed` | 1.000 | 3 | 0.171 |
| [envoy-custom-header-filter-feat-001](../tasks/feature_haiku_20260301_071229--baseline-local-direct--envoy-custom-header-filter-feat-001.html) | [source](../../../benchmarks/ccb_feature/envoy-custom-header-filter-feat-001) | `baseline-local-direct` | `passed` | 1.000 | 5 | 0.000 |
| [sgonly_envoy-custom-header-filter-feat-001](../tasks/feature_haiku_20260301_071229--mcp-remote-direct--sgonly_envoy-custom-header-filter-feat-001.html) | [source](../../../benchmarks/ccb_feature/envoy-custom-header-filter-feat-001) | `mcp-remote-direct` | `passed` | 1.000 | 5 | 0.510 |
| [envoy-grpc-server-impl-001](../tasks/feature_haiku_20260301_071229--baseline-local-direct--envoy-grpc-server-impl-001.html) | [source](../../../benchmarks/ccb_feature/envoy-grpc-server-impl-001) | `baseline-local-direct` | `passed` | 0.440 | 3 | 0.000 |
| [sgonly_envoy-grpc-server-impl-001](../tasks/feature_haiku_20260301_071229--mcp-remote-direct--sgonly_envoy-grpc-server-impl-001.html) | [source](../../../benchmarks/ccb_feature/envoy-grpc-server-impl-001) | `mcp-remote-direct` | `passed` | 0.500 | 3 | 0.938 |
| [flink-pricing-window-feat-001](../tasks/feature_haiku_20260301_071229--baseline-local-direct--flink-pricing-window-feat-001.html) | [source](../../../benchmarks/ccb_feature/flink-pricing-window-feat-001) | `baseline-local-direct` | `passed` | 0.480 | 4 | 0.000 |
| [sgonly_flink-pricing-window-feat-001](../tasks/feature_haiku_20260301_071229--mcp-remote-direct--sgonly_flink-pricing-window-feat-001.html) | [source](../../../benchmarks/ccb_feature/flink-pricing-window-feat-001) | `mcp-remote-direct` | `passed` | 0.380 | 4 | 0.253 |
| [k8s-noschedule-taint-feat-001](../tasks/feature_haiku_20260301_071229--baseline-local-direct--k8s-noschedule-taint-feat-001.html) | [source](../../../benchmarks/ccb_feature/k8s-noschedule-taint-feat-001) | `baseline-local-direct` | `failed` | 0.000 | 5 | 0.000 |
| [sgonly_k8s-noschedule-taint-feat-001](../tasks/feature_haiku_20260301_071229--mcp-remote-direct--sgonly_k8s-noschedule-taint-feat-001.html) | [source](../../../benchmarks/ccb_feature/k8s-noschedule-taint-feat-001) | `mcp-remote-direct` | `failed` | 0.000 | 4 | 0.441 |
| [k8s-runtime-object-impl-001](../tasks/ccb_feature_haiku_20260301_230003--baseline-local-direct--k8s-runtime-object-impl-001.html) | [source](../../../benchmarks/ccb_feature/k8s-runtime-object-impl-001) | `baseline-local-direct` | `passed` | 0.100 | 4 | 0.000 |
| [mcp_k8s-runtime-object-impl-001_dohqjj](../tasks/ccb_feature_haiku_20260302_005948--mcp-remote-direct--mcp_k8s-runtime-object-impl-001_dohqjj.html) | [source](../../../benchmarks/ccb_feature/k8s-runtime-object-impl-001) | `mcp-remote-direct` | `passed` | 0.140 | 5 | 0.704 |
| [mcp_k8s-runtime-object-impl-001_v3doff](../tasks/ccb_feature_haiku_20260301_230003--mcp-remote-direct--mcp_k8s-runtime-object-impl-001_v3doff.html) | [source](../../../benchmarks/ccb_feature/k8s-runtime-object-impl-001) | `mcp-remote-direct` | `passed` | 0.130 | 5 | 0.810 |
| [sgonly_k8s-runtime-object-impl-001](../tasks/feature_haiku_20260301_071229--mcp-remote-direct--sgonly_k8s-runtime-object-impl-001.html) | [source](../../../benchmarks/ccb_feature/k8s-runtime-object-impl-001) | `mcp-remote-direct` | `passed` | 0.130 | 5 | 0.706 |
| [numpy-rolling-median-feat-001](../tasks/feature_haiku_20260301_071229--baseline-local-direct--numpy-rolling-median-feat-001.html) | [source](../../../benchmarks/ccb_feature/numpy-rolling-median-feat-001) | `baseline-local-direct` | `passed` | 1.000 | 4 | 0.000 |
| [sgonly_numpy-rolling-median-feat-001](../tasks/feature_haiku_20260301_071229--mcp-remote-direct--sgonly_numpy-rolling-median-feat-001.html) | [source](../../../benchmarks/ccb_feature/numpy-rolling-median-feat-001) | `mcp-remote-direct` | `passed` | 1.000 | 4 | 0.379 |
| [pandas-merge-asof-indicator-feat-001](../tasks/feature_haiku_20260301_071229--baseline-local-direct--pandas-merge-asof-indicator-feat-001.html) | [source](../../../benchmarks/ccb_feature/pandas-merge-asof-indicator-feat-001) | `baseline-local-direct` | `passed` | 0.667 | 3 | 0.000 |
| [sgonly_pandas-merge-asof-indicator-feat-001](../tasks/feature_haiku_20260301_071229--mcp-remote-direct--sgonly_pandas-merge-asof-indicator-feat-001.html) | [source](../../../benchmarks/ccb_feature/pandas-merge-asof-indicator-feat-001) | `mcp-remote-direct` | `passed` | 0.667 | 4 | 0.278 |
| [postgres-copy-csv-header-feat-001](../tasks/ccb_feature_haiku_20260302_005828--baseline-local-direct--postgres-copy-csv-header-feat-001.html) | [source](../../../benchmarks/ccb_feature/postgres-copy-csv-header-feat-001) | `baseline-local-direct` | `passed` | 0.333 | 4 | 0.000 |
| [mcp_postgres-copy-csv-header-feat-001_ergdpr](../tasks/ccb_feature_haiku_20260301_230003--mcp-remote-direct--mcp_postgres-copy-csv-header-feat-001_ergdpr.html) | [source](../../../benchmarks/ccb_feature/postgres-copy-csv-header-feat-001) | `mcp-remote-direct` | `passed` | 0.500 | 4 | 0.424 |
| [mcp_postgres-copy-csv-header-feat-001_hl7ox9](../tasks/ccb_feature_haiku_20260301_212230--mcp-remote-direct--mcp_postgres-copy-csv-header-feat-001_hl7ox9.html) | [source](../../../benchmarks/ccb_feature/postgres-copy-csv-header-feat-001) | `mcp-remote-direct` | `passed` | 0.500 | 4 | 0.512 |
| [mcp_postgres-copy-csv-header-feat-001_r4p1kx](../tasks/ccb_feature_haiku_20260302_005828--mcp-remote-direct--mcp_postgres-copy-csv-header-feat-001_r4p1kx.html) | [source](../../../benchmarks/ccb_feature/postgres-copy-csv-header-feat-001) | `mcp-remote-direct` | `passed` | 0.500 | 4 | 0.253 |
| [mcp_postgres-copy-csv-header-feat-001_twvjfw](../tasks/ccb_feature_haiku_20260302_004743--mcp-remote-direct--mcp_postgres-copy-csv-header-feat-001_twvjfw.html) | [source](../../../benchmarks/ccb_feature/postgres-copy-csv-header-feat-001) | `mcp-remote-direct` | `passed` | 0.500 | 4 | 0.553 |
| [prometheus-silence-bulk-api-feat-001](../tasks/feature_haiku_20260301_071229--baseline-local-direct--prometheus-silence-bulk-api-feat-001.html) | [source](../../../benchmarks/ccb_feature/prometheus-silence-bulk-api-feat-001) | `baseline-local-direct` | `passed` | 0.833 | 3 | 0.000 |
| [sgonly_prometheus-silence-bulk-api-feat-001](../tasks/feature_haiku_20260301_071229--mcp-remote-direct--sgonly_prometheus-silence-bulk-api-feat-001.html) | [source](../../../benchmarks/ccb_feature/prometheus-silence-bulk-api-feat-001) | `mcp-remote-direct` | `passed` | 0.833 | 3 | 0.514 |
| [pytorch-gradient-noise-feat-001](../tasks/feature_haiku_20260301_071229--baseline-local-direct--pytorch-gradient-noise-feat-001.html) | [source](../../../benchmarks/ccb_feature/pytorch-gradient-noise-feat-001) | `baseline-local-direct` | `passed` | 0.833 | 3 | 0.000 |
| [sgonly_pytorch-gradient-noise-feat-001](../tasks/feature_haiku_20260301_071229--mcp-remote-direct--sgonly_pytorch-gradient-noise-feat-001.html) | [source](../../../benchmarks/ccb_feature/pytorch-gradient-noise-feat-001) | `mcp-remote-direct` | `passed` | 0.833 | 3 | 0.368 |
| [servo-css-container-query-feat-001](../tasks/ccb_feature_haiku_20260302_022544--baseline-local-direct--servo-css-container-query-feat-001.html) | [source](../../../benchmarks/ccb_feature/servo-css-container-query-feat-001) | `baseline-local-direct` | `failed` | 0.000 | 5 | 0.000 |
| [mcp_servo-css-container-query-feat-001_d2rk25](../tasks/ccb_feature_haiku_20260301_230003--mcp-remote-direct--mcp_servo-css-container-query-feat-001_d2rk25.html) | [source](../../../benchmarks/ccb_feature/servo-css-container-query-feat-001) | `mcp-remote-direct` | `failed` | 0.000 | 4 | 0.632 |
| [mcp_servo-css-container-query-feat-001_cmlod2](../tasks/ccb_feature_haiku_20260301_212230--mcp-remote-direct--mcp_servo-css-container-query-feat-001_cmlod2.html) | [source](../../../benchmarks/ccb_feature/servo-css-container-query-feat-001) | `mcp-remote-direct` | `failed` | 0.000 | 4 | 0.128 |
| [mcp_servo-css-container-query-feat-001_sf6eht](../tasks/ccb_feature_haiku_20260302_005828--mcp-remote-direct--mcp_servo-css-container-query-feat-001_sf6eht.html) | [source](../../../benchmarks/ccb_feature/servo-css-container-query-feat-001) | `mcp-remote-direct` | `failed` | 0.000 | 4 | 0.454 |
| [mcp_servo-css-container-query-feat-001_9uogue](../tasks/ccb_feature_haiku_20260302_004743--mcp-remote-direct--mcp_servo-css-container-query-feat-001_9uogue.html) | [source](../../../benchmarks/ccb_feature/servo-css-container-query-feat-001) | `mcp-remote-direct` | `failed` | 0.000 | 4 | 0.625 |
| [servo-scrollend-event-feat-001](../tasks/feature_haiku_20260301_071229--baseline-local-direct--servo-scrollend-event-feat-001.html) | [source](../../../benchmarks/ccb_feature/servo-scrollend-event-feat-001) | `baseline-local-direct` | `passed` | 0.500 | 3 | 0.000 |
| [sgonly_servo-scrollend-event-feat-001](../tasks/feature_haiku_20260301_071229--mcp-remote-direct--sgonly_servo-scrollend-event-feat-001.html) | [source](../../../benchmarks/ccb_feature/servo-scrollend-event-feat-001) | `mcp-remote-direct` | `passed` | 0.500 | 3 | 0.709 |
| [strata-cds-tranche-feat-001](../tasks/feature_haiku_20260301_071229--baseline-local-direct--strata-cds-tranche-feat-001.html) | [source](../../../benchmarks/ccb_feature/strata-cds-tranche-feat-001) | `baseline-local-direct` | `passed` | 0.390 | 5 | 0.000 |
| [sgonly_strata-cds-tranche-feat-001](../tasks/feature_haiku_20260301_071229--mcp-remote-direct--sgonly_strata-cds-tranche-feat-001.html) | [source](../../../benchmarks/ccb_feature/strata-cds-tranche-feat-001) | `mcp-remote-direct` | `passed` | 0.370 | 5 | 0.400 |
| [tensorrt-mxfp4-quant-feat-001](../tasks/feature_haiku_20260301_071229--baseline-local-direct--tensorrt-mxfp4-quant-feat-001.html) | [source](../../../benchmarks/ccb_feature/tensorrt-mxfp4-quant-feat-001) | `baseline-local-direct` | `passed` | 1.000 | 4 | 0.000 |
| [sgonly_tensorrt-mxfp4-quant-feat-001](../tasks/feature_haiku_20260301_071229--mcp-remote-direct--sgonly_tensorrt-mxfp4-quant-feat-001.html) | [source](../../../benchmarks/ccb_feature/tensorrt-mxfp4-quant-feat-001) | `mcp-remote-direct` | `failed` | 0.000 | 4 | 0.390 |
| [terraform-compact-diff-fmt-feat-001](../tasks/feature_haiku_20260301_071229--baseline-local-direct--terraform-compact-diff-fmt-feat-001.html) | [source](../../../benchmarks/ccb_feature/terraform-compact-diff-fmt-feat-001) | `baseline-local-direct` | `passed` | 1.000 | 3 | 0.000 |
| [sgonly_terraform-compact-diff-fmt-feat-001](../tasks/feature_haiku_20260301_071229--mcp-remote-direct--sgonly_terraform-compact-diff-fmt-feat-001.html) | [source](../../../benchmarks/ccb_feature/terraform-compact-diff-fmt-feat-001) | `mcp-remote-direct` | `passed` | 1.000 | 3 | 0.604 |
| [vscode-custom-fold-region-feat-001](../tasks/ccb_feature_haiku_20260302_005828--baseline-local-direct--vscode-custom-fold-region-feat-001.html) | [source](../../../benchmarks/ccb_feature/vscode-custom-fold-region-feat-001) | `baseline-local-direct` | `passed` | 0.333 | 4 | 0.000 |
| [mcp_vscode-custom-fold-region-feat-001_9bhijx](../tasks/ccb_feature_haiku_20260301_230003--mcp-remote-direct--mcp_vscode-custom-fold-region-feat-001_9bhijx.html) | [source](../../../benchmarks/ccb_feature/vscode-custom-fold-region-feat-001) | `mcp-remote-direct` | `passed` | 1.000 | 4 | 0.397 |
| [mcp_vscode-custom-fold-region-feat-001_qrch5q](../tasks/ccb_feature_haiku_20260301_212230--mcp-remote-direct--mcp_vscode-custom-fold-region-feat-001_qrch5q.html) | [source](../../../benchmarks/ccb_feature/vscode-custom-fold-region-feat-001) | `mcp-remote-direct` | `passed` | 1.000 | 4 | 0.583 |
| [mcp_vscode-custom-fold-region-feat-001_0utr7t](../tasks/ccb_feature_haiku_20260302_005828--mcp-remote-direct--mcp_vscode-custom-fold-region-feat-001_0utr7t.html) | [source](../../../benchmarks/ccb_feature/vscode-custom-fold-region-feat-001) | `mcp-remote-direct` | `passed` | 1.000 | 4 | 0.245 |
| [mcp_vscode-custom-fold-region-feat-001_1nsegg](../tasks/ccb_feature_haiku_20260302_004743--mcp-remote-direct--mcp_vscode-custom-fold-region-feat-001_1nsegg.html) | [source](../../../benchmarks/ccb_feature/vscode-custom-fold-region-feat-001) | `mcp-remote-direct` | `passed` | 1.000 | 4 | 0.567 |
| [vscode-stale-diagnostics-feat-001](../tasks/feature_haiku_20260301_071229--baseline-local-direct--vscode-stale-diagnostics-feat-001.html) | [source](../../../benchmarks/ccb_feature/vscode-stale-diagnostics-feat-001) | `baseline-local-direct` | `passed` | 0.700 | 6 | 0.000 |
| [sgonly_vscode-stale-diagnostics-feat-001](../tasks/feature_haiku_20260228_220733--mcp-remote-direct--sgonly_vscode-stale-diagnostics-feat-001.html) | [source](../../../benchmarks/ccb_feature/vscode-stale-diagnostics-feat-001) | `mcp-remote-direct` | `failed` | 0.000 | 2 | 0.120 |

## Multi-Run Variance

Tasks with multiple valid runs (46 task/config pairs).

| Task | Benchmark | Config | Runs | Mean | Std | Individual Rewards |
|---|---|---|---:|---:|---:|---|
| bustub-hyperloglog-impl-001 | [source](../../../benchmarks/ccb_feature/bustub-hyperloglog-impl-001) | `baseline-local-direct` | 3 | 0.222 | 0.255 | 0.167, 0.500, 0.000 |
| bustub-hyperloglog-impl-001 | [source](../../../benchmarks/ccb_feature/bustub-hyperloglog-impl-001) | `mcp-remote-direct` | 4 | 0.167 | 0.000 | 0.167, 0.167, 0.167, 0.167 |
| camel-fix-protocol-feat-001 | [source](../../../benchmarks/ccb_feature/camel-fix-protocol-feat-001) | `baseline-local-direct` | 4 | 0.320 | 0.164 | 0.470, 0.390, 0.090, 0.330 |
| camel-fix-protocol-feat-001 | [source](../../../benchmarks/ccb_feature/camel-fix-protocol-feat-001) | `mcp-remote-direct` | 5 | 0.332 | 0.130 | 0.450, 0.140, 0.280, 0.450, 0.340 |
| cilium-policy-audit-logger-feat-001 | [source](../../../benchmarks/ccb_feature/cilium-policy-audit-logger-feat-001) | `baseline-local-direct` | 4 | 1.000 | 0.000 | 1.000, 1.000, 1.000, 1.000 |
| cilium-policy-audit-logger-feat-001 | [source](../../../benchmarks/ccb_feature/cilium-policy-audit-logger-feat-001) | `mcp-remote-direct` | 4 | 1.000 | 0.000 | 1.000, 1.000, 1.000, 1.000 |
| cilium-policy-quota-feat-001 | [source](../../../benchmarks/ccb_feature/cilium-policy-quota-feat-001) | `baseline-local-direct` | 4 | 1.000 | 0.000 | 1.000, 1.000, 1.000, 1.000 |
| cilium-policy-quota-feat-001 | [source](../../../benchmarks/ccb_feature/cilium-policy-quota-feat-001) | `mcp-remote-direct` | 4 | 1.000 | 0.000 | 1.000, 1.000, 1.000, 1.000 |
| curl-http3-priority-feat-001 | [source](../../../benchmarks/ccb_feature/curl-http3-priority-feat-001) | `baseline-local-direct` | 5 | 0.833 | 0.000 | 0.833, 0.833, 0.833, 0.833, 0.833 |
| curl-http3-priority-feat-001 | [source](../../../benchmarks/ccb_feature/curl-http3-priority-feat-001) | `mcp-remote-direct` | 4 | 0.667 | 0.333 | 0.167, 0.833, 0.833, 0.833 |
| django-rate-limit-middleware-feat-001 | [source](../../../benchmarks/ccb_feature/django-rate-limit-middleware-feat-001) | `baseline-local-direct` | 4 | 1.000 | 0.000 | 1.000, 1.000, 1.000, 1.000 |
| django-rate-limit-middleware-feat-001 | [source](../../../benchmarks/ccb_feature/django-rate-limit-middleware-feat-001) | `mcp-remote-direct` | 3 | 1.000 | 0.000 | 1.000, 1.000, 1.000 |
| envoy-custom-header-filter-feat-001 | [source](../../../benchmarks/ccb_feature/envoy-custom-header-filter-feat-001) | `baseline-local-direct` | 5 | 1.000 | 0.000 | 1.000, 1.000, 1.000, 1.000, 1.000 |
| envoy-custom-header-filter-feat-001 | [source](../../../benchmarks/ccb_feature/envoy-custom-header-filter-feat-001) | `mcp-remote-direct` | 5 | 1.000 | 0.000 | 1.000, 1.000, 1.000, 1.000, 1.000 |
| envoy-grpc-server-impl-001 | [source](../../../benchmarks/ccb_feature/envoy-grpc-server-impl-001) | `baseline-local-direct` | 3 | 0.440 | 0.000 | 0.440, 0.440, 0.440 |
| envoy-grpc-server-impl-001 | [source](../../../benchmarks/ccb_feature/envoy-grpc-server-impl-001) | `mcp-remote-direct` | 3 | 0.387 | 0.147 | 0.220, 0.440, 0.500 |
| flink-pricing-window-feat-001 | [source](../../../benchmarks/ccb_feature/flink-pricing-window-feat-001) | `baseline-local-direct` | 4 | 0.487 | 0.071 | 0.540, 0.540, 0.390, 0.480 |
| flink-pricing-window-feat-001 | [source](../../../benchmarks/ccb_feature/flink-pricing-window-feat-001) | `mcp-remote-direct` | 4 | 0.395 | 0.079 | 0.490, 0.410, 0.300, 0.380 |
| k8s-noschedule-taint-feat-001 | [source](../../../benchmarks/ccb_feature/k8s-noschedule-taint-feat-001) | `baseline-local-direct` | 5 | 0.420 | 0.383 | 0.700, 0.700, 0.700, 0.000, 0.000 |
| k8s-noschedule-taint-feat-001 | [source](../../../benchmarks/ccb_feature/k8s-noschedule-taint-feat-001) | `mcp-remote-direct` | 4 | 0.125 | 0.250 | 0.500, 0.000, 0.000, 0.000 |
| k8s-runtime-object-impl-001 | [source](../../../benchmarks/ccb_feature/k8s-runtime-object-impl-001) | `baseline-local-direct` | 4 | 0.113 | 0.010 | 0.120, 0.110, 0.120, 0.100 |
| k8s-runtime-object-impl-001 | [source](../../../benchmarks/ccb_feature/k8s-runtime-object-impl-001) | `mcp-remote-direct` | 4 | 0.100 | 0.067 | 0.000, 0.130, 0.130, 0.140 |
| numpy-rolling-median-feat-001 | [source](../../../benchmarks/ccb_feature/numpy-rolling-median-feat-001) | `baseline-local-direct` | 4 | 1.000 | 0.000 | 1.000, 1.000, 1.000, 1.000 |
| numpy-rolling-median-feat-001 | [source](../../../benchmarks/ccb_feature/numpy-rolling-median-feat-001) | `mcp-remote-direct` | 4 | 1.000 | 0.000 | 1.000, 1.000, 1.000, 1.000 |
| pandas-merge-asof-indicator-feat-001 | [source](../../../benchmarks/ccb_feature/pandas-merge-asof-indicator-feat-001) | `baseline-local-direct` | 3 | 0.667 | 0.000 | 0.667, 0.667, 0.667 |
| pandas-merge-asof-indicator-feat-001 | [source](../../../benchmarks/ccb_feature/pandas-merge-asof-indicator-feat-001) | `mcp-remote-direct` | 4 | 0.667 | 0.000 | 0.667, 0.667, 0.667, 0.667 |
| postgres-copy-csv-header-feat-001 | [source](../../../benchmarks/ccb_feature/postgres-copy-csv-header-feat-001) | `baseline-local-direct` | 4 | 0.375 | 0.083 | 0.500, 0.333, 0.333, 0.333 |
| postgres-copy-csv-header-feat-001 | [source](../../../benchmarks/ccb_feature/postgres-copy-csv-header-feat-001) | `mcp-remote-direct` | 4 | 0.500 | 0.000 | 0.500, 0.500, 0.500, 0.500 |
| prometheus-silence-bulk-api-feat-001 | [source](../../../benchmarks/ccb_feature/prometheus-silence-bulk-api-feat-001) | `baseline-local-direct` | 3 | 0.833 | 0.000 | 0.833, 0.833, 0.833 |
| prometheus-silence-bulk-api-feat-001 | [source](../../../benchmarks/ccb_feature/prometheus-silence-bulk-api-feat-001) | `mcp-remote-direct` | 3 | 0.833 | 0.000 | 0.833, 0.833, 0.833 |
| pytorch-gradient-noise-feat-001 | [source](../../../benchmarks/ccb_feature/pytorch-gradient-noise-feat-001) | `baseline-local-direct` | 3 | 0.833 | 0.000 | 0.833, 0.833, 0.833 |
| pytorch-gradient-noise-feat-001 | [source](../../../benchmarks/ccb_feature/pytorch-gradient-noise-feat-001) | `mcp-remote-direct` | 3 | 0.833 | 0.000 | 0.833, 0.833, 0.833 |
| servo-css-container-query-feat-001 | [source](../../../benchmarks/ccb_feature/servo-css-container-query-feat-001) | `baseline-local-direct` | 5 | 0.000 | 0.000 | 0.000, 0.000, 0.000, 0.000, 0.000 |
| servo-css-container-query-feat-001 | [source](../../../benchmarks/ccb_feature/servo-css-container-query-feat-001) | `mcp-remote-direct` | 4 | 0.000 | 0.000 | 0.000, 0.000, 0.000, 0.000 |
| servo-scrollend-event-feat-001 | [source](../../../benchmarks/ccb_feature/servo-scrollend-event-feat-001) | `baseline-local-direct` | 3 | 0.500 | 0.000 | 0.500, 0.500, 0.500 |
| servo-scrollend-event-feat-001 | [source](../../../benchmarks/ccb_feature/servo-scrollend-event-feat-001) | `mcp-remote-direct` | 3 | 0.500 | 0.000 | 0.500, 0.500, 0.500 |
| strata-cds-tranche-feat-001 | [source](../../../benchmarks/ccb_feature/strata-cds-tranche-feat-001) | `baseline-local-direct` | 5 | 0.492 | 0.146 | 0.690, 0.600, 0.350, 0.430, 0.390 |
| strata-cds-tranche-feat-001 | [source](../../../benchmarks/ccb_feature/strata-cds-tranche-feat-001) | `mcp-remote-direct` | 5 | 0.354 | 0.195 | 0.360, 0.610, 0.370, 0.060, 0.370 |
| tensorrt-mxfp4-quant-feat-001 | [source](../../../benchmarks/ccb_feature/tensorrt-mxfp4-quant-feat-001) | `baseline-local-direct` | 4 | 0.500 | 0.577 | 0.000, 0.000, 1.000, 1.000 |
| tensorrt-mxfp4-quant-feat-001 | [source](../../../benchmarks/ccb_feature/tensorrt-mxfp4-quant-feat-001) | `mcp-remote-direct` | 4 | 0.750 | 0.500 | 1.000, 1.000, 1.000, 0.000 |
| terraform-compact-diff-fmt-feat-001 | [source](../../../benchmarks/ccb_feature/terraform-compact-diff-fmt-feat-001) | `baseline-local-direct` | 3 | 1.000 | 0.000 | 1.000, 1.000, 1.000 |
| terraform-compact-diff-fmt-feat-001 | [source](../../../benchmarks/ccb_feature/terraform-compact-diff-fmt-feat-001) | `mcp-remote-direct` | 3 | 1.000 | 0.000 | 1.000, 1.000, 1.000 |
| vscode-custom-fold-region-feat-001 | [source](../../../benchmarks/ccb_feature/vscode-custom-fold-region-feat-001) | `baseline-local-direct` | 4 | 0.833 | 0.333 | 1.000, 1.000, 1.000, 0.333 |
| vscode-custom-fold-region-feat-001 | [source](../../../benchmarks/ccb_feature/vscode-custom-fold-region-feat-001) | `mcp-remote-direct` | 4 | 1.000 | 0.000 | 1.000, 1.000, 1.000, 1.000 |
| vscode-stale-diagnostics-feat-001 | [source](../../../benchmarks/ccb_feature/vscode-stale-diagnostics-feat-001) | `baseline-local-direct` | 6 | 0.367 | 0.294 | 0.000, 0.000, 0.500, 0.500, 0.500, 0.700 |
| vscode-stale-diagnostics-feat-001 | [source](../../../benchmarks/ccb_feature/vscode-stale-diagnostics-feat-001) | `mcp-remote-direct` | 2 | 0.000 | 0.000 | 0.000, 0.000 |
