# ccb_refactor

## Run/Config Summary

| Run | Config | Valid Tasks | Mean Reward | Pass Rate |
|---|---|---:|---:|---:|
| [refactor_haiku_20260301_031849](../runs/refactor_haiku_20260301_031849.md) | `baseline-local-direct` | 20 | 0.755 | 1.000 |
| [refactor_haiku_20260301_031849](../runs/refactor_haiku_20260301_031849.md) | `mcp-remote-direct` | 20 | 0.671 | 1.000 |

## Tasks

| Task | Benchmark | Config | Status | Reward | Runs | MCP Ratio |
|---|---|---|---|---:|---:|---:|
| [cilium-endpoint-manager-refac-001](../tasks/refactor_haiku_20260301_031849--baseline-local-direct--cilium-endpoint-manager-refac-001.html) | [source](../../../benchmarks/ccb_refactor/cilium-endpoint-manager-refac-001) | `baseline-local-direct` | `passed` | 0.500 | 2 | 0.000 |
| [sgonly_cilium-endpoint-manager-refac-001](../tasks/refactor_haiku_20260301_031849--mcp-remote-direct--sgonly_cilium-endpoint-manager-refac-001.html) | [source](../../../benchmarks/ccb_refactor/cilium-endpoint-manager-refac-001) | `mcp-remote-direct` | `passed` | 0.333 | 4 | 0.396 |
| [curl-multi-process-refac-001](../tasks/refactor_haiku_20260301_031849--baseline-local-direct--curl-multi-process-refac-001.html) | [source](../../../benchmarks/ccb_refactor/curl-multi-process-refac-001) | `baseline-local-direct` | `passed` | 1.000 | 3 | 0.000 |
| [sgonly_curl-multi-process-refac-001](../tasks/refactor_haiku_20260301_031849--mcp-remote-direct--sgonly_curl-multi-process-refac-001.html) | [source](../../../benchmarks/ccb_refactor/curl-multi-process-refac-001) | `mcp-remote-direct` | `passed` | 1.000 | 4 | 0.296 |
| [django-request-factory-refac-001](../tasks/refactor_haiku_20260301_031849--baseline-local-direct--django-request-factory-refac-001.html) | [source](../../../benchmarks/ccb_refactor/django-request-factory-refac-001) | `baseline-local-direct` | `passed` | 0.833 | 3 | 0.000 |
| [sgonly_django-request-factory-refac-001](../tasks/refactor_haiku_20260301_031849--mcp-remote-direct--sgonly_django-request-factory-refac-001.html) | [source](../../../benchmarks/ccb_refactor/django-request-factory-refac-001) | `mcp-remote-direct` | `passed` | 0.833 | 4 | 0.302 |
| [envoy-listener-manager-refac-001](../tasks/refactor_haiku_20260301_031849--baseline-local-direct--envoy-listener-manager-refac-001.html) | [source](../../../benchmarks/ccb_refactor/envoy-listener-manager-refac-001) | `baseline-local-direct` | `passed` | 1.000 | 2 | 0.000 |
| [sgonly_envoy-listener-manager-refac-001](../tasks/refactor_haiku_20260301_031849--mcp-remote-direct--sgonly_envoy-listener-manager-refac-001.html) | [source](../../../benchmarks/ccb_refactor/envoy-listener-manager-refac-001) | `mcp-remote-direct` | `passed` | 0.833 | 3 | 0.367 |
| [etcd-raft-storage-refac-001](../tasks/refactor_haiku_20260301_031849--baseline-local-direct--etcd-raft-storage-refac-001.html) | [source](../../../benchmarks/ccb_refactor/etcd-raft-storage-refac-001) | `baseline-local-direct` | `passed` | 1.000 | 3 | 0.000 |
| [sgonly_etcd-raft-storage-refac-001](../tasks/refactor_haiku_20260301_031849--mcp-remote-direct--sgonly_etcd-raft-storage-refac-001.html) | [source](../../../benchmarks/ccb_refactor/etcd-raft-storage-refac-001) | `mcp-remote-direct` | `passed` | 1.000 | 4 | 0.521 |
| [flipt-dep-refactor-001](../tasks/refactor_haiku_20260301_031849--baseline-local-direct--flipt-dep-refactor-001.html) | [source](../../../benchmarks/ccb_refactor/flipt-dep-refactor-001) | `baseline-local-direct` | `passed` | 0.500 | 3 | 0.000 |
| [sgonly_flipt-dep-refactor-001](../tasks/refactor_haiku_20260301_031849--mcp-remote-direct--sgonly_flipt-dep-refactor-001.html) | [source](../../../benchmarks/ccb_refactor/flipt-dep-refactor-001) | `mcp-remote-direct` | `passed` | 0.250 | 4 | 0.301 |
| [flipt-flagexists-refactor-001](../tasks/refactor_haiku_20260301_031849--baseline-local-direct--flipt-flagexists-refactor-001.html) | [source](../../../benchmarks/ccb_refactor/flipt-flagexists-refactor-001) | `baseline-local-direct` | `passed` | 0.550 | 3 | 0.000 |
| [sgonly_flipt-flagexists-refactor-001](../tasks/refactor_haiku_20260301_031849--mcp-remote-direct--sgonly_flipt-flagexists-refactor-001.html) | [source](../../../benchmarks/ccb_refactor/flipt-flagexists-refactor-001) | `mcp-remote-direct` | `passed` | 0.280 | 3 | 0.651 |
| [istio-discovery-server-refac-001](../tasks/refactor_haiku_20260301_031849--baseline-local-direct--istio-discovery-server-refac-001.html) | [source](../../../benchmarks/ccb_refactor/istio-discovery-server-refac-001) | `baseline-local-direct` | `passed` | 1.000 | 3 | 0.000 |
| [sgonly_istio-discovery-server-refac-001](../tasks/refactor_haiku_20260301_031849--mcp-remote-direct--sgonly_istio-discovery-server-refac-001.html) | [source](../../../benchmarks/ccb_refactor/istio-discovery-server-refac-001) | `mcp-remote-direct` | `passed` | 0.500 | 4 | 0.062 |
| [k8s-score-normalizer-refac-001](../tasks/refactor_haiku_20260301_031849--baseline-local-direct--k8s-score-normalizer-refac-001.html) | [source](../../../benchmarks/ccb_refactor/k8s-score-normalizer-refac-001) | `baseline-local-direct` | `passed` | 0.730 | 3 | 0.000 |
| [sgonly_k8s-score-normalizer-refac-001](../tasks/refactor_haiku_20260301_031849--mcp-remote-direct--sgonly_k8s-score-normalizer-refac-001.html) | [source](../../../benchmarks/ccb_refactor/k8s-score-normalizer-refac-001) | `mcp-remote-direct` | `passed` | 0.710 | 4 | 0.444 |
| [kafka-batch-accumulator-refac-001](../tasks/refactor_haiku_20260301_031849--baseline-local-direct--kafka-batch-accumulator-refac-001.html) | [source](../../../benchmarks/ccb_refactor/kafka-batch-accumulator-refac-001) | `baseline-local-direct` | `passed` | 0.600 | 2 | 0.000 |
| [sgonly_kafka-batch-accumulator-refac-001](../tasks/refactor_haiku_20260301_031849--mcp-remote-direct--sgonly_kafka-batch-accumulator-refac-001.html) | [source](../../../benchmarks/ccb_refactor/kafka-batch-accumulator-refac-001) | `mcp-remote-direct` | `passed` | 0.680 | 3 | 0.302 |
| [kubernetes-scheduler-profile-refac-001](../tasks/refactor_haiku_20260301_031849--baseline-local-direct--kubernetes-scheduler-profile-refac-001.html) | [source](../../../benchmarks/ccb_refactor/kubernetes-scheduler-profile-refac-001) | `baseline-local-direct` | `passed` | 0.167 | 3 | 0.000 |
| [sgonly_kubernetes-scheduler-profile-refac-001](../tasks/refactor_haiku_20260301_031849--mcp-remote-direct--sgonly_kubernetes-scheduler-profile-refac-001.html) | [source](../../../benchmarks/ccb_refactor/kubernetes-scheduler-profile-refac-001) | `mcp-remote-direct` | `passed` | 1.000 | 4 | 0.103 |
| [numpy-array-dispatch-refac-001](../tasks/refactor_haiku_20260301_031849--baseline-local-direct--numpy-array-dispatch-refac-001.html) | [source](../../../benchmarks/ccb_refactor/numpy-array-dispatch-refac-001) | `baseline-local-direct` | `passed` | 1.000 | 3 | 0.000 |
| [sgonly_numpy-array-dispatch-refac-001](../tasks/refactor_haiku_20260301_031849--mcp-remote-direct--sgonly_numpy-array-dispatch-refac-001.html) | [source](../../../benchmarks/ccb_refactor/numpy-array-dispatch-refac-001) | `mcp-remote-direct` | `passed` | 0.833 | 4 | 0.566 |
| [pandas-index-engine-refac-001](../tasks/refactor_haiku_20260301_031849--baseline-local-direct--pandas-index-engine-refac-001.html) | [source](../../../benchmarks/ccb_refactor/pandas-index-engine-refac-001) | `baseline-local-direct` | `passed` | 0.667 | 3 | 0.000 |
| [sgonly_pandas-index-engine-refac-001](../tasks/refactor_haiku_20260301_031849--mcp-remote-direct--sgonly_pandas-index-engine-refac-001.html) | [source](../../../benchmarks/ccb_refactor/pandas-index-engine-refac-001) | `mcp-remote-direct` | `passed` | 0.667 | 4 | 0.298 |
| [prometheus-query-engine-refac-001](../tasks/refactor_haiku_20260301_031849--baseline-local-direct--prometheus-query-engine-refac-001.html) | [source](../../../benchmarks/ccb_refactor/prometheus-query-engine-refac-001) | `baseline-local-direct` | `passed` | 0.833 | 3 | 0.000 |
| [sgonly_prometheus-query-engine-refac-001](../tasks/refactor_haiku_20260301_031849--mcp-remote-direct--sgonly_prometheus-query-engine-refac-001.html) | [source](../../../benchmarks/ccb_refactor/prometheus-query-engine-refac-001) | `mcp-remote-direct` | `passed` | 0.833 | 4 | 0.143 |
| [python-http-class-naming-refac-001](../tasks/refactor_haiku_20260301_031849--baseline-local-direct--python-http-class-naming-refac-001.html) | [source](../../../benchmarks/ccb_refactor/python-http-class-naming-refac-001) | `baseline-local-direct` | `passed` | 0.920 | 3 | 0.000 |
| [sgonly_python-http-class-naming-refac-001](../tasks/refactor_haiku_20260301_031849--mcp-remote-direct--sgonly_python-http-class-naming-refac-001.html) | [source](../../../benchmarks/ccb_refactor/python-http-class-naming-refac-001) | `mcp-remote-direct` | `passed` | 0.320 | 4 | 0.422 |
| [pytorch-optimizer-foreach-refac-001](../tasks/refactor_haiku_20260301_031849--baseline-local-direct--pytorch-optimizer-foreach-refac-001.html) | [source](../../../benchmarks/ccb_refactor/pytorch-optimizer-foreach-refac-001) | `baseline-local-direct` | `passed` | 0.167 | 2 | 0.000 |
| [sgonly_pytorch-optimizer-foreach-refac-001](../tasks/refactor_haiku_20260301_031849--mcp-remote-direct--sgonly_pytorch-optimizer-foreach-refac-001.html) | [source](../../../benchmarks/ccb_refactor/pytorch-optimizer-foreach-refac-001) | `mcp-remote-direct` | `passed` | 0.167 | 4 | 0.165 |
| [rust-subtype-relation-refac-001](../tasks/refactor_haiku_20260301_031849--baseline-local-direct--rust-subtype-relation-refac-001.html) | [source](../../../benchmarks/ccb_refactor/rust-subtype-relation-refac-001) | `baseline-local-direct` | `passed` | 0.880 | 3 | 0.000 |
| [sgonly_rust-subtype-relation-refac-001](../tasks/refactor_haiku_20260301_031849--mcp-remote-direct--sgonly_rust-subtype-relation-refac-001.html) | [source](../../../benchmarks/ccb_refactor/rust-subtype-relation-refac-001) | `mcp-remote-direct` | `passed` | 0.900 | 5 | 0.163 |
| [scikit-learn-estimator-tags-refac-001](../tasks/refactor_haiku_20260301_031849--baseline-local-direct--scikit-learn-estimator-tags-refac-001.html) | [source](../../../benchmarks/ccb_refactor/scikit-learn-estimator-tags-refac-001) | `baseline-local-direct` | `passed` | 1.000 | 3 | 0.000 |
| [sgonly_scikit-learn-estimator-tags-refac-001](../tasks/refactor_haiku_20260301_031849--mcp-remote-direct--sgonly_scikit-learn-estimator-tags-refac-001.html) | [source](../../../benchmarks/ccb_refactor/scikit-learn-estimator-tags-refac-001) | `mcp-remote-direct` | `passed` | 0.833 | 4 | 0.212 |
| [strata-fx-european-refac-001](../tasks/refactor_haiku_20260301_031849--baseline-local-direct--strata-fx-european-refac-001.html) | [source](../../../benchmarks/ccb_refactor/strata-fx-european-refac-001) | `baseline-local-direct` | `passed` | 0.750 | 2 | 0.000 |
| [sgonly_strata-fx-european-refac-001](../tasks/refactor_haiku_20260301_031849--mcp-remote-direct--sgonly_strata-fx-european-refac-001.html) | [source](../../../benchmarks/ccb_refactor/strata-fx-european-refac-001) | `mcp-remote-direct` | `passed` | 0.610 | 3 | 0.556 |
| [terraform-eval-context-refac-001](../tasks/refactor_haiku_20260301_031849--baseline-local-direct--terraform-eval-context-refac-001.html) | [source](../../../benchmarks/ccb_refactor/terraform-eval-context-refac-001) | `baseline-local-direct` | `passed` | 1.000 | 3 | 0.000 |
| [sgonly_terraform-eval-context-refac-001](../tasks/refactor_haiku_20260301_031849--mcp-remote-direct--sgonly_terraform-eval-context-refac-001.html) | [source](../../../benchmarks/ccb_refactor/terraform-eval-context-refac-001) | `mcp-remote-direct` | `passed` | 0.833 | 3 | 0.281 |

