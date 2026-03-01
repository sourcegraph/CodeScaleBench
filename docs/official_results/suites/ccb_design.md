# ccb_design

## Run/Config Summary

| Run | Config | Valid Tasks | Mean Reward | Pass Rate |
|---|---|---:|---:|---:|
| [ccb_design_haiku_20260226_015500_backfill](../runs/ccb_design_haiku_20260226_015500_backfill.md) | `baseline-local-direct` | 7 | 0.723 | 0.857 |
| [ccb_design_haiku_20260228_025547](../runs/ccb_design_haiku_20260228_025547.md) | `baseline-local-direct` | 13 | 0.598 | 1.000 |
| [ccb_design_haiku_20260228_025547](../runs/ccb_design_haiku_20260228_025547.md) | `mcp-remote-direct` | 13 | 0.751 | 1.000 |
| [design_haiku_20260223_124652](../runs/design_haiku_20260223_124652.md) | `mcp-remote-direct` | 20 | 0.718 | 1.000 |

## Tasks

| Task | Benchmark | Config | Status | Reward | Runs | MCP Ratio |
|---|---|---|---|---:|---:|---:|
| [camel-routing-arch-001](../tasks/ccb_design_haiku_20260226_015500_backfill--baseline-local-direct--camel-routing-arch-001.html) | [source](../../../benchmarks/ccb_design/camel-routing-arch-001) | `baseline-local-direct` | `passed` | 0.870 | 2 | 0.000 |
| [sgonly_camel-routing-arch-001](../tasks/design_haiku_20260223_124652--mcp-remote-direct--sgonly_camel-routing-arch-001.html) | [source](../../../benchmarks/ccb_design/camel-routing-arch-001) | `mcp-remote-direct` | `passed` | 0.730 | 2 | 0.966 |
| [django-modeladmin-impact-001](../tasks/ccb_design_haiku_20260228_025547--baseline-local-direct--django-modeladmin-impact-001.html) | [source](../../../benchmarks/ccb_design/django-modeladmin-impact-001) | `baseline-local-direct` | `passed` | 1.000 | 3 | 0.000 |
| [mcp_django-modeladmin-impact-001_1Q2fNL](../tasks/ccb_design_haiku_20260228_025547--mcp-remote-direct--mcp_django-modeladmin-impact-001_1Q2fNL.html) | [source](../../../benchmarks/ccb_design/django-modeladmin-impact-001) | `mcp-remote-direct` | `passed` | 1.000 | 3 | 0.929 |
| [sgonly_django-modeladmin-impact-001](../tasks/design_haiku_20260223_124652--mcp-remote-direct--sgonly_django-modeladmin-impact-001.html) | [source](../../../benchmarks/ccb_design/django-modeladmin-impact-001) | `mcp-remote-direct` | `passed` | 1.000 | 3 | 0.939 |
| [django-orm-query-arch-001](../tasks/ccb_design_haiku_20260228_025547--baseline-local-direct--django-orm-query-arch-001.html) | [source](../../../benchmarks/ccb_design/django-orm-query-arch-001) | `baseline-local-direct` | `passed` | 0.460 | 3 | 0.000 |
| [mcp_django-orm-query-arch-001_6Ntzcs](../tasks/ccb_design_haiku_20260228_025547--mcp-remote-direct--mcp_django-orm-query-arch-001_6Ntzcs.html) | [source](../../../benchmarks/ccb_design/django-orm-query-arch-001) | `mcp-remote-direct` | `passed` | 0.880 | 3 | 0.951 |
| [sgonly_django-orm-query-arch-001](../tasks/design_haiku_20260223_124652--mcp-remote-direct--sgonly_django-orm-query-arch-001.html) | [source](../../../benchmarks/ccb_design/django-orm-query-arch-001) | `mcp-remote-direct` | `passed` | 0.990 | 3 | 0.969 |
| [django-pre-validate-signal-design-001](../tasks/ccb_design_haiku_20260228_025547--baseline-local-direct--django-pre-validate-signal-design-001.html) | [source](../../../benchmarks/ccb_design/django-pre-validate-signal-design-001) | `baseline-local-direct` | `passed` | 0.450 | 3 | 0.000 |
| [mcp_django-pre-validate-signal-design-001_oGZYof](../tasks/ccb_design_haiku_20260228_025547--mcp-remote-direct--mcp_django-pre-validate-signal-design-001_oGZYof.html) | [source](../../../benchmarks/ccb_design/django-pre-validate-signal-design-001) | `mcp-remote-direct` | `passed` | 0.900 | 3 | 0.412 |
| [sgonly_django-pre-validate-signal-design-001](../tasks/design_haiku_20260223_124652--mcp-remote-direct--sgonly_django-pre-validate-signal-design-001.html) | [source](../../../benchmarks/ccb_design/django-pre-validate-signal-design-001) | `mcp-remote-direct` | `passed` | 1.000 | 3 | 0.157 |
| [django-rate-limit-design-001](../tasks/ccb_design_haiku_20260228_025547--baseline-local-direct--django-rate-limit-design-001.html) | [source](../../../benchmarks/ccb_design/django-rate-limit-design-001) | `baseline-local-direct` | `passed` | 0.050 | 3 | 0.000 |
| [mcp_django-rate-limit-design-001_gfYegS](../tasks/ccb_design_haiku_20260228_025547--mcp-remote-direct--mcp_django-rate-limit-design-001_gfYegS.html) | [source](../../../benchmarks/ccb_design/django-rate-limit-design-001) | `mcp-remote-direct` | `passed` | 0.900 | 3 | 0.211 |
| [sgonly_django-rate-limit-design-001](../tasks/design_haiku_20260223_124652--mcp-remote-direct--sgonly_django-rate-limit-design-001.html) | [source](../../../benchmarks/ccb_design/django-rate-limit-design-001) | `mcp-remote-direct` | `passed` | 1.000 | 3 | 0.333 |
| [envoy-routeconfig-dep-chain-001](../tasks/ccb_design_haiku_20260228_025547--baseline-local-direct--envoy-routeconfig-dep-chain-001.html) | [source](../../../benchmarks/ccb_design/envoy-routeconfig-dep-chain-001) | `baseline-local-direct` | `passed` | 1.000 | 3 | 0.000 |
| [mcp_envoy-routeconfig-dep-chain-001_yTp2Rn](../tasks/ccb_design_haiku_20260228_025547--mcp-remote-direct--mcp_envoy-routeconfig-dep-chain-001_yTp2Rn.html) | [source](../../../benchmarks/ccb_design/envoy-routeconfig-dep-chain-001) | `mcp-remote-direct` | `passed` | 0.670 | 3 | 0.917 |
| [sgonly_envoy-routeconfig-dep-chain-001](../tasks/design_haiku_20260223_124652--mcp-remote-direct--sgonly_envoy-routeconfig-dep-chain-001.html) | [source](../../../benchmarks/ccb_design/envoy-routeconfig-dep-chain-001) | `mcp-remote-direct` | `passed` | 1.000 | 3 | 0.857 |
| [envoy-stream-aggregated-sym-001](../tasks/ccb_design_haiku_20260228_025547--baseline-local-direct--envoy-stream-aggregated-sym-001.html) | [source](../../../benchmarks/ccb_design/envoy-stream-aggregated-sym-001) | `baseline-local-direct` | `passed` | 0.740 | 3 | 0.000 |
| [mcp_envoy-stream-aggregated-sym-001_RqIhtU](../tasks/ccb_design_haiku_20260228_025547--mcp-remote-direct--mcp_envoy-stream-aggregated-sym-001_RqIhtU.html) | [source](../../../benchmarks/ccb_design/envoy-stream-aggregated-sym-001) | `mcp-remote-direct` | `passed` | 0.670 | 3 | 0.956 |
| [sgonly_envoy-stream-aggregated-sym-001](../tasks/design_haiku_20260223_124652--mcp-remote-direct--sgonly_envoy-stream-aggregated-sym-001.html) | [source](../../../benchmarks/ccb_design/envoy-stream-aggregated-sym-001) | `mcp-remote-direct` | `passed` | 0.320 | 3 | 0.971 |
| [etcd-grpc-api-upgrade-001](../tasks/ccb_design_haiku_20260226_015500_backfill--baseline-local-direct--etcd-grpc-api-upgrade-001.html) | [source](../../../benchmarks/ccb_design/etcd-grpc-api-upgrade-001) | `baseline-local-direct` | `failed` | 0.000 | 2 | 0.000 |
| [sgonly_etcd-grpc-api-upgrade-001](../tasks/design_haiku_20260223_124652--mcp-remote-direct--sgonly_etcd-grpc-api-upgrade-001.html) | [source](../../../benchmarks/ccb_design/etcd-grpc-api-upgrade-001) | `mcp-remote-direct` | `passed` | 0.714 | 2 | 0.108 |
| [flink-checkpoint-arch-001](../tasks/ccb_design_haiku_20260226_015500_backfill--baseline-local-direct--flink-checkpoint-arch-001.html) | [source](../../../benchmarks/ccb_design/flink-checkpoint-arch-001) | `baseline-local-direct` | `passed` | 0.800 | 2 | 0.000 |
| [sgonly_flink-checkpoint-arch-001](../tasks/design_haiku_20260223_124652--mcp-remote-direct--sgonly_flink-checkpoint-arch-001.html) | [source](../../../benchmarks/ccb_design/flink-checkpoint-arch-001) | `mcp-remote-direct` | `passed` | 0.730 | 2 | 0.958 |
| [flipt-protobuf-metadata-design-001](../tasks/ccb_design_haiku_20260228_025547--baseline-local-direct--flipt-protobuf-metadata-design-001.html) | [source](../../../benchmarks/ccb_design/flipt-protobuf-metadata-design-001) | `baseline-local-direct` | `passed` | 0.480 | 3 | 0.000 |
| [mcp_flipt-protobuf-metadata-design-001_VTUIt4](../tasks/ccb_design_haiku_20260228_025547--mcp-remote-direct--mcp_flipt-protobuf-metadata-design-001_VTUIt4.html) | [source](../../../benchmarks/ccb_design/flipt-protobuf-metadata-design-001) | `mcp-remote-direct` | `passed` | 0.750 | 3 | 0.333 |
| [sgonly_flipt-protobuf-metadata-design-001](../tasks/design_haiku_20260223_124652--mcp-remote-direct--sgonly_flipt-protobuf-metadata-design-001.html) | [source](../../../benchmarks/ccb_design/flipt-protobuf-metadata-design-001) | `mcp-remote-direct` | `passed` | 0.330 | 3 | 0.345 |
| [flipt-transitive-deps-001](../tasks/ccb_design_haiku_20260228_025547--baseline-local-direct--flipt-transitive-deps-001.html) | [source](../../../benchmarks/ccb_design/flipt-transitive-deps-001) | `baseline-local-direct` | `passed` | 0.533 | 3 | 0.000 |
| [mcp_flipt-transitive-deps-001_TV5FV0](../tasks/ccb_design_haiku_20260228_025547--mcp-remote-direct--mcp_flipt-transitive-deps-001_TV5FV0.html) | [source](../../../benchmarks/ccb_design/flipt-transitive-deps-001) | `mcp-remote-direct` | `passed` | 0.648 | 3 | 0.977 |
| [sgonly_flipt-transitive-deps-001](../tasks/design_haiku_20260223_124652--mcp-remote-direct--sgonly_flipt-transitive-deps-001.html) | [source](../../../benchmarks/ccb_design/flipt-transitive-deps-001) | `mcp-remote-direct` | `passed` | 0.711 | 3 | 0.949 |
| [k8s-crd-lifecycle-arch-001](../tasks/ccb_design_haiku_20260226_015500_backfill--baseline-local-direct--k8s-crd-lifecycle-arch-001.html) | [source](../../../benchmarks/ccb_design/k8s-crd-lifecycle-arch-001) | `baseline-local-direct` | `passed` | 0.690 | 2 | 0.000 |
| [sgonly_k8s-crd-lifecycle-arch-001](../tasks/design_haiku_20260223_124652--mcp-remote-direct--sgonly_k8s-crd-lifecycle-arch-001.html) | [source](../../../benchmarks/ccb_design/k8s-crd-lifecycle-arch-001) | `mcp-remote-direct` | `passed` | 0.770 | 2 | 0.829 |
| [k8s-dra-allocation-impact-001](../tasks/ccb_design_haiku_20260226_015500_backfill--baseline-local-direct--k8s-dra-allocation-impact-001.html) | [source](../../../benchmarks/ccb_design/k8s-dra-allocation-impact-001) | `baseline-local-direct` | `passed` | 1.000 | 2 | 0.000 |
| [sgonly_k8s-dra-allocation-impact-001](../tasks/design_haiku_20260223_124652--mcp-remote-direct--sgonly_k8s-dra-allocation-impact-001.html) | [source](../../../benchmarks/ccb_design/k8s-dra-allocation-impact-001) | `mcp-remote-direct` | `passed` | 0.900 | 2 | 0.913 |
| [k8s-scheduler-arch-001](../tasks/ccb_design_haiku_20260226_015500_backfill--baseline-local-direct--k8s-scheduler-arch-001.html) | [source](../../../benchmarks/ccb_design/k8s-scheduler-arch-001) | `baseline-local-direct` | `passed` | 0.730 | 2 | 0.000 |
| [sgonly_k8s-scheduler-arch-001](../tasks/design_haiku_20260223_124652--mcp-remote-direct--sgonly_k8s-scheduler-arch-001.html) | [source](../../../benchmarks/ccb_design/k8s-scheduler-arch-001) | `mcp-remote-direct` | `passed` | 0.720 | 2 | 0.773 |
| [k8s-sharedinformer-sym-001](../tasks/ccb_design_haiku_20260228_025547--baseline-local-direct--k8s-sharedinformer-sym-001.html) | [source](../../../benchmarks/ccb_design/k8s-sharedinformer-sym-001) | `baseline-local-direct` | `passed` | 0.690 | 3 | 0.000 |
| [mcp_k8s-sharedinformer-sym-001_r1uWY5](../tasks/ccb_design_haiku_20260228_025547--mcp-remote-direct--mcp_k8s-sharedinformer-sym-001_r1uWY5.html) | [source](../../../benchmarks/ccb_design/k8s-sharedinformer-sym-001) | `mcp-remote-direct` | `passed` | 0.710 | 3 | 0.977 |
| [sgonly_k8s-sharedinformer-sym-001](../tasks/design_haiku_20260223_124652--mcp-remote-direct--sgonly_k8s-sharedinformer-sym-001.html) | [source](../../../benchmarks/ccb_design/k8s-sharedinformer-sym-001) | `mcp-remote-direct` | `passed` | 0.620 | 3 | 0.967 |
| [k8s-typemeta-dep-chain-001](../tasks/ccb_design_haiku_20260228_025547--baseline-local-direct--k8s-typemeta-dep-chain-001.html) | [source](../../../benchmarks/ccb_design/k8s-typemeta-dep-chain-001) | `baseline-local-direct` | `passed` | 0.670 | 3 | 0.000 |
| [mcp_k8s-typemeta-dep-chain-001_uTlaTc](../tasks/ccb_design_haiku_20260228_025547--mcp-remote-direct--mcp_k8s-typemeta-dep-chain-001_uTlaTc.html) | [source](../../../benchmarks/ccb_design/k8s-typemeta-dep-chain-001) | `mcp-remote-direct` | `passed` | 0.670 | 3 | 0.700 |
| [sgonly_k8s-typemeta-dep-chain-001](../tasks/design_haiku_20260223_124652--mcp-remote-direct--sgonly_k8s-typemeta-dep-chain-001.html) | [source](../../../benchmarks/ccb_design/k8s-typemeta-dep-chain-001) | `mcp-remote-direct` | `passed` | 0.670 | 3 | 0.833 |
| [kafka-flink-streaming-arch-001](../tasks/ccb_design_haiku_20260226_015500_backfill--baseline-local-direct--kafka-flink-streaming-arch-001.html) | [source](../../../benchmarks/ccb_design/kafka-flink-streaming-arch-001) | `baseline-local-direct` | `passed` | 0.970 | 2 | 0.000 |
| [sgonly_kafka-flink-streaming-arch-001](../tasks/design_haiku_20260223_124652--mcp-remote-direct--sgonly_kafka-flink-streaming-arch-001.html) | [source](../../../benchmarks/ccb_design/kafka-flink-streaming-arch-001) | `mcp-remote-direct` | `passed` | 0.400 | 2 | 0.896 |
| [postgres-query-exec-arch-001](../tasks/ccb_design_haiku_20260228_025547--baseline-local-direct--postgres-query-exec-arch-001.html) | [source](../../../benchmarks/ccb_design/postgres-query-exec-arch-001) | `baseline-local-direct` | `passed` | 0.740 | 3 | 0.000 |
| [mcp_postgres-query-exec-arch-001_A0vfQ4](../tasks/ccb_design_haiku_20260228_025547--mcp-remote-direct--mcp_postgres-query-exec-arch-001_A0vfQ4.html) | [source](../../../benchmarks/ccb_design/postgres-query-exec-arch-001) | `mcp-remote-direct` | `passed` | 1.000 | 3 | 0.878 |
| [sgonly_postgres-query-exec-arch-001](../tasks/design_haiku_20260223_124652--mcp-remote-direct--sgonly_postgres-query-exec-arch-001.html) | [source](../../../benchmarks/ccb_design/postgres-query-exec-arch-001) | `mcp-remote-direct` | `passed` | 0.830 | 3 | 0.976 |
| [quantlib-barrier-pricing-arch-001](../tasks/ccb_design_haiku_20260228_025547--baseline-local-direct--quantlib-barrier-pricing-arch-001.html) | [source](../../../benchmarks/ccb_design/quantlib-barrier-pricing-arch-001) | `baseline-local-direct` | `passed` | 0.880 | 3 | 0.000 |
| [mcp_quantlib-barrier-pricing-arch-001_4uwsVP](../tasks/ccb_design_haiku_20260228_025547--mcp-remote-direct--mcp_quantlib-barrier-pricing-arch-001_4uwsVP.html) | [source](../../../benchmarks/ccb_design/quantlib-barrier-pricing-arch-001) | `mcp-remote-direct` | `passed` | 0.890 | 3 | 0.962 |
| [sgonly_quantlib-barrier-pricing-arch-001](../tasks/design_haiku_20260223_124652--mcp-remote-direct--sgonly_quantlib-barrier-pricing-arch-001.html) | [source](../../../benchmarks/ccb_design/quantlib-barrier-pricing-arch-001) | `mcp-remote-direct` | `passed` | 0.830 | 3 | 0.968 |
| [terraform-provider-iface-sym-001](../tasks/ccb_design_haiku_20260228_025547--baseline-local-direct--terraform-provider-iface-sym-001.html) | [source](../../../benchmarks/ccb_design/terraform-provider-iface-sym-001) | `baseline-local-direct` | `passed` | 0.080 | 3 | 0.000 |
| [mcp_terraform-provider-iface-sym-001_JJ1WXA](../tasks/ccb_design_haiku_20260228_025547--mcp-remote-direct--mcp_terraform-provider-iface-sym-001_JJ1WXA.html) | [source](../../../benchmarks/ccb_design/terraform-provider-iface-sym-001) | `mcp-remote-direct` | `passed` | 0.080 | 3 | 0.971 |
| [sgonly_terraform-provider-iface-sym-001](../tasks/design_haiku_20260223_124652--mcp-remote-direct--sgonly_terraform-provider-iface-sym-001.html) | [source](../../../benchmarks/ccb_design/terraform-provider-iface-sym-001) | `mcp-remote-direct` | `passed` | 0.090 | 3 | 0.929 |

