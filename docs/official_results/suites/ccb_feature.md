# ccb_feature

## Run/Config Summary

| Run | Config | Valid Tasks | Mean Reward | Pass Rate |
|---|---|---:|---:|---:|
| [feature_haiku_20260228_211127](../runs/feature_haiku_20260228_211127.md) | `baseline-local-direct` | 9 | 0.907 | 1.000 |
| [feature_haiku_20260228_220733](../runs/feature_haiku_20260228_220733.md) | `baseline-local-direct` | 1 | 1.000 | 1.000 |
| [feature_haiku_20260228_220733](../runs/feature_haiku_20260228_220733.md) | `mcp-remote-direct` | 1 | 0.000 | 0.000 |
| [feature_haiku_20260228_230650](../runs/feature_haiku_20260228_230650.md) | `mcp-remote-direct` | 15 | 0.767 | 1.000 |
| [feature_haiku_20260228_231035](../runs/feature_haiku_20260228_231035.md) | `mcp-remote-direct` | 4 | 0.208 | 0.500 |
| [feature_haiku_20260228_231041](../runs/feature_haiku_20260228_231041.md) | `baseline-local-direct` | 4 | 0.557 | 1.000 |
| [feature_haiku_20260228_231043](../runs/feature_haiku_20260228_231043.md) | `baseline-local-direct` | 5 | 0.339 | 0.800 |
| [feature_haiku_vscode_rerun_20260301_023018](../runs/feature_haiku_vscode_rerun_20260301_023018.md) | `baseline-local-direct` | 1 | 0.500 | 1.000 |

## Tasks

