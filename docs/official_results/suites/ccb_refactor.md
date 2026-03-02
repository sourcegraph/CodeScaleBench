# ccb_refactor

## Run/Config Summary

| Run | Config | Valid Tasks | Mean Reward | Pass Rate |
|---|---|---:|---:|---:|
| [ccb_refactor_haiku_20260301_133910](../runs/ccb_refactor_haiku_20260301_133910.md) | `baseline-local-direct` | 1 | 0.800 | 1.000 |
| [refactor_haiku_20260301_031849](../runs/refactor_haiku_20260301_031849.md) | `mcp-remote-direct` | 1 | 0.500 | 1.000 |
| [refactor_haiku_20260301_071230](../runs/refactor_haiku_20260301_071230.md) | `baseline-local-direct` | 19 | 0.804 | 0.947 |
| [refactor_haiku_20260301_071230](../runs/refactor_haiku_20260301_071230.md) | `mcp-remote-direct` | 19 | 0.713 | 1.000 |

## Tasks

| Task | Benchmark | Config | Status | Reward | Runs | MCP Ratio |
|---|---|---|---|---:|---:|---:|
| [cilium-endpoint-manager-refac-001](../tasks/refactor_haiku_20260301_071230--baseline-local-direct--cilium-endpoint-manager-refac-001.html) | [source](../../../benchmarks/ccb_refactor/cilium-endpoint-manager-refac-001) | `baseline-local-direct` | `passed` | 0.333 | 3 | 0.000 |
| [sgonly_cilium-endpoint-manager-refac-001](../tasks/refactor_haiku_20260301_071230--mcp-remote-direct--sgonly_cilium-endpoint-manager-refac-001.html) | [source](../../../benchmarks/ccb_refactor/cilium-endpoint-manager-refac-001) | `mcp-remote-direct` | `passed` | 0.500 | 4 | 0.518 |
| [curl-multi-process-refac-001](../tasks/refactor_haiku_20260301_071230--baseline-local-direct--curl-multi-process-refac-001.html) | — | `baseline-local-direct` | `passed` | 1.000 | 4 | 0.000 |
| [sgonly_curl-multi-process-refac-001](../tasks/refactor_haiku_20260301_071230--mcp-remote-direct--sgonly_curl-multi-process-refac-001.html) | — | `mcp-remote-direct` | `passed` | 1.000 | 5 | 0.250 |
| [django-request-factory-refac-001](../tasks/refactor_haiku_20260301_071230--baseline-local-direct--django-request-factory-refac-001.html) | [source](../../../benchmarks/ccb_refactor/django-request-factory-refac-001) | `baseline-local-direct` | `passed` | 1.000 | 4 | 0.000 |
| [sgonly_django-request-factory-refac-001](../tasks/refactor_haiku_20260301_071230--mcp-remote-direct--sgonly_django-request-factory-refac-001.html) | [source](../../../benchmarks/ccb_refactor/django-request-factory-refac-001) | `mcp-remote-direct` | `passed` | 0.667 | 4 | 0.381 |
| [envoy-listener-manager-refac-001](../tasks/refactor_haiku_20260301_071230--baseline-local-direct--envoy-listener-manager-refac-001.html) | [source](../../../benchmarks/ccb_refactor/envoy-listener-manager-refac-001) | `baseline-local-direct` | `passed` | 1.000 | 3 | 0.000 |
| [sgonly_envoy-listener-manager-refac-001](../tasks/refactor_haiku_20260301_071230--mcp-remote-direct--sgonly_envoy-listener-manager-refac-001.html) | [source](../../../benchmarks/ccb_refactor/envoy-listener-manager-refac-001) | `mcp-remote-direct` | `passed` | 1.000 | 4 | 0.119 |
| [etcd-raft-storage-refac-001](../tasks/refactor_haiku_20260301_071230--baseline-local-direct--etcd-raft-storage-refac-001.html) | — | `baseline-local-direct` | `passed` | 0.833 | 4 | 0.000 |
| [sgonly_etcd-raft-storage-refac-001](../tasks/refactor_haiku_20260301_071230--mcp-remote-direct--sgonly_etcd-raft-storage-refac-001.html) | — | `mcp-remote-direct` | `passed` | 0.833 | 4 | 0.171 |
| [flipt-dep-refactor-001](../tasks/ccb_refactor_haiku_20260301_133910--baseline-local-direct--flipt-dep-refactor-001.html) | [source](../../../benchmarks/ccb_refactor/flipt-dep-refactor-001) | `baseline-local-direct` | `passed` | 0.800 | 5 | 0.000 |
| [sgonly_flipt-dep-refactor-001](../tasks/refactor_haiku_20260301_071230--mcp-remote-direct--sgonly_flipt-dep-refactor-001.html) | [source](../../../benchmarks/ccb_refactor/flipt-dep-refactor-001) | `mcp-remote-direct` | `passed` | 0.180 | 3 | 0.338 |
| [flipt-flagexists-refactor-001](../tasks/refactor_haiku_20260301_071230--baseline-local-direct--flipt-flagexists-refactor-001.html) | [source](../../../benchmarks/ccb_refactor/flipt-flagexists-refactor-001) | `baseline-local-direct` | `passed` | 0.850 | 4 | 0.000 |
| [sgonly_flipt-flagexists-refactor-001](../tasks/refactor_haiku_20260301_071230--mcp-remote-direct--sgonly_flipt-flagexists-refactor-001.html) | [source](../../../benchmarks/ccb_refactor/flipt-flagexists-refactor-001) | `mcp-remote-direct` | `passed` | 0.550 | 3 | 0.207 |
| [istio-discovery-server-refac-001](../tasks/refactor_haiku_20260301_071230--baseline-local-direct--istio-discovery-server-refac-001.html) | [source](../../../benchmarks/ccb_refactor/istio-discovery-server-refac-001) | `baseline-local-direct` | `passed` | 1.000 | 4 | 0.000 |
| [sgonly_istio-discovery-server-refac-001](../tasks/refactor_haiku_20260301_031849--mcp-remote-direct--sgonly_istio-discovery-server-refac-001.html) | [source](../../../benchmarks/ccb_refactor/istio-discovery-server-refac-001) | `mcp-remote-direct` | `passed` | 0.500 | 3 | 0.062 |
| [k8s-score-normalizer-refac-001](../tasks/refactor_haiku_20260301_071230--baseline-local-direct--k8s-score-normalizer-refac-001.html) | [source](../../../benchmarks/ccb_refactor/k8s-score-normalizer-refac-001) | `baseline-local-direct` | `passed` | 0.660 | 4 | 0.000 |
| [sgonly_k8s-score-normalizer-refac-001](../tasks/refactor_haiku_20260301_071230--mcp-remote-direct--sgonly_k8s-score-normalizer-refac-001.html) | [source](../../../benchmarks/ccb_refactor/k8s-score-normalizer-refac-001) | `mcp-remote-direct` | `passed` | 0.760 | 3 | 0.230 |
| [kafka-batch-accumulator-refac-001](../tasks/refactor_haiku_20260301_071230--baseline-local-direct--kafka-batch-accumulator-refac-001.html) | [source](../../../benchmarks/ccb_refactor/kafka-batch-accumulator-refac-001) | `baseline-local-direct` | `passed` | 0.790 | 3 | 0.000 |
| [sgonly_kafka-batch-accumulator-refac-001](../tasks/refactor_haiku_20260301_071230--mcp-remote-direct--sgonly_kafka-batch-accumulator-refac-001.html) | [source](../../../benchmarks/ccb_refactor/kafka-batch-accumulator-refac-001) | `mcp-remote-direct` | `passed` | 0.530 | 3 | 0.097 |
| [kubernetes-scheduler-profile-refac-001](../tasks/refactor_haiku_20260301_071230--baseline-local-direct--kubernetes-scheduler-profile-refac-001.html) | [source](../../../benchmarks/ccb_refactor/kubernetes-scheduler-profile-refac-001) | `baseline-local-direct` | `passed` | 1.000 | 4 | 0.000 |
| [sgonly_kubernetes-scheduler-profile-refac-001](../tasks/refactor_haiku_20260301_071230--mcp-remote-direct--sgonly_kubernetes-scheduler-profile-refac-001.html) | [source](../../../benchmarks/ccb_refactor/kubernetes-scheduler-profile-refac-001) | `mcp-remote-direct` | `passed` | 0.833 | 4 | 0.603 |
| [numpy-array-dispatch-refac-001](../tasks/refactor_haiku_20260301_071230--baseline-local-direct--numpy-array-dispatch-refac-001.html) | [source](../../../benchmarks/ccb_refactor/numpy-array-dispatch-refac-001) | `baseline-local-direct` | `passed` | 1.000 | 4 | 0.000 |
| [sgonly_numpy-array-dispatch-refac-001](../tasks/refactor_haiku_20260301_071230--mcp-remote-direct--sgonly_numpy-array-dispatch-refac-001.html) | [source](../../../benchmarks/ccb_refactor/numpy-array-dispatch-refac-001) | `mcp-remote-direct` | `passed` | 0.667 | 4 | 0.667 |
| [pandas-index-engine-refac-001](../tasks/refactor_haiku_20260301_071230--baseline-local-direct--pandas-index-engine-refac-001.html) | [source](../../../benchmarks/ccb_refactor/pandas-index-engine-refac-001) | `baseline-local-direct` | `passed` | 0.667 | 4 | 0.000 |
| [sgonly_pandas-index-engine-refac-001](../tasks/refactor_haiku_20260301_071230--mcp-remote-direct--sgonly_pandas-index-engine-refac-001.html) | [source](../../../benchmarks/ccb_refactor/pandas-index-engine-refac-001) | `mcp-remote-direct` | `passed` | 0.667 | 4 | 0.138 |
| [prometheus-query-engine-refac-001](../tasks/refactor_haiku_20260301_071230--baseline-local-direct--prometheus-query-engine-refac-001.html) | [source](../../../benchmarks/ccb_refactor/prometheus-query-engine-refac-001) | `baseline-local-direct` | `passed` | 0.833 | 4 | 0.000 |
| [sgonly_prometheus-query-engine-refac-001](../tasks/refactor_haiku_20260301_071230--mcp-remote-direct--sgonly_prometheus-query-engine-refac-001.html) | [source](../../../benchmarks/ccb_refactor/prometheus-query-engine-refac-001) | `mcp-remote-direct` | `passed` | 0.833 | 4 | 0.421 |
| [python-http-class-naming-refac-001](../tasks/refactor_haiku_20260301_071230--baseline-local-direct--python-http-class-naming-refac-001.html) | [source](../../../benchmarks/ccb_refactor/python-http-class-naming-refac-001) | `baseline-local-direct` | `passed` | 0.920 | 4 | 0.000 |
| [sgonly_python-http-class-naming-refac-001](../tasks/refactor_haiku_20260301_071230--mcp-remote-direct--sgonly_python-http-class-naming-refac-001.html) | [source](../../../benchmarks/ccb_refactor/python-http-class-naming-refac-001) | `mcp-remote-direct` | `passed` | 0.920 | 4 | 0.077 |
| [pytorch-optimizer-foreach-refac-001](../tasks/refactor_haiku_20260301_071230--baseline-local-direct--pytorch-optimizer-foreach-refac-001.html) | [source](../../../benchmarks/ccb_refactor/pytorch-optimizer-foreach-refac-001) | `baseline-local-direct` | `failed` | 0.000 | 3 | 0.000 |
| [sgonly_pytorch-optimizer-foreach-refac-001](../tasks/refactor_haiku_20260301_071230--mcp-remote-direct--sgonly_pytorch-optimizer-foreach-refac-001.html) | [source](../../../benchmarks/ccb_refactor/pytorch-optimizer-foreach-refac-001) | `mcp-remote-direct` | `passed` | 0.167 | 4 | 0.371 |
| [rust-subtype-relation-refac-001](../tasks/refactor_haiku_20260301_071230--baseline-local-direct--rust-subtype-relation-refac-001.html) | — | `baseline-local-direct` | `passed` | 0.820 | 4 | 0.000 |
| [sgonly_rust-subtype-relation-refac-001](../tasks/refactor_haiku_20260301_071230--mcp-remote-direct--sgonly_rust-subtype-relation-refac-001.html) | — | `mcp-remote-direct` | `passed` | 0.840 | 4 | 0.414 |
| [scikit-learn-estimator-tags-refac-001](../tasks/refactor_haiku_20260301_071230--baseline-local-direct--scikit-learn-estimator-tags-refac-001.html) | — | `baseline-local-direct` | `passed` | 0.833 | 4 | 0.000 |
| [sgonly_scikit-learn-estimator-tags-refac-001](../tasks/refactor_haiku_20260301_071230--mcp-remote-direct--sgonly_scikit-learn-estimator-tags-refac-001.html) | — | `mcp-remote-direct` | `passed` | 1.000 | 4 | 0.206 |
| [strata-fx-european-refac-001](../tasks/refactor_haiku_20260301_071230--baseline-local-direct--strata-fx-european-refac-001.html) | [source](../../../benchmarks/ccb_refactor/strata-fx-european-refac-001) | `baseline-local-direct` | `passed` | 0.740 | 3 | 0.000 |
| [sgonly_strata-fx-european-refac-001](../tasks/refactor_haiku_20260301_071230--mcp-remote-direct--sgonly_strata-fx-european-refac-001.html) | [source](../../../benchmarks/ccb_refactor/strata-fx-european-refac-001) | `mcp-remote-direct` | `passed` | 0.770 | 3 | 0.367 |
| [terraform-eval-context-refac-001](../tasks/refactor_haiku_20260301_071230--baseline-local-direct--terraform-eval-context-refac-001.html) | [source](../../../benchmarks/ccb_refactor/terraform-eval-context-refac-001) | `baseline-local-direct` | `passed` | 1.000 | 4 | 0.000 |
| [sgonly_terraform-eval-context-refac-001](../tasks/refactor_haiku_20260301_071230--mcp-remote-direct--sgonly_terraform-eval-context-refac-001.html) | [source](../../../benchmarks/ccb_refactor/terraform-eval-context-refac-001) | `mcp-remote-direct` | `passed` | 0.833 | 3 | 0.305 |

