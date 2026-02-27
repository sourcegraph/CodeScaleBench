# ccb_design

| Run | Config | Valid Tasks | Mean Reward | Pass Rate |
|---|---|---:|---:|---:|
| [ccb_design_haiku_022326](../runs/ccb_design_haiku_022326.md) | `baseline` | 13 | 0.770 | 1.000 |
| [ccb_design_haiku_022326](../runs/ccb_design_haiku_022326.md) | `mcp` | 20 | 0.718 | 1.000 |
| [ccb_design_haiku_20260226_015500_backfill](../runs/ccb_design_haiku_20260226_015500_backfill.md) | `baseline-local-direct` | 7 | 0.723 | 0.857 |
| [design_haiku_20260223_124652](../runs/design_haiku_20260223_124652.md) | `baseline-local-direct` | 13 | 0.770 | 1.000 |
| [design_haiku_20260223_124652](../runs/design_haiku_20260223_124652.md) | `mcp-remote-direct` | 20 | 0.718 | 1.000 |

## Tasks

| Run | Config | Task | Status | Reward | MCP Ratio |
|---|---|---|---|---:|---:|
| `ccb_design_haiku_022326` | `baseline` | [django-modeladmin-impact-001](../tasks/ccb_design_haiku_022326--baseline--django-modeladmin-impact-001.md) | `passed` | 1.000 | 0.000 |
| `ccb_design_haiku_022326` | `baseline` | [django-orm-query-arch-001](../tasks/ccb_design_haiku_022326--baseline--django-orm-query-arch-001.md) | `passed` | 0.910 | 0.000 |
| `ccb_design_haiku_022326` | `baseline` | [django-pre-validate-signal-design-001](../tasks/ccb_design_haiku_022326--baseline--django-pre-validate-signal-design-001.md) | `passed` | 1.000 | 0.000 |
| `ccb_design_haiku_022326` | `baseline` | [django-rate-limit-design-001](../tasks/ccb_design_haiku_022326--baseline--django-rate-limit-design-001.md) | `passed` | 0.900 | 0.000 |
| `ccb_design_haiku_022326` | `baseline` | [envoy-routeconfig-dep-chain-001](../tasks/ccb_design_haiku_022326--baseline--envoy-routeconfig-dep-chain-001.md) | `passed` | 1.000 | 0.000 |
| `ccb_design_haiku_022326` | `baseline` | [envoy-stream-aggregated-sym-001](../tasks/ccb_design_haiku_022326--baseline--envoy-stream-aggregated-sym-001.md) | `passed` | 0.570 | 0.000 |
| `ccb_design_haiku_022326` | `baseline` | [flipt-protobuf-metadata-design-001](../tasks/ccb_design_haiku_022326--baseline--flipt-protobuf-metadata-design-001.md) | `passed` | 1.000 | 0.000 |
| `ccb_design_haiku_022326` | `baseline` | [flipt-transitive-deps-001](../tasks/ccb_design_haiku_022326--baseline--flipt-transitive-deps-001.md) | `passed` | 0.856 | 0.000 |
| `ccb_design_haiku_022326` | `baseline` | [k8s-sharedinformer-sym-001](../tasks/ccb_design_haiku_022326--baseline--k8s-sharedinformer-sym-001.md) | `passed` | 0.630 | 0.000 |
| `ccb_design_haiku_022326` | `baseline` | [k8s-typemeta-dep-chain-001](../tasks/ccb_design_haiku_022326--baseline--k8s-typemeta-dep-chain-001.md) | `passed` | 0.330 | 0.000 |
| `ccb_design_haiku_022326` | `baseline` | [postgres-query-exec-arch-001](../tasks/ccb_design_haiku_022326--baseline--postgres-query-exec-arch-001.md) | `passed` | 0.840 | 0.000 |
| `ccb_design_haiku_022326` | `baseline` | [quantlib-barrier-pricing-arch-001](../tasks/ccb_design_haiku_022326--baseline--quantlib-barrier-pricing-arch-001.md) | `passed` | 0.850 | 0.000 |
| `ccb_design_haiku_022326` | `baseline` | [terraform-provider-iface-sym-001](../tasks/ccb_design_haiku_022326--baseline--terraform-provider-iface-sym-001.md) | `passed` | 0.120 | 0.000 |
| `ccb_design_haiku_022326` | `mcp` | [sgonly_camel-routing-arch-001](../tasks/ccb_design_haiku_022326--mcp--sgonly_camel-routing-arch-001.md) | `passed` | 0.730 | 0.966 |
| `ccb_design_haiku_022326` | `mcp` | [sgonly_django-modeladmin-impact-001](../tasks/ccb_design_haiku_022326--mcp--sgonly_django-modeladmin-impact-001.md) | `passed` | 1.000 | 0.939 |
| `ccb_design_haiku_022326` | `mcp` | [sgonly_django-orm-query-arch-001](../tasks/ccb_design_haiku_022326--mcp--sgonly_django-orm-query-arch-001.md) | `passed` | 0.990 | 0.969 |
| `ccb_design_haiku_022326` | `mcp` | [sgonly_django-pre-validate-signal-design-001](../tasks/ccb_design_haiku_022326--mcp--sgonly_django-pre-validate-signal-design-001.md) | `passed` | 1.000 | 0.157 |
| `ccb_design_haiku_022326` | `mcp` | [sgonly_django-rate-limit-design-001](../tasks/ccb_design_haiku_022326--mcp--sgonly_django-rate-limit-design-001.md) | `passed` | 1.000 | 0.333 |
| `ccb_design_haiku_022326` | `mcp` | [sgonly_envoy-routeconfig-dep-chain-001](../tasks/ccb_design_haiku_022326--mcp--sgonly_envoy-routeconfig-dep-chain-001.md) | `passed` | 1.000 | 0.857 |
| `ccb_design_haiku_022326` | `mcp` | [sgonly_envoy-stream-aggregated-sym-001](../tasks/ccb_design_haiku_022326--mcp--sgonly_envoy-stream-aggregated-sym-001.md) | `passed` | 0.320 | 0.971 |
| `ccb_design_haiku_022326` | `mcp` | [sgonly_etcd-grpc-api-upgrade-001](../tasks/ccb_design_haiku_022326--mcp--sgonly_etcd-grpc-api-upgrade-001.md) | `passed` | 0.714 | 0.108 |
| `ccb_design_haiku_022326` | `mcp` | [sgonly_flink-checkpoint-arch-001](../tasks/ccb_design_haiku_022326--mcp--sgonly_flink-checkpoint-arch-001.md) | `passed` | 0.730 | 0.958 |
| `ccb_design_haiku_022326` | `mcp` | [sgonly_flipt-protobuf-metadata-design-001](../tasks/ccb_design_haiku_022326--mcp--sgonly_flipt-protobuf-metadata-design-001.md) | `passed` | 0.330 | 0.345 |
| `ccb_design_haiku_022326` | `mcp` | [sgonly_flipt-transitive-deps-001](../tasks/ccb_design_haiku_022326--mcp--sgonly_flipt-transitive-deps-001.md) | `passed` | 0.711 | 0.949 |
| `ccb_design_haiku_022326` | `mcp` | [sgonly_k8s-crd-lifecycle-arch-001](../tasks/ccb_design_haiku_022326--mcp--sgonly_k8s-crd-lifecycle-arch-001.md) | `passed` | 0.770 | 0.829 |
| `ccb_design_haiku_022326` | `mcp` | [sgonly_k8s-dra-allocation-impact-001](../tasks/ccb_design_haiku_022326--mcp--sgonly_k8s-dra-allocation-impact-001.md) | `passed` | 0.900 | 0.913 |
| `ccb_design_haiku_022326` | `mcp` | [sgonly_k8s-scheduler-arch-001](../tasks/ccb_design_haiku_022326--mcp--sgonly_k8s-scheduler-arch-001.md) | `passed` | 0.720 | 0.773 |
| `ccb_design_haiku_022326` | `mcp` | [sgonly_k8s-sharedinformer-sym-001](../tasks/ccb_design_haiku_022326--mcp--sgonly_k8s-sharedinformer-sym-001.md) | `passed` | 0.620 | 0.967 |
| `ccb_design_haiku_022326` | `mcp` | [sgonly_k8s-typemeta-dep-chain-001](../tasks/ccb_design_haiku_022326--mcp--sgonly_k8s-typemeta-dep-chain-001.md) | `passed` | 0.670 | 0.833 |
| `ccb_design_haiku_022326` | `mcp` | [sgonly_kafka-flink-streaming-arch-001](../tasks/ccb_design_haiku_022326--mcp--sgonly_kafka-flink-streaming-arch-001.md) | `passed` | 0.400 | 0.896 |
| `ccb_design_haiku_022326` | `mcp` | [sgonly_postgres-query-exec-arch-001](../tasks/ccb_design_haiku_022326--mcp--sgonly_postgres-query-exec-arch-001.md) | `passed` | 0.830 | 0.976 |
| `ccb_design_haiku_022326` | `mcp` | [sgonly_quantlib-barrier-pricing-arch-001](../tasks/ccb_design_haiku_022326--mcp--sgonly_quantlib-barrier-pricing-arch-001.md) | `passed` | 0.830 | 0.968 |
| `ccb_design_haiku_022326` | `mcp` | [sgonly_terraform-provider-iface-sym-001](../tasks/ccb_design_haiku_022326--mcp--sgonly_terraform-provider-iface-sym-001.md) | `passed` | 0.090 | 0.929 |
| `ccb_design_haiku_20260226_015500_backfill` | `baseline-local-direct` | [camel-routing-arch-001](../tasks/ccb_design_haiku_20260226_015500_backfill--baseline-local-direct--camel-routing-arch-001.md) | `passed` | 0.870 | 0.000 |
| `ccb_design_haiku_20260226_015500_backfill` | `baseline-local-direct` | [etcd-grpc-api-upgrade-001](../tasks/ccb_design_haiku_20260226_015500_backfill--baseline-local-direct--etcd-grpc-api-upgrade-001.md) | `failed` | 0.000 | 0.000 |
| `ccb_design_haiku_20260226_015500_backfill` | `baseline-local-direct` | [flink-checkpoint-arch-001](../tasks/ccb_design_haiku_20260226_015500_backfill--baseline-local-direct--flink-checkpoint-arch-001.md) | `passed` | 0.800 | 0.000 |
| `ccb_design_haiku_20260226_015500_backfill` | `baseline-local-direct` | [k8s-crd-lifecycle-arch-001](../tasks/ccb_design_haiku_20260226_015500_backfill--baseline-local-direct--k8s-crd-lifecycle-arch-001.md) | `passed` | 0.690 | 0.000 |
| `ccb_design_haiku_20260226_015500_backfill` | `baseline-local-direct` | [k8s-dra-allocation-impact-001](../tasks/ccb_design_haiku_20260226_015500_backfill--baseline-local-direct--k8s-dra-allocation-impact-001.md) | `passed` | 1.000 | 0.000 |
| `ccb_design_haiku_20260226_015500_backfill` | `baseline-local-direct` | [k8s-scheduler-arch-001](../tasks/ccb_design_haiku_20260226_015500_backfill--baseline-local-direct--k8s-scheduler-arch-001.md) | `passed` | 0.730 | 0.000 |
| `ccb_design_haiku_20260226_015500_backfill` | `baseline-local-direct` | [kafka-flink-streaming-arch-001](../tasks/ccb_design_haiku_20260226_015500_backfill--baseline-local-direct--kafka-flink-streaming-arch-001.md) | `passed` | 0.970 | 0.000 |
| `design_haiku_20260223_124652` | `baseline-local-direct` | [django-modeladmin-impact-001](../tasks/design_haiku_20260223_124652--baseline-local-direct--django-modeladmin-impact-001.md) | `passed` | 1.000 | 0.000 |
| `design_haiku_20260223_124652` | `baseline-local-direct` | [django-orm-query-arch-001](../tasks/design_haiku_20260223_124652--baseline-local-direct--django-orm-query-arch-001.md) | `passed` | 0.910 | 0.000 |
| `design_haiku_20260223_124652` | `baseline-local-direct` | [django-pre-validate-signal-design-001](../tasks/design_haiku_20260223_124652--baseline-local-direct--django-pre-validate-signal-design-001.md) | `passed` | 1.000 | 0.000 |
| `design_haiku_20260223_124652` | `baseline-local-direct` | [django-rate-limit-design-001](../tasks/design_haiku_20260223_124652--baseline-local-direct--django-rate-limit-design-001.md) | `passed` | 0.900 | 0.000 |
| `design_haiku_20260223_124652` | `baseline-local-direct` | [envoy-routeconfig-dep-chain-001](../tasks/design_haiku_20260223_124652--baseline-local-direct--envoy-routeconfig-dep-chain-001.md) | `passed` | 1.000 | 0.000 |
| `design_haiku_20260223_124652` | `baseline-local-direct` | [envoy-stream-aggregated-sym-001](../tasks/design_haiku_20260223_124652--baseline-local-direct--envoy-stream-aggregated-sym-001.md) | `passed` | 0.570 | 0.000 |
| `design_haiku_20260223_124652` | `baseline-local-direct` | [flipt-protobuf-metadata-design-001](../tasks/design_haiku_20260223_124652--baseline-local-direct--flipt-protobuf-metadata-design-001.md) | `passed` | 1.000 | 0.000 |
| `design_haiku_20260223_124652` | `baseline-local-direct` | [flipt-transitive-deps-001](../tasks/design_haiku_20260223_124652--baseline-local-direct--flipt-transitive-deps-001.md) | `passed` | 0.856 | 0.000 |
| `design_haiku_20260223_124652` | `baseline-local-direct` | [k8s-sharedinformer-sym-001](../tasks/design_haiku_20260223_124652--baseline-local-direct--k8s-sharedinformer-sym-001.md) | `passed` | 0.630 | 0.000 |
| `design_haiku_20260223_124652` | `baseline-local-direct` | [k8s-typemeta-dep-chain-001](../tasks/design_haiku_20260223_124652--baseline-local-direct--k8s-typemeta-dep-chain-001.md) | `passed` | 0.330 | 0.000 |
| `design_haiku_20260223_124652` | `baseline-local-direct` | [postgres-query-exec-arch-001](../tasks/design_haiku_20260223_124652--baseline-local-direct--postgres-query-exec-arch-001.md) | `passed` | 0.840 | 0.000 |
| `design_haiku_20260223_124652` | `baseline-local-direct` | [quantlib-barrier-pricing-arch-001](../tasks/design_haiku_20260223_124652--baseline-local-direct--quantlib-barrier-pricing-arch-001.md) | `passed` | 0.850 | 0.000 |
| `design_haiku_20260223_124652` | `baseline-local-direct` | [terraform-provider-iface-sym-001](../tasks/design_haiku_20260223_124652--baseline-local-direct--terraform-provider-iface-sym-001.md) | `passed` | 0.120 | 0.000 |
| `design_haiku_20260223_124652` | `mcp-remote-direct` | [sgonly_camel-routing-arch-001](../tasks/design_haiku_20260223_124652--mcp-remote-direct--sgonly_camel-routing-arch-001.md) | `passed` | 0.730 | 0.966 |
| `design_haiku_20260223_124652` | `mcp-remote-direct` | [sgonly_django-modeladmin-impact-001](../tasks/design_haiku_20260223_124652--mcp-remote-direct--sgonly_django-modeladmin-impact-001.md) | `passed` | 1.000 | 0.939 |
| `design_haiku_20260223_124652` | `mcp-remote-direct` | [sgonly_django-orm-query-arch-001](../tasks/design_haiku_20260223_124652--mcp-remote-direct--sgonly_django-orm-query-arch-001.md) | `passed` | 0.990 | 0.969 |
| `design_haiku_20260223_124652` | `mcp-remote-direct` | [sgonly_django-pre-validate-signal-design-001](../tasks/design_haiku_20260223_124652--mcp-remote-direct--sgonly_django-pre-validate-signal-design-001.md) | `passed` | 1.000 | 0.157 |
| `design_haiku_20260223_124652` | `mcp-remote-direct` | [sgonly_django-rate-limit-design-001](../tasks/design_haiku_20260223_124652--mcp-remote-direct--sgonly_django-rate-limit-design-001.md) | `passed` | 1.000 | 0.333 |
| `design_haiku_20260223_124652` | `mcp-remote-direct` | [sgonly_envoy-routeconfig-dep-chain-001](../tasks/design_haiku_20260223_124652--mcp-remote-direct--sgonly_envoy-routeconfig-dep-chain-001.md) | `passed` | 1.000 | 0.857 |
| `design_haiku_20260223_124652` | `mcp-remote-direct` | [sgonly_envoy-stream-aggregated-sym-001](../tasks/design_haiku_20260223_124652--mcp-remote-direct--sgonly_envoy-stream-aggregated-sym-001.md) | `passed` | 0.320 | 0.971 |
| `design_haiku_20260223_124652` | `mcp-remote-direct` | [sgonly_etcd-grpc-api-upgrade-001](../tasks/design_haiku_20260223_124652--mcp-remote-direct--sgonly_etcd-grpc-api-upgrade-001.md) | `passed` | 0.714 | 0.108 |
| `design_haiku_20260223_124652` | `mcp-remote-direct` | [sgonly_flink-checkpoint-arch-001](../tasks/design_haiku_20260223_124652--mcp-remote-direct--sgonly_flink-checkpoint-arch-001.md) | `passed` | 0.730 | 0.958 |
| `design_haiku_20260223_124652` | `mcp-remote-direct` | [sgonly_flipt-protobuf-metadata-design-001](../tasks/design_haiku_20260223_124652--mcp-remote-direct--sgonly_flipt-protobuf-metadata-design-001.md) | `passed` | 0.330 | 0.345 |
| `design_haiku_20260223_124652` | `mcp-remote-direct` | [sgonly_flipt-transitive-deps-001](../tasks/design_haiku_20260223_124652--mcp-remote-direct--sgonly_flipt-transitive-deps-001.md) | `passed` | 0.711 | 0.949 |
| `design_haiku_20260223_124652` | `mcp-remote-direct` | [sgonly_k8s-crd-lifecycle-arch-001](../tasks/design_haiku_20260223_124652--mcp-remote-direct--sgonly_k8s-crd-lifecycle-arch-001.md) | `passed` | 0.770 | 0.829 |
| `design_haiku_20260223_124652` | `mcp-remote-direct` | [sgonly_k8s-dra-allocation-impact-001](../tasks/design_haiku_20260223_124652--mcp-remote-direct--sgonly_k8s-dra-allocation-impact-001.md) | `passed` | 0.900 | 0.913 |
| `design_haiku_20260223_124652` | `mcp-remote-direct` | [sgonly_k8s-scheduler-arch-001](../tasks/design_haiku_20260223_124652--mcp-remote-direct--sgonly_k8s-scheduler-arch-001.md) | `passed` | 0.720 | 0.773 |
| `design_haiku_20260223_124652` | `mcp-remote-direct` | [sgonly_k8s-sharedinformer-sym-001](../tasks/design_haiku_20260223_124652--mcp-remote-direct--sgonly_k8s-sharedinformer-sym-001.md) | `passed` | 0.620 | 0.967 |
| `design_haiku_20260223_124652` | `mcp-remote-direct` | [sgonly_k8s-typemeta-dep-chain-001](../tasks/design_haiku_20260223_124652--mcp-remote-direct--sgonly_k8s-typemeta-dep-chain-001.md) | `passed` | 0.670 | 0.833 |
| `design_haiku_20260223_124652` | `mcp-remote-direct` | [sgonly_kafka-flink-streaming-arch-001](../tasks/design_haiku_20260223_124652--mcp-remote-direct--sgonly_kafka-flink-streaming-arch-001.md) | `passed` | 0.400 | 0.896 |
| `design_haiku_20260223_124652` | `mcp-remote-direct` | [sgonly_postgres-query-exec-arch-001](../tasks/design_haiku_20260223_124652--mcp-remote-direct--sgonly_postgres-query-exec-arch-001.md) | `passed` | 0.830 | 0.976 |
| `design_haiku_20260223_124652` | `mcp-remote-direct` | [sgonly_quantlib-barrier-pricing-arch-001](../tasks/design_haiku_20260223_124652--mcp-remote-direct--sgonly_quantlib-barrier-pricing-arch-001.md) | `passed` | 0.830 | 0.968 |
| `design_haiku_20260223_124652` | `mcp-remote-direct` | [sgonly_terraform-provider-iface-sym-001](../tasks/design_haiku_20260223_124652--mcp-remote-direct--sgonly_terraform-provider-iface-sym-001.md) | `passed` | 0.090 | 0.929 |
