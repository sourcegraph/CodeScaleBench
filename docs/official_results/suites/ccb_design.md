# ccb_design

## Run/Config Summary

| Run | Config | Valid Tasks | Mean Reward | Pass Rate |
|---|---|---:|---:|---:|
| [ccb_design_haiku_20260228_025547](../runs/ccb_design_haiku_20260228_025547.md) | `mcp-remote-direct` | 13 | 0.751 | 1.000 |
| [design_haiku_20260301_071227](../runs/design_haiku_20260301_071227.md) | `baseline-local-direct` | 20 | 0.770 | 1.000 |
| [design_haiku_20260301_071227](../runs/design_haiku_20260301_071227.md) | `mcp-remote-direct` | 20 | 0.699 | 0.950 |

## Tasks

| Task | Benchmark | Config | Status | Reward | Runs | MCP Ratio |
|---|---|---|---|---:|---:|---:|
| [camel-routing-arch-001](../tasks/design_haiku_20260301_071227--baseline-local-direct--camel-routing-arch-001.html) | [source](../../../benchmarks/ccb_design/camel-routing-arch-001) | `baseline-local-direct` | `passed` | 0.800 | 6 | 0.000 |
| [sgonly_camel-routing-arch-001](../tasks/design_haiku_20260301_071227--mcp-remote-direct--sgonly_camel-routing-arch-001.html) | [source](../../../benchmarks/ccb_design/camel-routing-arch-001) | `mcp-remote-direct` | `passed` | 0.730 | 5 | 0.971 |
| [django-modeladmin-impact-001](../tasks/design_haiku_20260301_071227--baseline-local-direct--django-modeladmin-impact-001.html) | — | `baseline-local-direct` | `passed` | 1.000 | 6 | 0.000 |
| [mcp_django-modeladmin-impact-001_1Q2fNL](../tasks/ccb_design_haiku_20260228_025547--mcp-remote-direct--mcp_django-modeladmin-impact-001_1Q2fNL.html) | — | `mcp-remote-direct` | `passed` | 1.000 | 6 | 0.929 |
| [sgonly_django-modeladmin-impact-001](../tasks/design_haiku_20260301_071227--mcp-remote-direct--sgonly_django-modeladmin-impact-001.html) | — | `mcp-remote-direct` | `passed` | 1.000 | 6 | 0.875 |
| [django-orm-query-arch-001](../tasks/design_haiku_20260301_071227--baseline-local-direct--django-orm-query-arch-001.html) | [source](../../../benchmarks/ccb_design/django-orm-query-arch-001) | `baseline-local-direct` | `passed` | 0.790 | 6 | 0.000 |
| [mcp_django-orm-query-arch-001_6Ntzcs](../tasks/ccb_design_haiku_20260228_025547--mcp-remote-direct--mcp_django-orm-query-arch-001_6Ntzcs.html) | [source](../../../benchmarks/ccb_design/django-orm-query-arch-001) | `mcp-remote-direct` | `passed` | 0.880 | 6 | 0.951 |
| [sgonly_django-orm-query-arch-001](../tasks/design_haiku_20260301_071227--mcp-remote-direct--sgonly_django-orm-query-arch-001.html) | [source](../../../benchmarks/ccb_design/django-orm-query-arch-001) | `mcp-remote-direct` | `passed` | 0.850 | 6 | 0.967 |
| [django-pre-validate-signal-design-001](../tasks/design_haiku_20260301_071227--baseline-local-direct--django-pre-validate-signal-design-001.html) | [source](../../../benchmarks/ccb_design/django-pre-validate-signal-design-001) | `baseline-local-direct` | `passed` | 1.000 | 6 | 0.000 |
| [mcp_django-pre-validate-signal-design-001_oGZYof](../tasks/ccb_design_haiku_20260228_025547--mcp-remote-direct--mcp_django-pre-validate-signal-design-001_oGZYof.html) | [source](../../../benchmarks/ccb_design/django-pre-validate-signal-design-001) | `mcp-remote-direct` | `passed` | 0.900 | 6 | 0.412 |
| [sgonly_django-pre-validate-signal-design-001](../tasks/design_haiku_20260301_071227--mcp-remote-direct--sgonly_django-pre-validate-signal-design-001.html) | [source](../../../benchmarks/ccb_design/django-pre-validate-signal-design-001) | `mcp-remote-direct` | `passed` | 0.900 | 6 | 0.369 |
| [django-rate-limit-design-001](../tasks/design_haiku_20260301_071227--baseline-local-direct--django-rate-limit-design-001.html) | [source](../../../benchmarks/ccb_design/django-rate-limit-design-001) | `baseline-local-direct` | `passed` | 1.000 | 6 | 0.000 |
| [mcp_django-rate-limit-design-001_gfYegS](../tasks/ccb_design_haiku_20260228_025547--mcp-remote-direct--mcp_django-rate-limit-design-001_gfYegS.html) | [source](../../../benchmarks/ccb_design/django-rate-limit-design-001) | `mcp-remote-direct` | `passed` | 0.900 | 6 | 0.211 |
| [sgonly_django-rate-limit-design-001](../tasks/design_haiku_20260301_071227--mcp-remote-direct--sgonly_django-rate-limit-design-001.html) | [source](../../../benchmarks/ccb_design/django-rate-limit-design-001) | `mcp-remote-direct` | `passed` | 1.000 | 6 | 0.278 |
| [envoy-routeconfig-dep-chain-001](../tasks/design_haiku_20260301_071227--baseline-local-direct--envoy-routeconfig-dep-chain-001.html) | [source](../../../benchmarks/ccb_design/envoy-routeconfig-dep-chain-001) | `baseline-local-direct` | `passed` | 1.000 | 6 | 0.000 |
| [mcp_envoy-routeconfig-dep-chain-001_yTp2Rn](../tasks/ccb_design_haiku_20260228_025547--mcp-remote-direct--mcp_envoy-routeconfig-dep-chain-001_yTp2Rn.html) | [source](../../../benchmarks/ccb_design/envoy-routeconfig-dep-chain-001) | `mcp-remote-direct` | `passed` | 0.670 | 6 | 0.917 |
| [sgonly_envoy-routeconfig-dep-chain-001](../tasks/design_haiku_20260301_071227--mcp-remote-direct--sgonly_envoy-routeconfig-dep-chain-001.html) | [source](../../../benchmarks/ccb_design/envoy-routeconfig-dep-chain-001) | `mcp-remote-direct` | `passed` | 0.670 | 6 | 0.889 |
| [envoy-stream-aggregated-sym-001](../tasks/design_haiku_20260301_071227--baseline-local-direct--envoy-stream-aggregated-sym-001.html) | [source](../../../benchmarks/ccb_design/envoy-stream-aggregated-sym-001) | `baseline-local-direct` | `passed` | 0.810 | 6 | 0.000 |
| [mcp_envoy-stream-aggregated-sym-001_RqIhtU](../tasks/ccb_design_haiku_20260228_025547--mcp-remote-direct--mcp_envoy-stream-aggregated-sym-001_RqIhtU.html) | [source](../../../benchmarks/ccb_design/envoy-stream-aggregated-sym-001) | `mcp-remote-direct` | `passed` | 0.670 | 6 | 0.956 |
| [sgonly_envoy-stream-aggregated-sym-001](../tasks/design_haiku_20260301_071227--mcp-remote-direct--sgonly_envoy-stream-aggregated-sym-001.html) | [source](../../../benchmarks/ccb_design/envoy-stream-aggregated-sym-001) | `mcp-remote-direct` | `passed` | 0.450 | 6 | 0.955 |
| [etcd-grpc-api-upgrade-001](../tasks/design_haiku_20260301_071227--baseline-local-direct--etcd-grpc-api-upgrade-001.html) | [source](../../../benchmarks/ccb_design/etcd-grpc-api-upgrade-001) | `baseline-local-direct` | `passed` | 0.771 | 6 | 0.000 |
| [sgonly_etcd-grpc-api-upgrade-001](../tasks/design_haiku_20260301_071227--mcp-remote-direct--sgonly_etcd-grpc-api-upgrade-001.html) | [source](../../../benchmarks/ccb_design/etcd-grpc-api-upgrade-001) | `mcp-remote-direct` | `failed` | 0.000 | 5 | 0.378 |
| [flink-checkpoint-arch-001](../tasks/design_haiku_20260301_071227--baseline-local-direct--flink-checkpoint-arch-001.html) | [source](../../../benchmarks/ccb_design/flink-checkpoint-arch-001) | `baseline-local-direct` | `passed` | 0.400 | 6 | 0.000 |
| [sgonly_flink-checkpoint-arch-001](../tasks/design_haiku_20260301_071227--mcp-remote-direct--sgonly_flink-checkpoint-arch-001.html) | [source](../../../benchmarks/ccb_design/flink-checkpoint-arch-001) | `mcp-remote-direct` | `passed` | 0.780 | 5 | 0.964 |
| [flipt-protobuf-metadata-design-001](../tasks/design_haiku_20260301_071227--baseline-local-direct--flipt-protobuf-metadata-design-001.html) | [source](../../../benchmarks/ccb_design/flipt-protobuf-metadata-design-001) | `baseline-local-direct` | `passed` | 1.000 | 6 | 0.000 |
| [mcp_flipt-protobuf-metadata-design-001_VTUIt4](../tasks/ccb_design_haiku_20260228_025547--mcp-remote-direct--mcp_flipt-protobuf-metadata-design-001_VTUIt4.html) | [source](../../../benchmarks/ccb_design/flipt-protobuf-metadata-design-001) | `mcp-remote-direct` | `passed` | 0.750 | 5 | 0.333 |
| [sgonly_flipt-protobuf-metadata-design-001](../tasks/design_haiku_20260301_071227--mcp-remote-direct--sgonly_flipt-protobuf-metadata-design-001.html) | [source](../../../benchmarks/ccb_design/flipt-protobuf-metadata-design-001) | `mcp-remote-direct` | `passed` | 0.750 | 5 | 0.313 |
| [flipt-transitive-deps-001](../tasks/design_haiku_20260301_071227--baseline-local-direct--flipt-transitive-deps-001.html) | [source](../../../benchmarks/ccb_design/flipt-transitive-deps-001) | `baseline-local-direct` | `passed` | 0.778 | 6 | 0.000 |
| [mcp_flipt-transitive-deps-001_TV5FV0](../tasks/ccb_design_haiku_20260228_025547--mcp-remote-direct--mcp_flipt-transitive-deps-001_TV5FV0.html) | [source](../../../benchmarks/ccb_design/flipt-transitive-deps-001) | `mcp-remote-direct` | `passed` | 0.648 | 6 | 0.977 |
| [sgonly_flipt-transitive-deps-001](../tasks/design_haiku_20260301_071227--mcp-remote-direct--sgonly_flipt-transitive-deps-001.html) | [source](../../../benchmarks/ccb_design/flipt-transitive-deps-001) | `mcp-remote-direct` | `passed` | 0.467 | 6 | 0.977 |
| [k8s-crd-lifecycle-arch-001](../tasks/design_haiku_20260301_071227--baseline-local-direct--k8s-crd-lifecycle-arch-001.html) | [source](../../../benchmarks/ccb_design/k8s-crd-lifecycle-arch-001) | `baseline-local-direct` | `passed` | 0.660 | 6 | 0.000 |
| [sgonly_k8s-crd-lifecycle-arch-001](../tasks/design_haiku_20260301_071227--mcp-remote-direct--sgonly_k8s-crd-lifecycle-arch-001.html) | [source](../../../benchmarks/ccb_design/k8s-crd-lifecycle-arch-001) | `mcp-remote-direct` | `passed` | 0.680 | 5 | 0.955 |
| [k8s-dra-allocation-impact-001](../tasks/design_haiku_20260301_071227--baseline-local-direct--k8s-dra-allocation-impact-001.html) | — | `baseline-local-direct` | `passed` | 1.000 | 6 | 0.000 |
| [sgonly_k8s-dra-allocation-impact-001](../tasks/design_haiku_20260301_071227--mcp-remote-direct--sgonly_k8s-dra-allocation-impact-001.html) | — | `mcp-remote-direct` | `passed` | 0.900 | 5 | 0.958 |
| [k8s-scheduler-arch-001](../tasks/design_haiku_20260301_071227--baseline-local-direct--k8s-scheduler-arch-001.html) | — | `baseline-local-direct` | `passed` | 0.700 | 6 | 0.000 |
| [sgonly_k8s-scheduler-arch-001](../tasks/design_haiku_20260301_071227--mcp-remote-direct--sgonly_k8s-scheduler-arch-001.html) | — | `mcp-remote-direct` | `passed` | 0.680 | 5 | 0.944 |
| [k8s-sharedinformer-sym-001](../tasks/design_haiku_20260301_071227--baseline-local-direct--k8s-sharedinformer-sym-001.html) | — | `baseline-local-direct` | `passed` | 0.610 | 6 | 0.000 |
| [mcp_k8s-sharedinformer-sym-001_r1uWY5](../tasks/ccb_design_haiku_20260228_025547--mcp-remote-direct--mcp_k8s-sharedinformer-sym-001_r1uWY5.html) | — | `mcp-remote-direct` | `passed` | 0.710 | 6 | 0.977 |
| [sgonly_k8s-sharedinformer-sym-001](../tasks/design_haiku_20260301_071227--mcp-remote-direct--sgonly_k8s-sharedinformer-sym-001.html) | — | `mcp-remote-direct` | `passed` | 0.690 | 6 | 0.980 |
| [k8s-typemeta-dep-chain-001](../tasks/design_haiku_20260301_071227--baseline-local-direct--k8s-typemeta-dep-chain-001.html) | [source](../../../benchmarks/ccb_design/k8s-typemeta-dep-chain-001) | `baseline-local-direct` | `passed` | 0.330 | 6 | 0.000 |
| [mcp_k8s-typemeta-dep-chain-001_uTlaTc](../tasks/ccb_design_haiku_20260228_025547--mcp-remote-direct--mcp_k8s-typemeta-dep-chain-001_uTlaTc.html) | [source](../../../benchmarks/ccb_design/k8s-typemeta-dep-chain-001) | `mcp-remote-direct` | `passed` | 0.670 | 6 | 0.700 |
| [sgonly_k8s-typemeta-dep-chain-001](../tasks/design_haiku_20260301_071227--mcp-remote-direct--sgonly_k8s-typemeta-dep-chain-001.html) | [source](../../../benchmarks/ccb_design/k8s-typemeta-dep-chain-001) | `mcp-remote-direct` | `passed` | 0.670 | 6 | 0.889 |
| [kafka-flink-streaming-arch-001](../tasks/design_haiku_20260301_071227--baseline-local-direct--kafka-flink-streaming-arch-001.html) | [source](../../../benchmarks/ccb_design/kafka-flink-streaming-arch-001) | `baseline-local-direct` | `passed` | 0.960 | 6 | 0.000 |
| [sgonly_kafka-flink-streaming-arch-001](../tasks/design_haiku_20260301_071227--mcp-remote-direct--sgonly_kafka-flink-streaming-arch-001.html) | [source](../../../benchmarks/ccb_design/kafka-flink-streaming-arch-001) | `mcp-remote-direct` | `passed` | 0.690 | 5 | 0.974 |
| [postgres-query-exec-arch-001](../tasks/design_haiku_20260301_071227--baseline-local-direct--postgres-query-exec-arch-001.html) | [source](../../../benchmarks/ccb_design/postgres-query-exec-arch-001) | `baseline-local-direct` | `passed` | 0.780 | 6 | 0.000 |
| [mcp_postgres-query-exec-arch-001_A0vfQ4](../tasks/ccb_design_haiku_20260228_025547--mcp-remote-direct--mcp_postgres-query-exec-arch-001_A0vfQ4.html) | [source](../../../benchmarks/ccb_design/postgres-query-exec-arch-001) | `mcp-remote-direct` | `passed` | 1.000 | 6 | 0.878 |
| [sgonly_postgres-query-exec-arch-001](../tasks/design_haiku_20260301_071227--mcp-remote-direct--sgonly_postgres-query-exec-arch-001.html) | [source](../../../benchmarks/ccb_design/postgres-query-exec-arch-001) | `mcp-remote-direct` | `passed` | 0.930 | 6 | 0.974 |
| [quantlib-barrier-pricing-arch-001](../tasks/design_haiku_20260301_071227--baseline-local-direct--quantlib-barrier-pricing-arch-001.html) | — | `baseline-local-direct` | `passed` | 0.870 | 6 | 0.000 |
| [mcp_quantlib-barrier-pricing-arch-001_4uwsVP](../tasks/ccb_design_haiku_20260228_025547--mcp-remote-direct--mcp_quantlib-barrier-pricing-arch-001_4uwsVP.html) | — | `mcp-remote-direct` | `passed` | 0.890 | 6 | 0.962 |
| [sgonly_quantlib-barrier-pricing-arch-001](../tasks/design_haiku_20260301_071227--mcp-remote-direct--sgonly_quantlib-barrier-pricing-arch-001.html) | — | `mcp-remote-direct` | `passed` | 0.920 | 6 | 0.963 |
| [terraform-provider-iface-sym-001](../tasks/design_haiku_20260301_071227--baseline-local-direct--terraform-provider-iface-sym-001.html) | — | `baseline-local-direct` | `passed` | 0.140 | 6 | 0.000 |
| [mcp_terraform-provider-iface-sym-001_JJ1WXA](../tasks/ccb_design_haiku_20260228_025547--mcp-remote-direct--mcp_terraform-provider-iface-sym-001_JJ1WXA.html) | — | `mcp-remote-direct` | `passed` | 0.080 | 6 | 0.971 |
| [sgonly_terraform-provider-iface-sym-001](../tasks/design_haiku_20260301_071227--mcp-remote-direct--sgonly_terraform-provider-iface-sym-001.html) | — | `mcp-remote-direct` | `passed` | 0.230 | 6 | 0.884 |