## Multi-Run Variance

Tasks with multiple valid runs (32 task/config pairs).

| Task | Benchmark | Config | Runs | Mean | Std | Individual Rewards |
|---|---|---|---:|---:|---:|---|
| cilium-endpoint-manager-refac-001 | [source](../../../benchmarks/ccb_refactor/cilium-endpoint-manager-refac-001) | `baseline-local-direct` | 3 | 0.389 | 0.096 | 0.333, 0.500, 0.333 |
| cilium-endpoint-manager-refac-001 | [source](../../../benchmarks/ccb_refactor/cilium-endpoint-manager-refac-001) | `mcp-remote-direct` | 4 | 0.417 | 0.096 | 0.333, 0.500, 0.333, 0.500 |
| django-request-factory-refac-001 | [source](../../../benchmarks/ccb_refactor/django-request-factory-refac-001) | `baseline-local-direct` | 4 | 0.875 | 0.083 | 0.833, 0.833, 0.833, 1.000 |
| django-request-factory-refac-001 | [source](../../../benchmarks/ccb_refactor/django-request-factory-refac-001) | `mcp-remote-direct` | 4 | 0.708 | 0.083 | 0.667, 0.667, 0.833, 0.667 |
| envoy-listener-manager-refac-001 | [source](../../../benchmarks/ccb_refactor/envoy-listener-manager-refac-001) | `baseline-local-direct` | 3 | 1.000 | 0.000 | 1.000, 1.000, 1.000 |
| envoy-listener-manager-refac-001 | [source](../../../benchmarks/ccb_refactor/envoy-listener-manager-refac-001) | `mcp-remote-direct` | 4 | 0.917 | 0.096 | 0.833, 1.000, 0.833, 1.000 |
| flipt-dep-refactor-001 | [source](../../../benchmarks/ccb_refactor/flipt-dep-refactor-001) | `baseline-local-direct` | 5 | 0.550 | 0.269 | 0.150, 0.800, 0.500, 0.500, 0.800 |
| flipt-dep-refactor-001 | [source](../../../benchmarks/ccb_refactor/flipt-dep-refactor-001) | `mcp-remote-direct` | 3 | 0.237 | 0.051 | 0.280, 0.250, 0.180 |
| flipt-flagexists-refactor-001 | [source](../../../benchmarks/ccb_refactor/flipt-flagexists-refactor-001) | `baseline-local-direct` | 4 | 0.637 | 0.266 | 0.300, 0.850, 0.550, 0.850 |
| flipt-flagexists-refactor-001 | [source](../../../benchmarks/ccb_refactor/flipt-flagexists-refactor-001) | `mcp-remote-direct` | 3 | 0.527 | 0.236 | 0.750, 0.280, 0.550 |
| istio-discovery-server-refac-001 | [source](../../../benchmarks/ccb_refactor/istio-discovery-server-refac-001) | `baseline-local-direct` | 4 | 1.000 | 0.000 | 1.000, 1.000, 1.000, 1.000 |
| istio-discovery-server-refac-001 | [source](../../../benchmarks/ccb_refactor/istio-discovery-server-refac-001) | `mcp-remote-direct` | 3 | 0.833 | 0.289 | 1.000, 1.000, 0.500 |
| k8s-score-normalizer-refac-001 | [source](../../../benchmarks/ccb_refactor/k8s-score-normalizer-refac-001) | `baseline-local-direct` | 4 | 0.738 | 0.059 | 0.800, 0.760, 0.730, 0.660 |
| k8s-score-normalizer-refac-001 | [source](../../../benchmarks/ccb_refactor/k8s-score-normalizer-refac-001) | `mcp-remote-direct` | 3 | 0.767 | 0.060 | 0.830, 0.710, 0.760 |
| kafka-batch-accumulator-refac-001 | [source](../../../benchmarks/ccb_refactor/kafka-batch-accumulator-refac-001) | `baseline-local-direct` | 3 | 0.747 | 0.131 | 0.850, 0.600, 0.790 |
| kafka-batch-accumulator-refac-001 | [source](../../../benchmarks/ccb_refactor/kafka-batch-accumulator-refac-001) | `mcp-remote-direct` | 3 | 0.613 | 0.076 | 0.630, 0.680, 0.530 |
| kubernetes-scheduler-profile-refac-001 | [source](../../../benchmarks/ccb_refactor/kubernetes-scheduler-profile-refac-001) | `baseline-local-direct` | 4 | 0.792 | 0.417 | 1.000, 1.000, 0.167, 1.000 |
| kubernetes-scheduler-profile-refac-001 | [source](../../../benchmarks/ccb_refactor/kubernetes-scheduler-profile-refac-001) | `mcp-remote-direct` | 4 | 0.958 | 0.083 | 1.000, 1.000, 1.000, 0.833 |
| numpy-array-dispatch-refac-001 | [source](../../../benchmarks/ccb_refactor/numpy-array-dispatch-refac-001) | `baseline-local-direct` | 4 | 1.000 | 0.000 | 1.000, 1.000, 1.000, 1.000 |
| numpy-array-dispatch-refac-001 | [source](../../../benchmarks/ccb_refactor/numpy-array-dispatch-refac-001) | `mcp-remote-direct` | 4 | 0.792 | 0.083 | 0.833, 0.833, 0.833, 0.667 |
| pandas-index-engine-refac-001 | [source](../../../benchmarks/ccb_refactor/pandas-index-engine-refac-001) | `baseline-local-direct` | 4 | 0.667 | 0.000 | 0.667, 0.667, 0.667, 0.667 |
| pandas-index-engine-refac-001 | [source](../../../benchmarks/ccb_refactor/pandas-index-engine-refac-001) | `mcp-remote-direct` | 4 | 0.500 | 0.333 | 0.000, 0.667, 0.667, 0.667 |
| prometheus-query-engine-refac-001 | [source](../../../benchmarks/ccb_refactor/prometheus-query-engine-refac-001) | `baseline-local-direct` | 4 | 0.875 | 0.083 | 0.833, 1.000, 0.833, 0.833 |
| prometheus-query-engine-refac-001 | [source](../../../benchmarks/ccb_refactor/prometheus-query-engine-refac-001) | `mcp-remote-direct` | 4 | 0.667 | 0.451 | 1.000, 0.000, 0.833, 0.833 |
| python-http-class-naming-refac-001 | [source](../../../benchmarks/ccb_refactor/python-http-class-naming-refac-001) | `baseline-local-direct` | 4 | 0.840 | 0.160 | 0.600, 0.920, 0.920, 0.920 |
| python-http-class-naming-refac-001 | [source](../../../benchmarks/ccb_refactor/python-http-class-naming-refac-001) | `mcp-remote-direct` | 4 | 0.570 | 0.363 | 0.200, 0.840, 0.320, 0.920 |
| pytorch-optimizer-foreach-refac-001 | [source](../../../benchmarks/ccb_refactor/pytorch-optimizer-foreach-refac-001) | `baseline-local-direct` | 3 | 0.056 | 0.096 | 0.000, 0.167, 0.000 |
| pytorch-optimizer-foreach-refac-001 | [source](../../../benchmarks/ccb_refactor/pytorch-optimizer-foreach-refac-001) | `mcp-remote-direct` | 4 | 0.250 | 0.167 | 0.500, 0.167, 0.167, 0.167 |
| strata-fx-european-refac-001 | [source](../../../benchmarks/ccb_refactor/strata-fx-european-refac-001) | `baseline-local-direct` | 3 | 0.590 | 0.269 | 0.280, 0.750, 0.740 |
| strata-fx-european-refac-001 | [source](../../../benchmarks/ccb_refactor/strata-fx-european-refac-001) | `mcp-remote-direct` | 3 | 0.770 | 0.160 | 0.930, 0.610, 0.770 |
| terraform-eval-context-refac-001 | [source](../../../benchmarks/ccb_refactor/terraform-eval-context-refac-001) | `baseline-local-direct` | 4 | 1.000 | 0.000 | 1.000, 1.000, 1.000, 1.000 |
| terraform-eval-context-refac-001 | [source](../../../benchmarks/ccb_refactor/terraform-eval-context-refac-001) | `mcp-remote-direct` | 3 | 0.611 | 0.385 | 0.167, 0.833, 0.833 |
