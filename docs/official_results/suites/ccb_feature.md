# ccb_feature

## Run/Config Summary

| Run | Config | Valid Tasks | Mean Reward | Pass Rate |
|---|---|---:|---:|---:|
| [feature_haiku_20260228_220733](../runs/feature_haiku_20260228_220733.md) | `mcp-remote-direct` | 1 | 0.000 | 0.000 |
| [feature_haiku_20260301_071229](../runs/feature_haiku_20260301_071229.md) | `baseline-local-direct` | 20 | 0.631 | 0.850 |
| [feature_haiku_20260301_071229](../runs/feature_haiku_20260301_071229.md) | `mcp-remote-direct` | 19 | 0.582 | 0.842 |

## Tasks

| Task | Benchmark | Config | Status | Reward | Runs | MCP Ratio |
|---|---|---|---|---:|---:|---:|
| [bustub-hyperloglog-impl-001](../tasks/feature_haiku_20260301_071229--baseline-local-direct--bustub-hyperloglog-impl-001.html) | [source](../../../benchmarks/ccb_feature/bustub-hyperloglog-impl-001) | `baseline-local-direct` | `failed` | 0.000 | 5 | 0.000 |
| [sgonly_bustub-hyperloglog-impl-001](../tasks/feature_haiku_20260301_071229--mcp-remote-direct--sgonly_bustub-hyperloglog-impl-001.html) | [source](../../../benchmarks/ccb_feature/bustub-hyperloglog-impl-001) | `mcp-remote-direct` | `passed` | 0.167 | 4 | 0.165 |
| [camel-fix-protocol-feat-001](../tasks/feature_haiku_20260301_071229--baseline-local-direct--camel-fix-protocol-feat-001.html) | [source](../../../benchmarks/ccb_feature/camel-fix-protocol-feat-001) | `baseline-local-direct` | `passed` | 0.330 | 4 | 0.000 |
| [sgonly_camel-fix-protocol-feat-001](../tasks/feature_haiku_20260301_071229--mcp-remote-direct--sgonly_camel-fix-protocol-feat-001.html) | [source](../../../benchmarks/ccb_feature/camel-fix-protocol-feat-001) | `mcp-remote-direct` | `passed` | 0.340 | 6 | 0.605 |
| [cilium-policy-audit-logger-feat-001](../tasks/feature_haiku_20260301_071229--baseline-local-direct--cilium-policy-audit-logger-feat-001.html) | [source](../../../benchmarks/ccb_feature/cilium-policy-audit-logger-feat-001) | `baseline-local-direct` | `passed` | 1.000 | 4 | 0.000 |
| [sgonly_cilium-policy-audit-logger-feat-001](../tasks/feature_haiku_20260301_071229--mcp-remote-direct--sgonly_cilium-policy-audit-logger-feat-001.html) | [source](../../../benchmarks/ccb_feature/cilium-policy-audit-logger-feat-001) | `mcp-remote-direct` | `passed` | 1.000 | 5 | 0.426 |
| [cilium-policy-quota-feat-001](../tasks/feature_haiku_20260301_071229--baseline-local-direct--cilium-policy-quota-feat-001.html) | [source](../../../benchmarks/ccb_feature/cilium-policy-quota-feat-001) | `baseline-local-direct` | `passed` | 1.000 | 4 | 0.000 |
| [sgonly_cilium-policy-quota-feat-001](../tasks/feature_haiku_20260301_071229--mcp-remote-direct--sgonly_cilium-policy-quota-feat-001.html) | [source](../../../benchmarks/ccb_feature/cilium-policy-quota-feat-001) | `mcp-remote-direct` | `passed` | 1.000 | 5 | 0.361 |
| [curl-http3-priority-feat-001](../tasks/feature_haiku_20260301_071229--baseline-local-direct--curl-http3-priority-feat-001.html) | [source](../../../benchmarks/ccb_feature/curl-http3-priority-feat-001) | `baseline-local-direct` | `passed` | 0.833 | 5 | 0.000 |
| [sgonly_curl-http3-priority-feat-001](../tasks/feature_haiku_20260301_071229--mcp-remote-direct--sgonly_curl-http3-priority-feat-001.html) | [source](../../../benchmarks/ccb_feature/curl-http3-priority-feat-001) | `mcp-remote-direct` | `passed` | 0.833 | 5 | 0.266 |
| [django-rate-limit-middleware-feat-001](../tasks/feature_haiku_20260301_071229--baseline-local-direct--django-rate-limit-middleware-feat-001.html) | [source](../../../benchmarks/ccb_feature/django-rate-limit-middleware-feat-001) | `baseline-local-direct` | `passed` | 1.000 | 4 | 0.000 |
| [sgonly_django-rate-limit-middleware-feat-001](../tasks/feature_haiku_20260301_071229--mcp-remote-direct--sgonly_django-rate-limit-middleware-feat-001.html) | [source](../../../benchmarks/ccb_feature/django-rate-limit-middleware-feat-001) | `mcp-remote-direct` | `passed` | 1.000 | 4 | 0.171 |
| [envoy-custom-header-filter-feat-001](../tasks/feature_haiku_20260301_071229--baseline-local-direct--envoy-custom-header-filter-feat-001.html) | [source](../../../benchmarks/ccb_feature/envoy-custom-header-filter-feat-001) | `baseline-local-direct` | `passed` | 1.000 | 5 | 0.000 |
| [sgonly_envoy-custom-header-filter-feat-001](../tasks/feature_haiku_20260301_071229--mcp-remote-direct--sgonly_envoy-custom-header-filter-feat-001.html) | [source](../../../benchmarks/ccb_feature/envoy-custom-header-filter-feat-001) | `mcp-remote-direct` | `passed` | 1.000 | 6 | 0.510 |
| [envoy-grpc-server-impl-001](../tasks/feature_haiku_20260301_071229--baseline-local-direct--envoy-grpc-server-impl-001.html) | [source](../../../benchmarks/ccb_feature/envoy-grpc-server-impl-001) | `baseline-local-direct` | `passed` | 0.440 | 5 | 0.000 |
| [sgonly_envoy-grpc-server-impl-001](../tasks/feature_haiku_20260301_071229--mcp-remote-direct--sgonly_envoy-grpc-server-impl-001.html) | [source](../../../benchmarks/ccb_feature/envoy-grpc-server-impl-001) | `mcp-remote-direct` | `passed` | 0.500 | 4 | 0.938 |
| [flink-pricing-window-feat-001](../tasks/feature_haiku_20260301_071229--baseline-local-direct--flink-pricing-window-feat-001.html) | [source](../../../benchmarks/ccb_feature/flink-pricing-window-feat-001) | `baseline-local-direct` | `passed` | 0.480 | 4 | 0.000 |
| [sgonly_flink-pricing-window-feat-001](../tasks/feature_haiku_20260301_071229--mcp-remote-direct--sgonly_flink-pricing-window-feat-001.html) | [source](../../../benchmarks/ccb_feature/flink-pricing-window-feat-001) | `mcp-remote-direct` | `passed` | 0.380 | 5 | 0.253 |
| [k8s-noschedule-taint-feat-001](../tasks/feature_haiku_20260301_071229--baseline-local-direct--k8s-noschedule-taint-feat-001.html) | [source](../../../benchmarks/ccb_feature/k8s-noschedule-taint-feat-001) | `baseline-local-direct` | `failed` | 0.000 | 5 | 0.000 |
| [sgonly_k8s-noschedule-taint-feat-001](../tasks/feature_haiku_20260301_071229--mcp-remote-direct--sgonly_k8s-noschedule-taint-feat-001.html) | [source](../../../benchmarks/ccb_feature/k8s-noschedule-taint-feat-001) | `mcp-remote-direct` | `failed` | 0.000 | 4 | 0.441 |
| [k8s-runtime-object-impl-001](../tasks/feature_haiku_20260301_071229--baseline-local-direct--k8s-runtime-object-impl-001.html) | [source](../../../benchmarks/ccb_feature/k8s-runtime-object-impl-001) | `baseline-local-direct` | `passed` | 0.120 | 5 | 0.000 |
| [sgonly_k8s-runtime-object-impl-001](../tasks/feature_haiku_20260301_071229--mcp-remote-direct--sgonly_k8s-runtime-object-impl-001.html) | [source](../../../benchmarks/ccb_feature/k8s-runtime-object-impl-001) | `mcp-remote-direct` | `passed` | 0.130 | 4 | 0.706 |
| [numpy-rolling-median-feat-001](../tasks/feature_haiku_20260301_071229--baseline-local-direct--numpy-rolling-median-feat-001.html) | [source](../../../benchmarks/ccb_feature/numpy-rolling-median-feat-001) | `baseline-local-direct` | `passed` | 1.000 | 4 | 0.000 |
| [sgonly_numpy-rolling-median-feat-001](../tasks/feature_haiku_20260301_071229--mcp-remote-direct--sgonly_numpy-rolling-median-feat-001.html) | [source](../../../benchmarks/ccb_feature/numpy-rolling-median-feat-001) | `mcp-remote-direct` | `passed` | 1.000 | 5 | 0.379 |
| [pandas-merge-asof-indicator-feat-001](../tasks/feature_haiku_20260301_071229--baseline-local-direct--pandas-merge-asof-indicator-feat-001.html) | [source](../../../benchmarks/ccb_feature/pandas-merge-asof-indicator-feat-001) | `baseline-local-direct` | `passed` | 0.667 | 3 | 0.000 |
| [sgonly_pandas-merge-asof-indicator-feat-001](../tasks/feature_haiku_20260301_071229--mcp-remote-direct--sgonly_pandas-merge-asof-indicator-feat-001.html) | [source](../../../benchmarks/ccb_feature/pandas-merge-asof-indicator-feat-001) | `mcp-remote-direct` | `passed` | 0.667 | 4 | 0.278 |
| [prometheus-silence-bulk-api-feat-001](../tasks/feature_haiku_20260301_071229--baseline-local-direct--prometheus-silence-bulk-api-feat-001.html) | [source](../../../benchmarks/ccb_feature/prometheus-silence-bulk-api-feat-001) | `baseline-local-direct` | `passed` | 0.833 | 3 | 0.000 |
| [sgonly_prometheus-silence-bulk-api-feat-001](../tasks/feature_haiku_20260301_071229--mcp-remote-direct--sgonly_prometheus-silence-bulk-api-feat-001.html) | [source](../../../benchmarks/ccb_feature/prometheus-silence-bulk-api-feat-001) | `mcp-remote-direct` | `passed` | 0.833 | 4 | 0.514 |
| [pytorch-gradient-noise-feat-001](../tasks/feature_haiku_20260301_071229--baseline-local-direct--pytorch-gradient-noise-feat-001.html) | [source](../../../benchmarks/ccb_feature/pytorch-gradient-noise-feat-001) | `baseline-local-direct` | `passed` | 0.833 | 3 | 0.000 |
| [sgonly_pytorch-gradient-noise-feat-001](../tasks/feature_haiku_20260301_071229--mcp-remote-direct--sgonly_pytorch-gradient-noise-feat-001.html) | [source](../../../benchmarks/ccb_feature/pytorch-gradient-noise-feat-001) | `mcp-remote-direct` | `passed` | 0.833 | 4 | 0.368 |
| [servo-scrollend-event-feat-001](../tasks/feature_haiku_20260301_071229--baseline-local-direct--servo-scrollend-event-feat-001.html) | [source](../../../benchmarks/ccb_feature/servo-scrollend-event-feat-001) | `baseline-local-direct` | `failed` | 0.000 | 5 | 0.000 |
| [sgonly_servo-scrollend-event-feat-001](../tasks/feature_haiku_20260301_071229--mcp-remote-direct--sgonly_servo-scrollend-event-feat-001.html) | [source](../../../benchmarks/ccb_feature/servo-scrollend-event-feat-001) | `mcp-remote-direct` | `failed` | 0.000 | 4 | 0.709 |
| [strata-cds-tranche-feat-001](../tasks/feature_haiku_20260301_071229--baseline-local-direct--strata-cds-tranche-feat-001.html) | [source](../../../benchmarks/ccb_feature/strata-cds-tranche-feat-001) | `baseline-local-direct` | `passed` | 0.390 | 5 | 0.000 |
| [sgonly_strata-cds-tranche-feat-001](../tasks/feature_haiku_20260301_071229--mcp-remote-direct--sgonly_strata-cds-tranche-feat-001.html) | [source](../../../benchmarks/ccb_feature/strata-cds-tranche-feat-001) | `mcp-remote-direct` | `passed` | 0.370 | 6 | 0.400 |
| [tensorrt-mxfp4-quant-feat-001](../tasks/feature_haiku_20260301_071229--baseline-local-direct--tensorrt-mxfp4-quant-feat-001.html) | [source](../../../benchmarks/ccb_feature/tensorrt-mxfp4-quant-feat-001) | `baseline-local-direct` | `passed` | 1.000 | 6 | 0.000 |
| [sgonly_tensorrt-mxfp4-quant-feat-001](../tasks/feature_haiku_20260301_071229--mcp-remote-direct--sgonly_tensorrt-mxfp4-quant-feat-001.html) | [source](../../../benchmarks/ccb_feature/tensorrt-mxfp4-quant-feat-001) | `mcp-remote-direct` | `failed` | 0.000 | 5 | 0.390 |
| [terraform-compact-diff-fmt-feat-001](../tasks/feature_haiku_20260301_071229--baseline-local-direct--terraform-compact-diff-fmt-feat-001.html) | [source](../../../benchmarks/ccb_feature/terraform-compact-diff-fmt-feat-001) | `baseline-local-direct` | `passed` | 1.000 | 3 | 0.000 |
| [sgonly_terraform-compact-diff-fmt-feat-001](../tasks/feature_haiku_20260301_071229--mcp-remote-direct--sgonly_terraform-compact-diff-fmt-feat-001.html) | [source](../../../benchmarks/ccb_feature/terraform-compact-diff-fmt-feat-001) | `mcp-remote-direct` | `passed` | 1.000 | 4 | 0.604 |
| [vscode-stale-diagnostics-feat-001](../tasks/feature_haiku_20260301_071229--baseline-local-direct--vscode-stale-diagnostics-feat-001.html) | [source](../../../benchmarks/ccb_feature/vscode-stale-diagnostics-feat-001) | `baseline-local-direct` | `passed` | 0.700 | 8 | 0.000 |
| [sgonly_vscode-stale-diagnostics-feat-001](../tasks/feature_haiku_20260228_220733--mcp-remote-direct--sgonly_vscode-stale-diagnostics-feat-001.html) | [source](../../../benchmarks/ccb_feature/vscode-stale-diagnostics-feat-001) | `mcp-remote-direct` | `failed` | 0.000 | 2 | 0.120 |