| Task | Benchmark | Config | Status | Reward | Runs | MCP Ratio |
|---|---|---|---|---:|---:|---:|
| [bustub-hyperloglog-impl-001](../tasks/feature_haiku_20260228_231043--baseline-local-direct--bustub-hyperloglog-impl-001.html) | [source](../../../benchmarks/ccb_feature/bustub-hyperloglog-impl-001) | `baseline-local-direct` | `passed` | 0.167 | 4 | 0.000 |
| [sgonly_bustub-hyperloglog-impl-001](../tasks/feature_haiku_20260228_231035--mcp-remote-direct--sgonly_bustub-hyperloglog-impl-001.html) | [source](../../../benchmarks/ccb_feature/bustub-hyperloglog-impl-001) | `mcp-remote-direct` | `passed` | 0.167 | 2 | 0.000 |
| [camel-fix-protocol-feat-001](../tasks/feature_haiku_20260228_231041--baseline-local-direct--camel-fix-protocol-feat-001.html) | [source](../../../benchmarks/ccb_feature/camel-fix-protocol-feat-001) | `baseline-local-direct` | `passed` | 0.390 | 2 | 0.000 |
| [sgonly_camel-fix-protocol-feat-001](../tasks/feature_haiku_20260228_230650--mcp-remote-direct--sgonly_camel-fix-protocol-feat-001.html) | [source](../../../benchmarks/ccb_feature/camel-fix-protocol-feat-001) | `mcp-remote-direct` | `passed` | 0.520 | 4 | 0.509 |
| [cilium-policy-audit-logger-feat-001](../tasks/feature_haiku_20260228_211127--baseline-local-direct--cilium-policy-audit-logger-feat-001.html) | [source](../../../benchmarks/ccb_feature/cilium-policy-audit-logger-feat-001) | `baseline-local-direct` | `passed` | 1.000 | 1 | 0.000 |
| [sgonly_cilium-policy-audit-logger-feat-001](../tasks/feature_haiku_20260228_230650--mcp-remote-direct--sgonly_cilium-policy-audit-logger-feat-001.html) | [source](../../../benchmarks/ccb_feature/cilium-policy-audit-logger-feat-001) | `mcp-remote-direct` | `passed` | 1.000 | 2 | 0.706 |
| [cilium-policy-quota-feat-001](../tasks/feature_haiku_20260228_211127--baseline-local-direct--cilium-policy-quota-feat-001.html) | [source](../../../benchmarks/ccb_feature/cilium-policy-quota-feat-001) | `baseline-local-direct` | `passed` | 1.000 | 1 | 0.000 |
| [sgonly_cilium-policy-quota-feat-001](../tasks/feature_haiku_20260228_230650--mcp-remote-direct--sgonly_cilium-policy-quota-feat-001.html) | [source](../../../benchmarks/ccb_feature/cilium-policy-quota-feat-001) | `mcp-remote-direct` | `passed` | 1.000 | 2 | 0.478 |
| [curl-http3-priority-feat-001](../tasks/feature_haiku_20260228_211127--baseline-local-direct--curl-http3-priority-feat-001.html) | [source](../../../benchmarks/ccb_feature/curl-http3-priority-feat-001) | `baseline-local-direct` | `passed` | 0.833 | 2 | 0.000 |
| [sgonly_curl-http3-priority-feat-001](../tasks/feature_haiku_20260228_230650--mcp-remote-direct--sgonly_curl-http3-priority-feat-001.html) | [source](../../../benchmarks/ccb_feature/curl-http3-priority-feat-001) | `mcp-remote-direct` | `passed` | 0.833 | 2 | 0.151 |
| [django-rate-limit-middleware-feat-001](../tasks/feature_haiku_20260228_211127--baseline-local-direct--django-rate-limit-middleware-feat-001.html) | [source](../../../benchmarks/ccb_feature/django-rate-limit-middleware-feat-001) | `baseline-local-direct` | `passed` | 1.000 | 1 | 0.000 |
| [sgonly_django-rate-limit-middleware-feat-001](../tasks/feature_haiku_20260228_230650--mcp-remote-direct--sgonly_django-rate-limit-middleware-feat-001.html) | [source](../../../benchmarks/ccb_feature/django-rate-limit-middleware-feat-001) | `mcp-remote-direct` | `passed` | 1.000 | 2 | 0.167 |
| [envoy-custom-header-filter-feat-001](../tasks/feature_haiku_20260228_220733--baseline-local-direct--envoy-custom-header-filter-feat-001.html) | [source](../../../benchmarks/ccb_feature/envoy-custom-header-filter-feat-001) | `baseline-local-direct` | `passed` | 1.000 | 2 | 0.000 |
| [sgonly_envoy-custom-header-filter-feat-001](../tasks/feature_haiku_20260228_230650--mcp-remote-direct--sgonly_envoy-custom-header-filter-feat-001.html) | [source](../../../benchmarks/ccb_feature/envoy-custom-header-filter-feat-001) | `mcp-remote-direct` | `passed` | 1.000 | 3 | 0.407 |
| [envoy-grpc-server-impl-001](../tasks/feature_haiku_20260228_231043--baseline-local-direct--envoy-grpc-server-impl-001.html) | [source](../../../benchmarks/ccb_feature/envoy-grpc-server-impl-001) | `baseline-local-direct` | `passed` | 0.440 | 3 | 0.000 |
| [sgonly_envoy-grpc-server-impl-001](../tasks/feature_haiku_20260228_230650--mcp-remote-direct--sgonly_envoy-grpc-server-impl-001.html) | [source](../../../benchmarks/ccb_feature/envoy-grpc-server-impl-001) | `mcp-remote-direct` | `passed` | 0.440 | 2 | 0.943 |
| [flink-pricing-window-feat-001](../tasks/feature_haiku_20260228_231041--baseline-local-direct--flink-pricing-window-feat-001.html) | [source](../../../benchmarks/ccb_feature/flink-pricing-window-feat-001) | `baseline-local-direct` | `passed` | 0.540 | 2 | 0.000 |
| [sgonly_flink-pricing-window-feat-001](../tasks/feature_haiku_20260228_230650--mcp-remote-direct--sgonly_flink-pricing-window-feat-001.html) | [source](../../../benchmarks/ccb_feature/flink-pricing-window-feat-001) | `mcp-remote-direct` | `passed` | 0.480 | 3 | 0.468 |
| [k8s-noschedule-taint-feat-001](../tasks/feature_haiku_20260228_231041--baseline-local-direct--k8s-noschedule-taint-feat-001.html) | [source](../../../benchmarks/ccb_feature/k8s-noschedule-taint-feat-001) | `baseline-local-direct` | `passed` | 0.700 | 3 | 0.000 |
| [sgonly_k8s-noschedule-taint-feat-001](../tasks/feature_haiku_20260228_231035--mcp-remote-direct--sgonly_k8s-noschedule-taint-feat-001.html) | [source](../../../benchmarks/ccb_feature/k8s-noschedule-taint-feat-001) | `mcp-remote-direct` | `failed` | 0.000 | 2 | 0.438 |
| [k8s-runtime-object-impl-001](../tasks/feature_haiku_20260228_231043--baseline-local-direct--k8s-runtime-object-impl-001.html) | [source](../../../benchmarks/ccb_feature/k8s-runtime-object-impl-001) | `baseline-local-direct` | `passed` | 0.090 | 3 | 0.000 |
| [sgonly_k8s-runtime-object-impl-001](../tasks/feature_haiku_20260228_230650--mcp-remote-direct--sgonly_k8s-runtime-object-impl-001.html) | [source](../../../benchmarks/ccb_feature/k8s-runtime-object-impl-001) | `mcp-remote-direct` | `passed` | 0.160 | 2 | 0.690 |
| [numpy-rolling-median-feat-001](../tasks/feature_haiku_20260228_211127--baseline-local-direct--numpy-rolling-median-feat-001.html) | [source](../../../benchmarks/ccb_feature/numpy-rolling-median-feat-001) | `baseline-local-direct` | `passed` | 1.000 | 1 | 0.000 |
| [sgonly_numpy-rolling-median-feat-001](../tasks/feature_haiku_20260228_230650--mcp-remote-direct--sgonly_numpy-rolling-median-feat-001.html) | [source](../../../benchmarks/ccb_feature/numpy-rolling-median-feat-001) | `mcp-remote-direct` | `passed` | 1.000 | 2 | 0.327 |
| [pandas-merge-asof-indicator-feat-001](../tasks/feature_haiku_20260228_211127--baseline-local-direct--pandas-merge-asof-indicator-feat-001.html) | [source](../../../benchmarks/ccb_feature/pandas-merge-asof-indicator-feat-001) | `baseline-local-direct` | `passed` | 0.667 | 1 | 0.000 |
| [sgonly_pandas-merge-asof-indicator-feat-001](../tasks/feature_haiku_20260228_231035--mcp-remote-direct--sgonly_pandas-merge-asof-indicator-feat-001.html) | [source](../../../benchmarks/ccb_feature/pandas-merge-asof-indicator-feat-001) | `mcp-remote-direct` | `passed` | 0.667 | 2 | 0.329 |
| [prometheus-silence-bulk-api-feat-001](../tasks/feature_haiku_20260228_211127--baseline-local-direct--prometheus-silence-bulk-api-feat-001.html) | [source](../../../benchmarks/ccb_feature/prometheus-silence-bulk-api-feat-001) | `baseline-local-direct` | `passed` | 0.833 | 1 | 0.000 |
| [sgonly_prometheus-silence-bulk-api-feat-001](../tasks/feature_haiku_20260228_230650--mcp-remote-direct--sgonly_prometheus-silence-bulk-api-feat-001.html) | [source](../../../benchmarks/ccb_feature/prometheus-silence-bulk-api-feat-001) | `mcp-remote-direct` | `passed` | 0.833 | 2 | 0.488 |
| [pytorch-gradient-noise-feat-001](../tasks/feature_haiku_20260228_211127--baseline-local-direct--pytorch-gradient-noise-feat-001.html) | [source](../../../benchmarks/ccb_feature/pytorch-gradient-noise-feat-001) | `baseline-local-direct` | `passed` | 0.833 | 1 | 0.000 |
| [sgonly_pytorch-gradient-noise-feat-001](../tasks/feature_haiku_20260228_230650--mcp-remote-direct--sgonly_pytorch-gradient-noise-feat-001.html) | [source](../../../benchmarks/ccb_feature/pytorch-gradient-noise-feat-001) | `mcp-remote-direct` | `passed` | 0.833 | 2 | 0.385 |
| [servo-scrollend-event-feat-001](../tasks/feature_haiku_20260228_231043--baseline-local-direct--servo-scrollend-event-feat-001.html) | [source](../../../benchmarks/ccb_feature/servo-scrollend-event-feat-001) | `baseline-local-direct` | `failed` | 0.000 | 3 | 0.000 |
| [sgonly_servo-scrollend-event-feat-001](../tasks/feature_haiku_20260228_231035--mcp-remote-direct--sgonly_servo-scrollend-event-feat-001.html) | [source](../../../benchmarks/ccb_feature/servo-scrollend-event-feat-001) | `mcp-remote-direct` | `failed` | 0.000 | 3 | 0.691 |
| [strata-cds-tranche-feat-001](../tasks/feature_haiku_20260228_231041--baseline-local-direct--strata-cds-tranche-feat-001.html) | [source](../../../benchmarks/ccb_feature/strata-cds-tranche-feat-001) | `baseline-local-direct` | `passed` | 0.600 | 2 | 0.000 |
| [sgonly_strata-cds-tranche-feat-001](../tasks/feature_haiku_20260228_230650--mcp-remote-direct--sgonly_strata-cds-tranche-feat-001.html) | [source](../../../benchmarks/ccb_feature/strata-cds-tranche-feat-001) | `mcp-remote-direct` | `passed` | 0.410 | 3 | 0.531 |
| [tensorrt-mxfp4-quant-feat-001](../tasks/feature_haiku_20260228_231043--baseline-local-direct--tensorrt-mxfp4-quant-feat-001.html) | [source](../../../benchmarks/ccb_feature/tensorrt-mxfp4-quant-feat-001) | `baseline-local-direct` | `passed` | 1.000 | 4 | 0.000 |
| [sgonly_tensorrt-mxfp4-quant-feat-001](../tasks/feature_haiku_20260228_230650--mcp-remote-direct--sgonly_tensorrt-mxfp4-quant-feat-001.html) | [source](../../../benchmarks/ccb_feature/tensorrt-mxfp4-quant-feat-001) | `mcp-remote-direct` | `passed` | 1.000 | 3 | 0.422 |
| [terraform-compact-diff-fmt-feat-001](../tasks/feature_haiku_20260228_211127--baseline-local-direct--terraform-compact-diff-fmt-feat-001.html) | [source](../../../benchmarks/ccb_feature/terraform-compact-diff-fmt-feat-001) | `baseline-local-direct` | `passed` | 1.000 | 1 | 0.000 |
| [sgonly_terraform-compact-diff-fmt-feat-001](../tasks/feature_haiku_20260228_230650--mcp-remote-direct--sgonly_terraform-compact-diff-fmt-feat-001.html) | [source](../../../benchmarks/ccb_feature/terraform-compact-diff-fmt-feat-001) | `mcp-remote-direct` | `passed` | 1.000 | 2 | 0.657 |
| [vscode-stale-diagnostics-feat-001](../tasks/feature_haiku_vscode_rerun_20260301_023018--baseline-local-direct--vscode-stale-diagnostics-feat-001.html) | [source](../../../benchmarks/ccb_feature/vscode-stale-diagnostics-feat-001) | `baseline-local-direct` | `passed` | 0.500 | 5 | 0.000 |
| [sgonly_vscode-stale-diagnostics-feat-001](../tasks/feature_haiku_20260228_220733--mcp-remote-direct--sgonly_vscode-stale-diagnostics-feat-001.html) | [source](../../../benchmarks/ccb_feature/vscode-stale-diagnostics-feat-001) | `mcp-remote-direct` | `failed` | 0.000 | 2 | 0.120 |

