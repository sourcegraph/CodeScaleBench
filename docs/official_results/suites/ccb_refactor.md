# ccb_refactor

## Run/Config Summary

| Run | Config | Valid Tasks | Mean Reward | Pass Rate |
|---|---|---:|---:|---:|
| [refactor_haiku_20260301_010758](../runs/refactor_haiku_20260301_010758.md) | `baseline-local-direct` | 20 | 0.791 | 0.950 |
| [refactor_haiku_20260301_010758](../runs/refactor_haiku_20260301_010758.md) | `mcp-remote-direct` | 20 | 0.737 | 0.950 |

## Tasks

| Task | Benchmark | Config | Status | Reward | Runs | MCP Ratio |
|---|---|---|---|---:|---:|---:|
| [cilium-endpoint-manager-refac-001](../tasks/refactor_haiku_20260301_010758--baseline-local-direct--cilium-endpoint-manager-refac-001.html) | [source](../../../benchmarks/ccb_refactor/cilium-endpoint-manager-refac-001) | `baseline-local-direct` | `passed` | 0.333 | 1 | 0.000 |
| [sgonly_cilium-endpoint-manager-refac-001](../tasks/refactor_haiku_20260301_010758--mcp-remote-direct--sgonly_cilium-endpoint-manager-refac-001.html) | [source](../../../benchmarks/ccb_refactor/cilium-endpoint-manager-refac-001) | `mcp-remote-direct` | `passed` | 0.500 | 3 | 0.090 |
| [curl-multi-process-refac-001](../tasks/refactor_haiku_20260301_010758--baseline-local-direct--curl-multi-process-refac-001.html) | [source](../../../benchmarks/ccb_refactor/curl-multi-process-refac-001) | `baseline-local-direct` | `passed` | 1.000 | 1 | 0.000 |
| [sgonly_curl-multi-process-refac-001](../tasks/refactor_haiku_20260301_010758--mcp-remote-direct--sgonly_curl-multi-process-refac-001.html) | [source](../../../benchmarks/ccb_refactor/curl-multi-process-refac-001) | `mcp-remote-direct` | `passed` | 1.000 | 2 | 0.179 |
| [django-request-factory-refac-001](../tasks/refactor_haiku_20260301_010758--baseline-local-direct--django-request-factory-refac-001.html) | [source](../../../benchmarks/ccb_refactor/django-request-factory-refac-001) | `baseline-local-direct` | `passed` | 0.833 | 1 | 0.000 |
| [sgonly_django-request-factory-refac-001](../tasks/refactor_haiku_20260301_010758--mcp-remote-direct--sgonly_django-request-factory-refac-001.html) | [source](../../../benchmarks/ccb_refactor/django-request-factory-refac-001) | `mcp-remote-direct` | `passed` | 0.667 | 2 | 0.169 |
| [envoy-listener-manager-refac-001](../tasks/refactor_haiku_20260301_010758--baseline-local-direct--envoy-listener-manager-refac-001.html) | [source](../../../benchmarks/ccb_refactor/envoy-listener-manager-refac-001) | `baseline-local-direct` | `passed` | 1.000 | 1 | 0.000 |
| [sgonly_envoy-listener-manager-refac-001](../tasks/refactor_haiku_20260301_010758--mcp-remote-direct--sgonly_envoy-listener-manager-refac-001.html) | [source](../../../benchmarks/ccb_refactor/envoy-listener-manager-refac-001) | `mcp-remote-direct` | `passed` | 1.000 | 2 | 0.417 |
| [etcd-raft-storage-refac-001](../tasks/refactor_haiku_20260301_010758--baseline-local-direct--etcd-raft-storage-refac-001.html) | [source](../../../benchmarks/ccb_refactor/etcd-raft-storage-refac-001) | `baseline-local-direct` | `passed` | 0.833 | 1 | 0.000 |
| [sgonly_etcd-raft-storage-refac-001](../tasks/refactor_haiku_20260301_010758--mcp-remote-direct--sgonly_etcd-raft-storage-refac-001.html) | [source](../../../benchmarks/ccb_refactor/etcd-raft-storage-refac-001) | `mcp-remote-direct` | `passed` | 1.000 | 2 | 0.329 |
| [flipt-dep-refactor-001](../tasks/refactor_haiku_20260301_010758--baseline-local-direct--flipt-dep-refactor-001.html) | [source](../../../benchmarks/ccb_refactor/flipt-dep-refactor-001) | `baseline-local-direct` | `passed` | 0.800 | 2 | - |
| [sgonly_flipt-dep-refactor-001](../tasks/refactor_haiku_20260301_010758--mcp-remote-direct--sgonly_flipt-dep-refactor-001.html) | [source](../../../benchmarks/ccb_refactor/flipt-dep-refactor-001) | `mcp-remote-direct` | `passed` | 0.280 | 3 | 0.600 |
| [flipt-flagexists-refactor-001](../tasks/refactor_haiku_20260301_010758--baseline-local-direct--flipt-flagexists-refactor-001.html) | [source](../../../benchmarks/ccb_refactor/flipt-flagexists-refactor-001) | `baseline-local-direct` | `passed` | 0.850 | 2 | 0.000 |
| [sgonly_flipt-flagexists-refactor-001](../tasks/refactor_haiku_20260301_010758--mcp-remote-direct--sgonly_flipt-flagexists-refactor-001.html) | [source](../../../benchmarks/ccb_refactor/flipt-flagexists-refactor-001) | `mcp-remote-direct` | `passed` | 0.750 | 2 | 0.253 |
| [istio-discovery-server-refac-001](../tasks/refactor_haiku_20260301_010758--baseline-local-direct--istio-discovery-server-refac-001.html) | [source](../../../benchmarks/ccb_refactor/istio-discovery-server-refac-001) | `baseline-local-direct` | `passed` | 1.000 | 1 | 0.000 |
| [sgonly_istio-discovery-server-refac-001](../tasks/refactor_haiku_20260301_010758--mcp-remote-direct--sgonly_istio-discovery-server-refac-001.html) | [source](../../../benchmarks/ccb_refactor/istio-discovery-server-refac-001) | `mcp-remote-direct` | `passed` | 1.000 | 2 | 0.093 |
| [k8s-score-normalizer-refac-001](../tasks/refactor_haiku_20260301_010758--baseline-local-direct--k8s-score-normalizer-refac-001.html) | [source](../../../benchmarks/ccb_refactor/k8s-score-normalizer-refac-001) | `baseline-local-direct` | `passed` | 0.760 | 2 | 0.000 |
| [sgonly_k8s-score-normalizer-refac-001](../tasks/refactor_haiku_20260301_010758--mcp-remote-direct--sgonly_k8s-score-normalizer-refac-001.html) | [source](../../../benchmarks/ccb_refactor/k8s-score-normalizer-refac-001) | `mcp-remote-direct` | `passed` | 0.830 | 3 | 0.477 |
| [kafka-batch-accumulator-refac-001](../tasks/refactor_haiku_20260301_010758--baseline-local-direct--kafka-batch-accumulator-refac-001.html) | [source](../../../benchmarks/ccb_refactor/kafka-batch-accumulator-refac-001) | `baseline-local-direct` | `passed` | 0.850 | 1 | 0.000 |
| [sgonly_kafka-batch-accumulator-refac-001](../tasks/refactor_haiku_20260301_010758--mcp-remote-direct--sgonly_kafka-batch-accumulator-refac-001.html) | [source](../../../benchmarks/ccb_refactor/kafka-batch-accumulator-refac-001) | `mcp-remote-direct` | `passed` | 0.630 | 2 | 0.135 |
| [kubernetes-scheduler-profile-refac-001](../tasks/refactor_haiku_20260301_010758--baseline-local-direct--kubernetes-scheduler-profile-refac-001.html) | [source](../../../benchmarks/ccb_refactor/kubernetes-scheduler-profile-refac-001) | `baseline-local-direct` | `passed` | 1.000 | 1 | 0.000 |
| [sgonly_kubernetes-scheduler-profile-refac-001](../tasks/refactor_haiku_20260301_010758--mcp-remote-direct--sgonly_kubernetes-scheduler-profile-refac-001.html) | [source](../../../benchmarks/ccb_refactor/kubernetes-scheduler-profile-refac-001) | `mcp-remote-direct` | `passed` | 1.000 | 2 | 0.213 |
| [numpy-array-dispatch-refac-001](../tasks/refactor_haiku_20260301_010758--baseline-local-direct--numpy-array-dispatch-refac-001.html) | [source](../../../benchmarks/ccb_refactor/numpy-array-dispatch-refac-001) | `baseline-local-direct` | `passed` | 1.000 | 1 | 0.000 |
| [sgonly_numpy-array-dispatch-refac-001](../tasks/refactor_haiku_20260301_010758--mcp-remote-direct--sgonly_numpy-array-dispatch-refac-001.html) | [source](../../../benchmarks/ccb_refactor/numpy-array-dispatch-refac-001) | `mcp-remote-direct` | `passed` | 0.833 | 2 | 0.526 |
| [pandas-index-engine-refac-001](../tasks/refactor_haiku_20260301_010758--baseline-local-direct--pandas-index-engine-refac-001.html) | [source](../../../benchmarks/ccb_refactor/pandas-index-engine-refac-001) | `baseline-local-direct` | `passed` | 0.667 | 1 | 0.000 |
| [sgonly_pandas-index-engine-refac-001](../tasks/refactor_haiku_20260301_010758--mcp-remote-direct--sgonly_pandas-index-engine-refac-001.html) | [source](../../../benchmarks/ccb_refactor/pandas-index-engine-refac-001) | `mcp-remote-direct` | `failed` | 0.000 | 2 | 0.130 |
| [prometheus-query-engine-refac-001](../tasks/refactor_haiku_20260301_010758--baseline-local-direct--prometheus-query-engine-refac-001.html) | [source](../../../benchmarks/ccb_refactor/prometheus-query-engine-refac-001) | `baseline-local-direct` | `passed` | 0.833 | 1 | 0.000 |
| [sgonly_prometheus-query-engine-refac-001](../tasks/refactor_haiku_20260301_010758--mcp-remote-direct--sgonly_prometheus-query-engine-refac-001.html) | [source](../../../benchmarks/ccb_refactor/prometheus-query-engine-refac-001) | `mcp-remote-direct` | `passed` | 1.000 | 2 | 0.256 |
| [python-http-class-naming-refac-001](../tasks/refactor_haiku_20260301_010758--baseline-local-direct--python-http-class-naming-refac-001.html) | [source](../../../benchmarks/ccb_refactor/python-http-class-naming-refac-001) | `baseline-local-direct` | `passed` | 0.920 | 2 | 0.000 |
| [sgonly_python-http-class-naming-refac-001](../tasks/refactor_haiku_20260301_010758--mcp-remote-direct--sgonly_python-http-class-naming-refac-001.html) | [source](../../../benchmarks/ccb_refactor/python-http-class-naming-refac-001) | `mcp-remote-direct` | `passed` | 0.840 | 3 | 0.191 |
| [pytorch-optimizer-foreach-refac-001](../tasks/refactor_haiku_20260301_010758--baseline-local-direct--pytorch-optimizer-foreach-refac-001.html) | [source](../../../benchmarks/ccb_refactor/pytorch-optimizer-foreach-refac-001) | `baseline-local-direct` | `failed` | 0.000 | 1 | 0.000 |
| [sgonly_pytorch-optimizer-foreach-refac-001](../tasks/refactor_haiku_20260301_010758--mcp-remote-direct--sgonly_pytorch-optimizer-foreach-refac-001.html) | [source](../../../benchmarks/ccb_refactor/pytorch-optimizer-foreach-refac-001) | `mcp-remote-direct` | `passed` | 0.500 | 2 | 0.543 |
| [rust-subtype-relation-refac-001](../tasks/refactor_haiku_20260301_010758--baseline-local-direct--rust-subtype-relation-refac-001.html) | [source](../../../benchmarks/ccb_refactor/rust-subtype-relation-refac-001) | `baseline-local-direct` | `passed` | 0.860 | 2 | 0.000 |
| [sgonly_rust-subtype-relation-refac-001](../tasks/refactor_haiku_20260301_010758--mcp-remote-direct--sgonly_rust-subtype-relation-refac-001.html) | [source](../../../benchmarks/ccb_refactor/rust-subtype-relation-refac-001) | `mcp-remote-direct` | `passed` | 0.810 | 4 | 0.712 |
| [scikit-learn-estimator-tags-refac-001](../tasks/refactor_haiku_20260301_010758--baseline-local-direct--scikit-learn-estimator-tags-refac-001.html) | [source](../../../benchmarks/ccb_refactor/scikit-learn-estimator-tags-refac-001) | `baseline-local-direct` | `passed` | 1.000 | 1 | 0.000 |
| [sgonly_scikit-learn-estimator-tags-refac-001](../tasks/refactor_haiku_20260301_010758--mcp-remote-direct--sgonly_scikit-learn-estimator-tags-refac-001.html) | [source](../../../benchmarks/ccb_refactor/scikit-learn-estimator-tags-refac-001) | `mcp-remote-direct` | `passed` | 1.000 | 2 | 0.172 |
| [strata-fx-european-refac-001](../tasks/refactor_haiku_20260301_010758--baseline-local-direct--strata-fx-european-refac-001.html) | [source](../../../benchmarks/ccb_refactor/strata-fx-european-refac-001) | `baseline-local-direct` | `passed` | 0.280 | 1 | 0.000 |
| [sgonly_strata-fx-european-refac-001](../tasks/refactor_haiku_20260301_010758--mcp-remote-direct--sgonly_strata-fx-european-refac-001.html) | [source](../../../benchmarks/ccb_refactor/strata-fx-european-refac-001) | `mcp-remote-direct` | `passed` | 0.930 | 2 | 0.500 |
| [terraform-eval-context-refac-001](../tasks/refactor_haiku_20260301_010758--baseline-local-direct--terraform-eval-context-refac-001.html) | [source](../../../benchmarks/ccb_refactor/terraform-eval-context-refac-001) | `baseline-local-direct` | `passed` | 1.000 | 1 | 0.000 |
| [sgonly_terraform-eval-context-refac-001](../tasks/refactor_haiku_20260301_010758--mcp-remote-direct--sgonly_terraform-eval-context-refac-001.html) | [source](../../../benchmarks/ccb_refactor/terraform-eval-context-refac-001) | `mcp-remote-direct` | `passed` | 0.167 | 2 | 0.368 |