## Multi-Run Variance

Tasks with multiple valid runs (40 task/config pairs).

| Task | Benchmark | Config | Runs | Mean | Std | Individual Rewards |
|---|---|---|---:|---:|---:|---|
| bustub-hyperloglog-impl-001 | [source](../../../benchmarks/ccb_feature/bustub-hyperloglog-impl-001) | `baseline-local-direct` | 5 | 0.200 | 0.183 | 0.167, 0.500, 0.167, 0.167, 0.000 |
| bustub-hyperloglog-impl-001 | [source](../../../benchmarks/ccb_feature/bustub-hyperloglog-impl-001) | `mcp-remote-direct` | 4 | 0.167 | 0.000 | 0.167, 0.167, 0.167, 0.167 |
| camel-fix-protocol-feat-001 | [source](../../../benchmarks/ccb_feature/camel-fix-protocol-feat-001) | `baseline-local-direct` | 4 | 0.320 | 0.164 | 0.470, 0.390, 0.090, 0.330 |
| camel-fix-protocol-feat-001 | [source](../../../benchmarks/ccb_feature/camel-fix-protocol-feat-001) | `mcp-remote-direct` | 6 | 0.363 | 0.139 | 0.450, 0.140, 0.280, 0.520, 0.450, 0.340 |
| cilium-policy-audit-logger-feat-001 | [source](../../../benchmarks/ccb_feature/cilium-policy-audit-logger-feat-001) | `baseline-local-direct` | 4 | 1.000 | 0.000 | 1.000, 1.000, 1.000, 1.000 |
| cilium-policy-audit-logger-feat-001 | [source](../../../benchmarks/ccb_feature/cilium-policy-audit-logger-feat-001) | `mcp-remote-direct` | 5 | 1.000 | 0.000 | 1.000, 1.000, 1.000, 1.000, 1.000 |
| cilium-policy-quota-feat-001 | [source](../../../benchmarks/ccb_feature/cilium-policy-quota-feat-001) | `baseline-local-direct` | 4 | 1.000 | 0.000 | 1.000, 1.000, 1.000, 1.000 |
| cilium-policy-quota-feat-001 | [source](../../../benchmarks/ccb_feature/cilium-policy-quota-feat-001) | `mcp-remote-direct` | 5 | 1.000 | 0.000 | 1.000, 1.000, 1.000, 1.000, 1.000 |
| curl-http3-priority-feat-001 | [source](../../../benchmarks/ccb_feature/curl-http3-priority-feat-001) | `baseline-local-direct` | 5 | 0.833 | 0.000 | 0.833, 0.833, 0.833, 0.833, 0.833 |
| curl-http3-priority-feat-001 | [source](../../../benchmarks/ccb_feature/curl-http3-priority-feat-001) | `mcp-remote-direct` | 5 | 0.700 | 0.298 | 0.167, 0.833, 0.833, 0.833, 0.833 |
| django-rate-limit-middleware-feat-001 | [source](../../../benchmarks/ccb_feature/django-rate-limit-middleware-feat-001) | `baseline-local-direct` | 4 | 1.000 | 0.000 | 1.000, 1.000, 1.000, 1.000 |
| django-rate-limit-middleware-feat-001 | [source](../../../benchmarks/ccb_feature/django-rate-limit-middleware-feat-001) | `mcp-remote-direct` | 4 | 1.000 | 0.000 | 1.000, 1.000, 1.000, 1.000 |
| envoy-custom-header-filter-feat-001 | [source](../../../benchmarks/ccb_feature/envoy-custom-header-filter-feat-001) | `baseline-local-direct` | 5 | 1.000 | 0.000 | 1.000, 1.000, 1.000, 1.000, 1.000 |
| envoy-custom-header-filter-feat-001 | [source](../../../benchmarks/ccb_feature/envoy-custom-header-filter-feat-001) | `mcp-remote-direct` | 6 | 1.000 | 0.000 | 1.000, 1.000, 1.000, 1.000, 1.000, 1.000 |
| envoy-grpc-server-impl-001 | [source](../../../benchmarks/ccb_feature/envoy-grpc-server-impl-001) | `baseline-local-direct` | 5 | 0.440 | 0.000 | 0.440, 0.440, 0.440, 0.440, 0.440 |
| envoy-grpc-server-impl-001 | [source](../../../benchmarks/ccb_feature/envoy-grpc-server-impl-001) | `mcp-remote-direct` | 4 | 0.400 | 0.123 | 0.220, 0.440, 0.440, 0.500 |
| flink-pricing-window-feat-001 | [source](../../../benchmarks/ccb_feature/flink-pricing-window-feat-001) | `baseline-local-direct` | 4 | 0.487 | 0.071 | 0.540, 0.540, 0.390, 0.480 |
| flink-pricing-window-feat-001 | [source](../../../benchmarks/ccb_feature/flink-pricing-window-feat-001) | `mcp-remote-direct` | 5 | 0.412 | 0.078 | 0.490, 0.410, 0.480, 0.300, 0.380 |
| k8s-noschedule-taint-feat-001 | [source](../../../benchmarks/ccb_feature/k8s-noschedule-taint-feat-001) | `baseline-local-direct` | 5 | 0.420 | 0.383 | 0.700, 0.700, 0.700, 0.000, 0.000 |
| k8s-noschedule-taint-feat-001 | [source](../../../benchmarks/ccb_feature/k8s-noschedule-taint-feat-001) | `mcp-remote-direct` | 4 | 0.125 | 0.250 | 0.500, 0.000, 0.000, 0.000 |
| k8s-runtime-object-impl-001 | [source](../../../benchmarks/ccb_feature/k8s-runtime-object-impl-001) | `baseline-local-direct` | 5 | 0.110 | 0.012 | 0.120, 0.110, 0.090, 0.110, 0.120 |
| k8s-runtime-object-impl-001 | [source](../../../benchmarks/ccb_feature/k8s-runtime-object-impl-001) | `mcp-remote-direct` | 3 | 0.097 | 0.085 | 0.000, 0.160, 0.130 |
| numpy-rolling-median-feat-001 | [source](../../../benchmarks/ccb_feature/numpy-rolling-median-feat-001) | `baseline-local-direct` | 4 | 1.000 | 0.000 | 1.000, 1.000, 1.000, 1.000 |
| numpy-rolling-median-feat-001 | [source](../../../benchmarks/ccb_feature/numpy-rolling-median-feat-001) | `mcp-remote-direct` | 5 | 1.000 | 0.000 | 1.000, 1.000, 1.000, 1.000, 1.000 |
| pandas-merge-asof-indicator-feat-001 | [source](../../../benchmarks/ccb_feature/pandas-merge-asof-indicator-feat-001) | `baseline-local-direct` | 3 | 0.667 | 0.000 | 0.667, 0.667, 0.667 |
| pandas-merge-asof-indicator-feat-001 | [source](../../../benchmarks/ccb_feature/pandas-merge-asof-indicator-feat-001) | `mcp-remote-direct` | 4 | 0.667 | 0.000 | 0.667, 0.667, 0.667, 0.667 |
| prometheus-silence-bulk-api-feat-001 | [source](../../../benchmarks/ccb_feature/prometheus-silence-bulk-api-feat-001) | `baseline-local-direct` | 3 | 0.833 | 0.000 | 0.833, 0.833, 0.833 |
| prometheus-silence-bulk-api-feat-001 | [source](../../../benchmarks/ccb_feature/prometheus-silence-bulk-api-feat-001) | `mcp-remote-direct` | 4 | 0.833 | 0.000 | 0.833, 0.833, 0.833, 0.833 |
| pytorch-gradient-noise-feat-001 | [source](../../../benchmarks/ccb_feature/pytorch-gradient-noise-feat-001) | `baseline-local-direct` | 3 | 0.833 | 0.000 | 0.833, 0.833, 0.833 |
| pytorch-gradient-noise-feat-001 | [source](../../../benchmarks/ccb_feature/pytorch-gradient-noise-feat-001) | `mcp-remote-direct` | 4 | 0.833 | 0.000 | 0.833, 0.833, 0.833, 0.833 |
| servo-scrollend-event-feat-001 | [source](../../../benchmarks/ccb_feature/servo-scrollend-event-feat-001) | `baseline-local-direct` | 5 | 0.000 | 0.000 | 0.000, 0.000, 0.000, 0.000, 0.000 |
| servo-scrollend-event-feat-001 | [source](../../../benchmarks/ccb_feature/servo-scrollend-event-feat-001) | `mcp-remote-direct` | 4 | 0.000 | 0.000 | 0.000, 0.000, 0.000, 0.000 |
| strata-cds-tranche-feat-001 | [source](../../../benchmarks/ccb_feature/strata-cds-tranche-feat-001) | `baseline-local-direct` | 5 | 0.492 | 0.146 | 0.690, 0.600, 0.350, 0.430, 0.390 |
| strata-cds-tranche-feat-001 | [source](../../../benchmarks/ccb_feature/strata-cds-tranche-feat-001) | `mcp-remote-direct` | 6 | 0.363 | 0.176 | 0.360, 0.610, 0.410, 0.370, 0.060, 0.370 |
| tensorrt-mxfp4-quant-feat-001 | [source](../../../benchmarks/ccb_feature/tensorrt-mxfp4-quant-feat-001) | `baseline-local-direct` | 6 | 0.500 | 0.548 | 0.000, 0.000, 0.000, 1.000, 1.000, 1.000 |
| tensorrt-mxfp4-quant-feat-001 | [source](../../../benchmarks/ccb_feature/tensorrt-mxfp4-quant-feat-001) | `mcp-remote-direct` | 5 | 0.800 | 0.447 | 1.000, 1.000, 1.000, 1.000, 0.000 |
| terraform-compact-diff-fmt-feat-001 | [source](../../../benchmarks/ccb_feature/terraform-compact-diff-fmt-feat-001) | `baseline-local-direct` | 3 | 1.000 | 0.000 | 1.000, 1.000, 1.000 |
| terraform-compact-diff-fmt-feat-001 | [source](../../../benchmarks/ccb_feature/terraform-compact-diff-fmt-feat-001) | `mcp-remote-direct` | 4 | 1.000 | 0.000 | 1.000, 1.000, 1.000, 1.000 |
| vscode-stale-diagnostics-feat-001 | [source](../../../benchmarks/ccb_feature/vscode-stale-diagnostics-feat-001) | `baseline-local-direct` | 8 | 0.275 | 0.301 | 0.000, 0.000, 0.000, 0.000, 0.500, 0.500, 0.500, 0.700 |
| vscode-stale-diagnostics-feat-001 | [source](../../../benchmarks/ccb_feature/vscode-stale-diagnostics-feat-001) | `mcp-remote-direct` | 2 | 0.000 | 0.000 | 0.000, 0.000 |