## Multi-Run Variance

Tasks with multiple valid runs (28 task/config pairs).

| Task | Benchmark | Config | Runs | Mean | Std | Individual Rewards |
|---|---|---|---:|---:|---:|---|
| camel-routing-arch-001 | [source](../../../benchmarks/ccb_design/camel-routing-arch-001) | `baseline-local-direct` | 6 | 0.847 | 0.029 | 0.870, 0.870, 0.860, 0.860, 0.820, 0.800 |
| camel-routing-arch-001 | [source](../../../benchmarks/ccb_design/camel-routing-arch-001) | `mcp-remote-direct` | 4 | 0.660 | 0.174 | 0.400, 0.750, 0.760, 0.730 |
| django-orm-query-arch-001 | [source](../../../benchmarks/ccb_design/django-orm-query-arch-001) | `baseline-local-direct` | 5 | 0.748 | 0.164 | 0.460, 0.840, 0.790, 0.860, 0.790 |
| django-orm-query-arch-001 | [source](../../../benchmarks/ccb_design/django-orm-query-arch-001) | `mcp-remote-direct` | 5 | 0.896 | 0.034 | 0.880, 0.900, 0.940, 0.910, 0.850 |
| django-pre-validate-signal-design-001 | [source](../../../benchmarks/ccb_design/django-pre-validate-signal-design-001) | `baseline-local-direct` | 5 | 0.870 | 0.239 | 0.450, 0.900, 1.000, 1.000, 1.000 |
| django-pre-validate-signal-design-001 | [source](../../../benchmarks/ccb_design/django-pre-validate-signal-design-001) | `mcp-remote-direct` | 5 | 0.920 | 0.045 | 0.900, 1.000, 0.900, 0.900, 0.900 |
| django-rate-limit-design-001 | [source](../../../benchmarks/ccb_design/django-rate-limit-design-001) | `baseline-local-direct` | 5 | 0.810 | 0.425 | 0.050, 1.000, 1.000, 1.000, 1.000 |
| django-rate-limit-design-001 | [source](../../../benchmarks/ccb_design/django-rate-limit-design-001) | `mcp-remote-direct` | 5 | 0.980 | 0.045 | 0.900, 1.000, 1.000, 1.000, 1.000 |
| envoy-routeconfig-dep-chain-001 | [source](../../../benchmarks/ccb_design/envoy-routeconfig-dep-chain-001) | `baseline-local-direct` | 5 | 1.000 | 0.000 | 1.000, 1.000, 1.000, 1.000, 1.000 |
| envoy-routeconfig-dep-chain-001 | [source](../../../benchmarks/ccb_design/envoy-routeconfig-dep-chain-001) | `mcp-remote-direct` | 5 | 0.736 | 0.148 | 0.670, 0.670, 1.000, 0.670, 0.670 |
| envoy-stream-aggregated-sym-001 | [source](../../../benchmarks/ccb_design/envoy-stream-aggregated-sym-001) | `baseline-local-direct` | 5 | 0.696 | 0.131 | 0.740, 0.470, 0.720, 0.740, 0.810 |
| envoy-stream-aggregated-sym-001 | [source](../../../benchmarks/ccb_design/envoy-stream-aggregated-sym-001) | `mcp-remote-direct` | 5 | 0.564 | 0.083 | 0.670, 0.520, 0.580, 0.600, 0.450 |
| etcd-grpc-api-upgrade-001 | [source](../../../benchmarks/ccb_design/etcd-grpc-api-upgrade-001) | `baseline-local-direct` | 6 | 0.514 | 0.398 | 0.000, 0.000, 0.771, 0.771, 0.771, 0.771 |
| etcd-grpc-api-upgrade-001 | [source](../../../benchmarks/ccb_design/etcd-grpc-api-upgrade-001) | `mcp-remote-direct` | 4 | 0.436 | 0.371 | 0.714, 0.771, 0.257, 0.000 |
| flink-checkpoint-arch-001 | [source](../../../benchmarks/ccb_design/flink-checkpoint-arch-001) | `baseline-local-direct` | 6 | 0.655 | 0.199 | 0.800, 0.800, 0.400, 0.790, 0.740, 0.400 |
| flink-checkpoint-arch-001 | [source](../../../benchmarks/ccb_design/flink-checkpoint-arch-001) | `mcp-remote-direct` | 4 | 0.748 | 0.033 | 0.710, 0.770, 0.730, 0.780 |
| flipt-protobuf-metadata-design-001 | [source](../../../benchmarks/ccb_design/flipt-protobuf-metadata-design-001) | `baseline-local-direct` | 5 | 0.696 | 0.450 | 0.480, 1.000, 0.000, 1.000, 1.000 |
| flipt-protobuf-metadata-design-001 | [source](../../../benchmarks/ccb_design/flipt-protobuf-metadata-design-001) | `mcp-remote-direct` | 4 | 0.812 | 0.125 | 0.750, 1.000, 0.750, 0.750 |
| flipt-transitive-deps-001 | [source](../../../benchmarks/ccb_design/flipt-transitive-deps-001) | `baseline-local-direct` | 5 | 0.696 | 0.130 | 0.533, 0.711, 0.600, 0.856, 0.778 |
| flipt-transitive-deps-001 | [source](../../../benchmarks/ccb_design/flipt-transitive-deps-001) | `mcp-remote-direct` | 5 | 0.667 | 0.140 | 0.648, 0.711, 0.656, 0.856, 0.467 |
| k8s-crd-lifecycle-arch-001 | [source](../../../benchmarks/ccb_design/k8s-crd-lifecycle-arch-001) | `baseline-local-direct` | 6 | 0.623 | 0.117 | 0.690, 0.690, 0.590, 0.710, 0.400, 0.660 |
| k8s-crd-lifecycle-arch-001 | [source](../../../benchmarks/ccb_design/k8s-crd-lifecycle-arch-001) | `mcp-remote-direct` | 4 | 0.708 | 0.059 | 0.640, 0.770, 0.740, 0.680 |
| k8s-typemeta-dep-chain-001 | [source](../../../benchmarks/ccb_design/k8s-typemeta-dep-chain-001) | `baseline-local-direct` | 5 | 0.668 | 0.237 | 0.670, 0.670, 1.000, 0.670, 0.330 |
| k8s-typemeta-dep-chain-001 | [source](../../../benchmarks/ccb_design/k8s-typemeta-dep-chain-001) | `mcp-remote-direct` | 5 | 0.670 | 0.000 | 0.670, 0.670, 0.670, 0.670, 0.670 |
| kafka-flink-streaming-arch-001 | [source](../../../benchmarks/ccb_design/kafka-flink-streaming-arch-001) | `baseline-local-direct` | 6 | 0.957 | 0.029 | 0.970, 0.970, 0.980, 0.900, 0.960, 0.960 |
| kafka-flink-streaming-arch-001 | [source](../../../benchmarks/ccb_design/kafka-flink-streaming-arch-001) | `mcp-remote-direct` | 4 | 0.472 | 0.145 | 0.400, 0.400, 0.400, 0.690 |
| postgres-query-exec-arch-001 | [source](../../../benchmarks/ccb_design/postgres-query-exec-arch-001) | `baseline-local-direct` | 5 | 0.802 | 0.051 | 0.740, 0.780, 0.860, 0.850, 0.780 |
| postgres-query-exec-arch-001 | [source](../../../benchmarks/ccb_design/postgres-query-exec-arch-001) | `mcp-remote-direct` | 5 | 0.916 | 0.103 | 1.000, 1.000, 0.900, 0.750, 0.930 |