## Multi-Run Variance

Tasks with multiple valid runs (25 task/config pairs).

| Task | Benchmark | Config | Runs | Mean | Std | Individual Rewards |
|---|---|---|---:|---:|---:|---|
| cilium-endpoint-manager-refac-001 | [source](../../../benchmarks/ccb_refactor/cilium-endpoint-manager-refac-001) | `mcp-remote-direct` | 3 | 0.444 | 0.096 | 0.500, 0.333, 0.500 |
| curl-multi-process-refac-001 | [source](../../../benchmarks/ccb_refactor/curl-multi-process-refac-001) | `mcp-remote-direct` | 2 | 1.000 | 0.000 | 1.000, 1.000 |
| django-request-factory-refac-001 | [source](../../../benchmarks/ccb_refactor/django-request-factory-refac-001) | `mcp-remote-direct` | 2 | 0.667 | 0.000 | 0.667, 0.667 |
| envoy-listener-manager-refac-001 | [source](../../../benchmarks/ccb_refactor/envoy-listener-manager-refac-001) | `mcp-remote-direct` | 2 | 0.917 | 0.118 | 0.833, 1.000 |
| etcd-raft-storage-refac-001 | [source](../../../benchmarks/ccb_refactor/etcd-raft-storage-refac-001) | `mcp-remote-direct` | 2 | 0.583 | 0.589 | 0.167, 1.000 |
| flipt-dep-refactor-001 | [source](../../../benchmarks/ccb_refactor/flipt-dep-refactor-001) | `baseline-local-direct` | 2 | 0.475 | 0.460 | 0.150, 0.800 |
| flipt-dep-refactor-001 | [source](../../../benchmarks/ccb_refactor/flipt-dep-refactor-001) | `mcp-remote-direct` | 3 | 0.350 | 0.130 | 0.500, 0.270, 0.280 |
| flipt-flagexists-refactor-001 | [source](../../../benchmarks/ccb_refactor/flipt-flagexists-refactor-001) | `baseline-local-direct` | 2 | 0.575 | 0.389 | 0.300, 0.850 |
| flipt-flagexists-refactor-001 | [source](../../../benchmarks/ccb_refactor/flipt-flagexists-refactor-001) | `mcp-remote-direct` | 2 | 0.650 | 0.141 | 0.550, 0.750 |
| istio-discovery-server-refac-001 | [source](../../../benchmarks/ccb_refactor/istio-discovery-server-refac-001) | `mcp-remote-direct` | 2 | 1.000 | 0.000 | 1.000, 1.000 |
| k8s-score-normalizer-refac-001 | [source](../../../benchmarks/ccb_refactor/k8s-score-normalizer-refac-001) | `baseline-local-direct` | 2 | 0.780 | 0.028 | 0.800, 0.760 |
| k8s-score-normalizer-refac-001 | [source](../../../benchmarks/ccb_refactor/k8s-score-normalizer-refac-001) | `mcp-remote-direct` | 3 | 0.663 | 0.194 | 0.710, 0.450, 0.830 |
| kafka-batch-accumulator-refac-001 | [source](../../../benchmarks/ccb_refactor/kafka-batch-accumulator-refac-001) | `mcp-remote-direct` | 2 | 0.655 | 0.035 | 0.680, 0.630 |
| kubernetes-scheduler-profile-refac-001 | [source](../../../benchmarks/ccb_refactor/kubernetes-scheduler-profile-refac-001) | `mcp-remote-direct` | 2 | 0.917 | 0.118 | 0.833, 1.000 |
| numpy-array-dispatch-refac-001 | [source](../../../benchmarks/ccb_refactor/numpy-array-dispatch-refac-001) | `mcp-remote-direct` | 2 | 0.833 | 0.000 | 0.833, 0.833 |
| pandas-index-engine-refac-001 | [source](../../../benchmarks/ccb_refactor/pandas-index-engine-refac-001) | `mcp-remote-direct` | 2 | 0.333 | 0.471 | 0.667, 0.000 |
| prometheus-query-engine-refac-001 | [source](../../../benchmarks/ccb_refactor/prometheus-query-engine-refac-001) | `mcp-remote-direct` | 2 | 0.917 | 0.118 | 0.833, 1.000 |
| python-http-class-naming-refac-001 | [source](../../../benchmarks/ccb_refactor/python-http-class-naming-refac-001) | `baseline-local-direct` | 2 | 0.760 | 0.226 | 0.600, 0.920 |
| python-http-class-naming-refac-001 | [source](../../../benchmarks/ccb_refactor/python-http-class-naming-refac-001) | `mcp-remote-direct` | 3 | 0.440 | 0.349 | 0.280, 0.200, 0.840 |
| pytorch-optimizer-foreach-refac-001 | [source](../../../benchmarks/ccb_refactor/pytorch-optimizer-foreach-refac-001) | `mcp-remote-direct` | 2 | 0.333 | 0.236 | 0.167, 0.500 |
| rust-subtype-relation-refac-001 | [source](../../../benchmarks/ccb_refactor/rust-subtype-relation-refac-001) | `baseline-local-direct` | 2 | 0.805 | 0.078 | 0.750, 0.860 |
| rust-subtype-relation-refac-001 | [source](../../../benchmarks/ccb_refactor/rust-subtype-relation-refac-001) | `mcp-remote-direct` | 4 | 0.802 | 0.015 | 0.790, 0.790, 0.820, 0.810 |
| scikit-learn-estimator-tags-refac-001 | [source](../../../benchmarks/ccb_refactor/scikit-learn-estimator-tags-refac-001) | `mcp-remote-direct` | 2 | 1.000 | 0.000 | 1.000, 1.000 |
| strata-fx-european-refac-001 | [source](../../../benchmarks/ccb_refactor/strata-fx-european-refac-001) | `mcp-remote-direct` | 2 | 0.785 | 0.205 | 0.640, 0.930 |
| terraform-eval-context-refac-001 | [source](../../../benchmarks/ccb_refactor/terraform-eval-context-refac-001) | `mcp-remote-direct` | 2 | 0.417 | 0.354 | 0.667, 0.167 |