## Multi-Run Variance

Tasks with multiple valid runs (40 task/config pairs).

| Task | Benchmark | Config | Runs | Mean | Std | Individual Rewards |
|---|---|---|---:|---:|---:|---|
| cilium-endpoint-manager-refac-001 | [source](../../../benchmarks/ccb_refactor/cilium-endpoint-manager-refac-001) | `baseline-local-direct` | 2 | 0.417 | 0.118 | 0.333, 0.500 |
| cilium-endpoint-manager-refac-001 | [source](../../../benchmarks/ccb_refactor/cilium-endpoint-manager-refac-001) | `mcp-remote-direct` | 4 | 0.417 | 0.096 | 0.500, 0.333, 0.500, 0.333 |
| curl-multi-process-refac-001 | [source](../../../benchmarks/ccb_refactor/curl-multi-process-refac-001) | `baseline-local-direct` | 3 | 1.000 | 0.000 | 1.000, 1.000, 1.000 |
| curl-multi-process-refac-001 | [source](../../../benchmarks/ccb_refactor/curl-multi-process-refac-001) | `mcp-remote-direct` | 4 | 1.000 | 0.000 | 1.000, 1.000, 1.000, 1.000 |
| django-request-factory-refac-001 | [source](../../../benchmarks/ccb_refactor/django-request-factory-refac-001) | `baseline-local-direct` | 3 | 0.833 | 0.000 | 0.833, 0.833, 0.833 |
| django-request-factory-refac-001 | [source](../../../benchmarks/ccb_refactor/django-request-factory-refac-001) | `mcp-remote-direct` | 4 | 0.708 | 0.083 | 0.667, 0.667, 0.667, 0.833 |
| envoy-listener-manager-refac-001 | [source](../../../benchmarks/ccb_refactor/envoy-listener-manager-refac-001) | `baseline-local-direct` | 2 | 1.000 | 0.000 | 1.000, 1.000 |
| envoy-listener-manager-refac-001 | [source](../../../benchmarks/ccb_refactor/envoy-listener-manager-refac-001) | `mcp-remote-direct` | 3 | 0.889 | 0.096 | 0.833, 1.000, 0.833 |
| etcd-raft-storage-refac-001 | [source](../../../benchmarks/ccb_refactor/etcd-raft-storage-refac-001) | `baseline-local-direct` | 3 | 0.944 | 0.096 | 0.833, 1.000, 1.000 |
| etcd-raft-storage-refac-001 | [source](../../../benchmarks/ccb_refactor/etcd-raft-storage-refac-001) | `mcp-remote-direct` | 4 | 0.750 | 0.397 | 0.167, 1.000, 0.833, 1.000 |
| flipt-dep-refactor-001 | [source](../../../benchmarks/ccb_refactor/flipt-dep-refactor-001) | `baseline-local-direct` | 3 | 0.483 | 0.325 | 0.150, 0.800, 0.500 |
| flipt-dep-refactor-001 | [source](../../../benchmarks/ccb_refactor/flipt-dep-refactor-001) | `mcp-remote-direct` | 4 | 0.325 | 0.117 | 0.500, 0.270, 0.280, 0.250 |
| flipt-flagexists-refactor-001 | [source](../../../benchmarks/ccb_refactor/flipt-flagexists-refactor-001) | `baseline-local-direct` | 3 | 0.567 | 0.275 | 0.300, 0.850, 0.550 |
| flipt-flagexists-refactor-001 | [source](../../../benchmarks/ccb_refactor/flipt-flagexists-refactor-001) | `mcp-remote-direct` | 3 | 0.527 | 0.236 | 0.550, 0.750, 0.280 |
| istio-discovery-server-refac-001 | [source](../../../benchmarks/ccb_refactor/istio-discovery-server-refac-001) | `baseline-local-direct` | 3 | 1.000 | 0.000 | 1.000, 1.000, 1.000 |
| istio-discovery-server-refac-001 | [source](../../../benchmarks/ccb_refactor/istio-discovery-server-refac-001) | `mcp-remote-direct` | 4 | 0.875 | 0.250 | 1.000, 1.000, 1.000, 0.500 |
| k8s-score-normalizer-refac-001 | [source](../../../benchmarks/ccb_refactor/k8s-score-normalizer-refac-001) | `baseline-local-direct` | 3 | 0.763 | 0.035 | 0.800, 0.760, 0.730 |
| k8s-score-normalizer-refac-001 | [source](../../../benchmarks/ccb_refactor/k8s-score-normalizer-refac-001) | `mcp-remote-direct` | 4 | 0.675 | 0.160 | 0.710, 0.450, 0.830, 0.710 |
| kafka-batch-accumulator-refac-001 | [source](../../../benchmarks/ccb_refactor/kafka-batch-accumulator-refac-001) | `baseline-local-direct` | 2 | 0.725 | 0.177 | 0.850, 0.600 |
| kafka-batch-accumulator-refac-001 | [source](../../../benchmarks/ccb_refactor/kafka-batch-accumulator-refac-001) | `mcp-remote-direct` | 3 | 0.663 | 0.029 | 0.680, 0.630, 0.680 |
| kubernetes-scheduler-profile-refac-001 | [source](../../../benchmarks/ccb_refactor/kubernetes-scheduler-profile-refac-001) | `baseline-local-direct` | 3 | 0.722 | 0.481 | 1.000, 1.000, 0.167 |
| kubernetes-scheduler-profile-refac-001 | [source](../../../benchmarks/ccb_refactor/kubernetes-scheduler-profile-refac-001) | `mcp-remote-direct` | 4 | 0.958 | 0.083 | 0.833, 1.000, 1.000, 1.000 |
| numpy-array-dispatch-refac-001 | [source](../../../benchmarks/ccb_refactor/numpy-array-dispatch-refac-001) | `baseline-local-direct` | 3 | 1.000 | 0.000 | 1.000, 1.000, 1.000 |
| numpy-array-dispatch-refac-001 | [source](../../../benchmarks/ccb_refactor/numpy-array-dispatch-refac-001) | `mcp-remote-direct` | 4 | 0.833 | 0.000 | 0.833, 0.833, 0.833, 0.833 |
| pandas-index-engine-refac-001 | [source](../../../benchmarks/ccb_refactor/pandas-index-engine-refac-001) | `baseline-local-direct` | 3 | 0.667 | 0.000 | 0.667, 0.667, 0.667 |
| pandas-index-engine-refac-001 | [source](../../../benchmarks/ccb_refactor/pandas-index-engine-refac-001) | `mcp-remote-direct` | 4 | 0.500 | 0.333 | 0.667, 0.000, 0.667, 0.667 |
| prometheus-query-engine-refac-001 | [source](../../../benchmarks/ccb_refactor/prometheus-query-engine-refac-001) | `baseline-local-direct` | 3 | 0.889 | 0.096 | 0.833, 1.000, 0.833 |
| prometheus-query-engine-refac-001 | [source](../../../benchmarks/ccb_refactor/prometheus-query-engine-refac-001) | `mcp-remote-direct` | 4 | 0.667 | 0.451 | 0.833, 1.000, 0.000, 0.833 |
| python-http-class-naming-refac-001 | [source](../../../benchmarks/ccb_refactor/python-http-class-naming-refac-001) | `baseline-local-direct` | 3 | 0.813 | 0.185 | 0.600, 0.920, 0.920 |
| python-http-class-naming-refac-001 | [source](../../../benchmarks/ccb_refactor/python-http-class-naming-refac-001) | `mcp-remote-direct` | 4 | 0.410 | 0.291 | 0.280, 0.200, 0.840, 0.320 |
| pytorch-optimizer-foreach-refac-001 | [source](../../../benchmarks/ccb_refactor/pytorch-optimizer-foreach-refac-001) | `baseline-local-direct` | 2 | 0.083 | 0.118 | 0.000, 0.167 |
| pytorch-optimizer-foreach-refac-001 | [source](../../../benchmarks/ccb_refactor/pytorch-optimizer-foreach-refac-001) | `mcp-remote-direct` | 4 | 0.250 | 0.167 | 0.167, 0.500, 0.167, 0.167 |
| rust-subtype-relation-refac-001 | [source](../../../benchmarks/ccb_refactor/rust-subtype-relation-refac-001) | `baseline-local-direct` | 3 | 0.830 | 0.070 | 0.750, 0.860, 0.880 |
| rust-subtype-relation-refac-001 | [source](../../../benchmarks/ccb_refactor/rust-subtype-relation-refac-001) | `mcp-remote-direct` | 5 | 0.822 | 0.045 | 0.790, 0.790, 0.820, 0.810, 0.900 |
| scikit-learn-estimator-tags-refac-001 | [source](../../../benchmarks/ccb_refactor/scikit-learn-estimator-tags-refac-001) | `baseline-local-direct` | 3 | 1.000 | 0.000 | 1.000, 1.000, 1.000 |
| scikit-learn-estimator-tags-refac-001 | [source](../../../benchmarks/ccb_refactor/scikit-learn-estimator-tags-refac-001) | `mcp-remote-direct` | 4 | 0.958 | 0.083 | 1.000, 1.000, 1.000, 0.833 |
| strata-fx-european-refac-001 | [source](../../../benchmarks/ccb_refactor/strata-fx-european-refac-001) | `baseline-local-direct` | 2 | 0.515 | 0.332 | 0.280, 0.750 |
| strata-fx-european-refac-001 | [source](../../../benchmarks/ccb_refactor/strata-fx-european-refac-001) | `mcp-remote-direct` | 3 | 0.727 | 0.177 | 0.640, 0.930, 0.610 |
| terraform-eval-context-refac-001 | [source](../../../benchmarks/ccb_refactor/terraform-eval-context-refac-001) | `baseline-local-direct` | 3 | 1.000 | 0.000 | 1.000, 1.000, 1.000 |
| terraform-eval-context-refac-001 | [source](../../../benchmarks/ccb_refactor/terraform-eval-context-refac-001) | `mcp-remote-direct` | 3 | 0.556 | 0.347 | 0.667, 0.167, 0.833 |