## Multi-Run Variance

Tasks with multiple valid runs (33 task/config pairs).

| Task | Benchmark | Config | Runs | Mean | Std | Individual Rewards |
|---|---|---|---:|---:|---:|---|
| camel-routing-arch-001 | [source](../../../benchmarks/ccb_design/camel-routing-arch-001) | `baseline-local-direct` | 2 | 0.870 | 0.000 | 0.870, 0.870 |
| django-modeladmin-impact-001 | [source](../../../benchmarks/ccb_design/django-modeladmin-impact-001) | `baseline-local-direct` | 2 | 1.000 | 0.000 | 1.000, 1.000 |
| django-modeladmin-impact-001 | [source](../../../benchmarks/ccb_design/django-modeladmin-impact-001) | `mcp-remote-direct` | 2 | 1.000 | 0.000 | 1.000, 1.000 |
| django-orm-query-arch-001 | [source](../../../benchmarks/ccb_design/django-orm-query-arch-001) | `baseline-local-direct` | 2 | 0.685 | 0.318 | 0.910, 0.460 |
| django-orm-query-arch-001 | [source](../../../benchmarks/ccb_design/django-orm-query-arch-001) | `mcp-remote-direct` | 2 | 0.935 | 0.078 | 0.990, 0.880 |
| django-pre-validate-signal-design-001 | [source](../../../benchmarks/ccb_design/django-pre-validate-signal-design-001) | `baseline-local-direct` | 2 | 0.725 | 0.389 | 1.000, 0.450 |
| django-pre-validate-signal-design-001 | [source](../../../benchmarks/ccb_design/django-pre-validate-signal-design-001) | `mcp-remote-direct` | 2 | 0.950 | 0.071 | 1.000, 0.900 |
| django-rate-limit-design-001 | [source](../../../benchmarks/ccb_design/django-rate-limit-design-001) | `baseline-local-direct` | 2 | 0.475 | 0.601 | 0.900, 0.050 |
| django-rate-limit-design-001 | [source](../../../benchmarks/ccb_design/django-rate-limit-design-001) | `mcp-remote-direct` | 2 | 0.950 | 0.071 | 1.000, 0.900 |
| envoy-routeconfig-dep-chain-001 | [source](../../../benchmarks/ccb_design/envoy-routeconfig-dep-chain-001) | `baseline-local-direct` | 2 | 1.000 | 0.000 | 1.000, 1.000 |
| envoy-routeconfig-dep-chain-001 | [source](../../../benchmarks/ccb_design/envoy-routeconfig-dep-chain-001) | `mcp-remote-direct` | 2 | 0.835 | 0.233 | 1.000, 0.670 |
| envoy-stream-aggregated-sym-001 | [source](../../../benchmarks/ccb_design/envoy-stream-aggregated-sym-001) | `baseline-local-direct` | 2 | 0.655 | 0.120 | 0.570, 0.740 |
| envoy-stream-aggregated-sym-001 | [source](../../../benchmarks/ccb_design/envoy-stream-aggregated-sym-001) | `mcp-remote-direct` | 2 | 0.495 | 0.247 | 0.320, 0.670 |
| etcd-grpc-api-upgrade-001 | [source](../../../benchmarks/ccb_design/etcd-grpc-api-upgrade-001) | `baseline-local-direct` | 2 | 0.000 | 0.000 | 0.000, 0.000 |
| flink-checkpoint-arch-001 | [source](../../../benchmarks/ccb_design/flink-checkpoint-arch-001) | `baseline-local-direct` | 2 | 0.800 | 0.000 | 0.800, 0.800 |
| flipt-protobuf-metadata-design-001 | [source](../../../benchmarks/ccb_design/flipt-protobuf-metadata-design-001) | `baseline-local-direct` | 2 | 0.740 | 0.368 | 1.000, 0.480 |
| flipt-protobuf-metadata-design-001 | [source](../../../benchmarks/ccb_design/flipt-protobuf-metadata-design-001) | `mcp-remote-direct` | 2 | 0.540 | 0.297 | 0.330, 0.750 |
| flipt-transitive-deps-001 | [source](../../../benchmarks/ccb_design/flipt-transitive-deps-001) | `baseline-local-direct` | 2 | 0.694 | 0.228 | 0.856, 0.533 |
| flipt-transitive-deps-001 | [source](../../../benchmarks/ccb_design/flipt-transitive-deps-001) | `mcp-remote-direct` | 2 | 0.679 | 0.045 | 0.711, 0.648 |
| k8s-crd-lifecycle-arch-001 | [source](../../../benchmarks/ccb_design/k8s-crd-lifecycle-arch-001) | `baseline-local-direct` | 2 | 0.690 | 0.000 | 0.690, 0.690 |
| k8s-dra-allocation-impact-001 | [source](../../../benchmarks/ccb_design/k8s-dra-allocation-impact-001) | `baseline-local-direct` | 2 | 1.000 | 0.000 | 1.000, 1.000 |
| k8s-scheduler-arch-001 | [source](../../../benchmarks/ccb_design/k8s-scheduler-arch-001) | `baseline-local-direct` | 2 | 0.730 | 0.000 | 0.730, 0.730 |
| k8s-sharedinformer-sym-001 | [source](../../../benchmarks/ccb_design/k8s-sharedinformer-sym-001) | `baseline-local-direct` | 2 | 0.660 | 0.042 | 0.630, 0.690 |
| k8s-sharedinformer-sym-001 | [source](../../../benchmarks/ccb_design/k8s-sharedinformer-sym-001) | `mcp-remote-direct` | 2 | 0.665 | 0.064 | 0.620, 0.710 |
| k8s-typemeta-dep-chain-001 | [source](../../../benchmarks/ccb_design/k8s-typemeta-dep-chain-001) | `baseline-local-direct` | 2 | 0.500 | 0.240 | 0.330, 0.670 |
| k8s-typemeta-dep-chain-001 | [source](../../../benchmarks/ccb_design/k8s-typemeta-dep-chain-001) | `mcp-remote-direct` | 2 | 0.670 | 0.000 | 0.670, 0.670 |
| kafka-flink-streaming-arch-001 | [source](../../../benchmarks/ccb_design/kafka-flink-streaming-arch-001) | `baseline-local-direct` | 2 | 0.970 | 0.000 | 0.970, 0.970 |
| postgres-query-exec-arch-001 | [source](../../../benchmarks/ccb_design/postgres-query-exec-arch-001) | `baseline-local-direct` | 2 | 0.790 | 0.071 | 0.840, 0.740 |
| postgres-query-exec-arch-001 | [source](../../../benchmarks/ccb_design/postgres-query-exec-arch-001) | `mcp-remote-direct` | 2 | 0.915 | 0.120 | 0.830, 1.000 |
| quantlib-barrier-pricing-arch-001 | [source](../../../benchmarks/ccb_design/quantlib-barrier-pricing-arch-001) | `baseline-local-direct` | 2 | 0.865 | 0.021 | 0.850, 0.880 |
| quantlib-barrier-pricing-arch-001 | [source](../../../benchmarks/ccb_design/quantlib-barrier-pricing-arch-001) | `mcp-remote-direct` | 2 | 0.860 | 0.042 | 0.830, 0.890 |
| terraform-provider-iface-sym-001 | [source](../../../benchmarks/ccb_design/terraform-provider-iface-sym-001) | `baseline-local-direct` | 2 | 0.100 | 0.028 | 0.120, 0.080 |
| terraform-provider-iface-sym-001 | [source](../../../benchmarks/ccb_design/terraform-provider-iface-sym-001) | `mcp-remote-direct` | 2 | 0.085 | 0.007 | 0.090, 0.080 |