## Multi-Run Variance

Tasks with multiple valid runs (32 task/config pairs).

| Task | Benchmark | Config | Runs | Mean | Std | Individual Rewards |
|---|---|---|---:|---:|---:|---|
| bustub-hyperloglog-impl-001 | [source](../../../benchmarks/ccb_feature/bustub-hyperloglog-impl-001) | `baseline-local-direct` | 4 | 0.250 | 0.167 | 0.167, 0.500, 0.167, 0.167 |
| bustub-hyperloglog-impl-001 | [source](../../../benchmarks/ccb_feature/bustub-hyperloglog-impl-001) | `mcp-remote-direct` | 2 | 0.167 | 0.000 | 0.167, 0.167 |
| camel-fix-protocol-feat-001 | [source](../../../benchmarks/ccb_feature/camel-fix-protocol-feat-001) | `baseline-local-direct` | 2 | 0.430 | 0.057 | 0.470, 0.390 |
| camel-fix-protocol-feat-001 | [source](../../../benchmarks/ccb_feature/camel-fix-protocol-feat-001) | `mcp-remote-direct` | 4 | 0.347 | 0.171 | 0.450, 0.140, 0.280, 0.520 |
| cilium-policy-audit-logger-feat-001 | [source](../../../benchmarks/ccb_feature/cilium-policy-audit-logger-feat-001) | `mcp-remote-direct` | 2 | 1.000 | 0.000 | 1.000, 1.000 |
| cilium-policy-quota-feat-001 | [source](../../../benchmarks/ccb_feature/cilium-policy-quota-feat-001) | `mcp-remote-direct` | 2 | 1.000 | 0.000 | 1.000, 1.000 |
| curl-http3-priority-feat-001 | [source](../../../benchmarks/ccb_feature/curl-http3-priority-feat-001) | `baseline-local-direct` | 2 | 0.833 | 0.000 | 0.833, 0.833 |
| curl-http3-priority-feat-001 | [source](../../../benchmarks/ccb_feature/curl-http3-priority-feat-001) | `mcp-remote-direct` | 2 | 0.500 | 0.471 | 0.167, 0.833 |
| django-rate-limit-middleware-feat-001 | [source](../../../benchmarks/ccb_feature/django-rate-limit-middleware-feat-001) | `mcp-remote-direct` | 2 | 1.000 | 0.000 | 1.000, 1.000 |
| envoy-custom-header-filter-feat-001 | [source](../../../benchmarks/ccb_feature/envoy-custom-header-filter-feat-001) | `baseline-local-direct` | 2 | 1.000 | 0.000 | 1.000, 1.000 |
| envoy-custom-header-filter-feat-001 | [source](../../../benchmarks/ccb_feature/envoy-custom-header-filter-feat-001) | `mcp-remote-direct` | 3 | 1.000 | 0.000 | 1.000, 1.000, 1.000 |
| envoy-grpc-server-impl-001 | [source](../../../benchmarks/ccb_feature/envoy-grpc-server-impl-001) | `baseline-local-direct` | 3 | 0.440 | 0.000 | 0.440, 0.440, 0.440 |
| envoy-grpc-server-impl-001 | [source](../../../benchmarks/ccb_feature/envoy-grpc-server-impl-001) | `mcp-remote-direct` | 2 | 0.330 | 0.156 | 0.220, 0.440 |
| flink-pricing-window-feat-001 | [source](../../../benchmarks/ccb_feature/flink-pricing-window-feat-001) | `baseline-local-direct` | 2 | 0.540 | 0.000 | 0.540, 0.540 |
| flink-pricing-window-feat-001 | [source](../../../benchmarks/ccb_feature/flink-pricing-window-feat-001) | `mcp-remote-direct` | 3 | 0.460 | 0.044 | 0.490, 0.410, 0.480 |
| k8s-noschedule-taint-feat-001 | [source](../../../benchmarks/ccb_feature/k8s-noschedule-taint-feat-001) | `baseline-local-direct` | 3 | 0.700 | 0.000 | 0.700, 0.700, 0.700 |
| k8s-noschedule-taint-feat-001 | [source](../../../benchmarks/ccb_feature/k8s-noschedule-taint-feat-001) | `mcp-remote-direct` | 2 | 0.250 | 0.354 | 0.500, 0.000 |
| k8s-runtime-object-impl-001 | [source](../../../benchmarks/ccb_feature/k8s-runtime-object-impl-001) | `baseline-local-direct` | 3 | 0.107 | 0.015 | 0.120, 0.110, 0.090 |
| k8s-runtime-object-impl-001 | [source](../../../benchmarks/ccb_feature/k8s-runtime-object-impl-001) | `mcp-remote-direct` | 2 | 0.080 | 0.113 | 0.000, 0.160 |
| numpy-rolling-median-feat-001 | [source](../../../benchmarks/ccb_feature/numpy-rolling-median-feat-001) | `mcp-remote-direct` | 2 | 1.000 | 0.000 | 1.000, 1.000 |
| pandas-merge-asof-indicator-feat-001 | [source](../../../benchmarks/ccb_feature/pandas-merge-asof-indicator-feat-001) | `mcp-remote-direct` | 2 | 0.667 | 0.000 | 0.667, 0.667 |
| prometheus-silence-bulk-api-feat-001 | [source](../../../benchmarks/ccb_feature/prometheus-silence-bulk-api-feat-001) | `mcp-remote-direct` | 2 | 0.833 | 0.000 | 0.833, 0.833 |
| pytorch-gradient-noise-feat-001 | [source](../../../benchmarks/ccb_feature/pytorch-gradient-noise-feat-001) | `mcp-remote-direct` | 2 | 0.833 | 0.000 | 0.833, 0.833 |
| servo-scrollend-event-feat-001 | [source](../../../benchmarks/ccb_feature/servo-scrollend-event-feat-001) | `baseline-local-direct` | 3 | 0.000 | 0.000 | 0.000, 0.000, 0.000 |
| servo-scrollend-event-feat-001 | [source](../../../benchmarks/ccb_feature/servo-scrollend-event-feat-001) | `mcp-remote-direct` | 3 | 0.000 | 0.000 | 0.000, 0.000, 0.000 |
| strata-cds-tranche-feat-001 | [source](../../../benchmarks/ccb_feature/strata-cds-tranche-feat-001) | `baseline-local-direct` | 2 | 0.645 | 0.064 | 0.690, 0.600 |
| strata-cds-tranche-feat-001 | [source](../../../benchmarks/ccb_feature/strata-cds-tranche-feat-001) | `mcp-remote-direct` | 3 | 0.460 | 0.132 | 0.360, 0.610, 0.410 |
| tensorrt-mxfp4-quant-feat-001 | [source](../../../benchmarks/ccb_feature/tensorrt-mxfp4-quant-feat-001) | `baseline-local-direct` | 4 | 0.250 | 0.500 | 0.000, 0.000, 0.000, 1.000 |
| tensorrt-mxfp4-quant-feat-001 | [source](../../../benchmarks/ccb_feature/tensorrt-mxfp4-quant-feat-001) | `mcp-remote-direct` | 3 | 1.000 | 0.000 | 1.000, 1.000, 1.000 |
| terraform-compact-diff-fmt-feat-001 | [source](../../../benchmarks/ccb_feature/terraform-compact-diff-fmt-feat-001) | `mcp-remote-direct` | 2 | 1.000 | 0.000 | 1.000, 1.000 |
| vscode-stale-diagnostics-feat-001 | [source](../../../benchmarks/ccb_feature/vscode-stale-diagnostics-feat-001) | `baseline-local-direct` | 5 | 0.100 | 0.224 | 0.000, 0.000, 0.000, 0.000, 0.500 |
| vscode-stale-diagnostics-feat-001 | [source](../../../benchmarks/ccb_feature/vscode-stale-diagnostics-feat-001) | `mcp-remote-direct` | 2 | 0.000 | 0.000 | 0.000, 0.000 |
