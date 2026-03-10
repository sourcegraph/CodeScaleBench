# csb_sdlc_design_haiku_022326

## baseline-local-direct

- Valid tasks: `9`
- Mean reward: `0.823`
- Pass rate: `1.000`
- Scorer families: `unknown (4), repo_state_heuristic (3), ir_checklist (2)`
- Output contracts: `unknown (4), answer_json_native (3), answer_json_bridge (2)`

| Task | Status | Reward | Passed | Scorer Family | Output Contract | MCP Ratio | Tool Calls | Trace |
|---|---|---:|---|---|---|---:|---:|---|
| [django-orm-query-arch-001](../tasks/csb_sdlc_design_haiku_022326--baseline--django-orm-query-arch-001--e89235fbb6.html) | `passed` | 0.910 | `True` | `ir_checklist` | `answer_json_bridge` | 0.000 | 53 | traj, tx |
| [django-pre-validate-signal-design-001](../tasks/csb_sdlc_design_haiku_022326--baseline--django-pre-validate-signal-design-001--76320d85b5.html) | `passed` | 1.000 | `True` | `repo_state_heuristic` | `answer_json_native` | 0.000 | 49 | traj, tx |
| [django-rate-limit-design-001](../tasks/csb_sdlc_design_haiku_022326--baseline--django-rate-limit-design-001--22c18f666e.html) | `passed` | 0.900 | `True` | `repo_state_heuristic` | `answer_json_native` | 0.000 | 12 | traj, tx |
| [envoy-routeconfig-dep-chain-001](../tasks/csb_sdlc_design_haiku_022326--baseline--envoy-routeconfig-dep-chain-001--0dc7056bb7.html) | `passed` | 1.000 | `True` | `-` | `-` | 0.000 | 14 | traj, tx |
| [envoy-stream-aggregated-sym-001](../tasks/csb_sdlc_design_haiku_022326--baseline--envoy-stream-aggregated-sym-001--ea93ea8ab4.html) | `passed` | 0.570 | `True` | `-` | `-` | 0.000 | 90 | traj, tx |
| [flipt-protobuf-metadata-design-001](../tasks/csb_sdlc_design_haiku_022326--baseline--flipt-protobuf-metadata-design-001--f9feb2a825.html) | `passed` | 1.000 | `True` | `repo_state_heuristic` | `answer_json_native` | 0.000 | 39 | traj, tx |
| [flipt-transitive-deps-001](../tasks/csb_sdlc_design_haiku_022326--baseline--flipt-transitive-deps-001--22f4f87e9b.html) | `passed` | 0.856 | `True` | `-` | `-` | 0.000 | 53 | traj, tx |
| [k8s-typemeta-dep-chain-001](../tasks/csb_sdlc_design_haiku_022326--baseline--k8s-typemeta-dep-chain-001--b7b4543949.html) | `passed` | 0.330 | `True` | `-` | `-` | 0.000 | 22 | traj, tx |
| [postgres-query-exec-arch-001](../tasks/csb_sdlc_design_haiku_022326--baseline--postgres-query-exec-arch-001--7eec207235.html) | `passed` | 0.840 | `True` | `ir_checklist` | `answer_json_bridge` | 0.000 | 44 | traj, tx |

## mcp-remote-direct

- Valid tasks: `20`
- Mean reward: `0.718`
- Pass rate: `1.000`
- Scorer families: `unknown (10), ir_checklist (6), repo_state_heuristic (3), semantic_similarity (1)`
- Output contracts: `unknown (10), answer_json_bridge (6), answer_json_native (3), repo_state (1)`

| Task | Status | Reward | Passed | Scorer Family | Output Contract | MCP Ratio | Tool Calls | Trace |
|---|---|---:|---|---|---|---:|---:|---|
| [sgonly_camel-routing-arch-001](../tasks/csb_sdlc_design_haiku_022326--mcp--sgonly_camel-routing-arch-001--d8680722d8.html) | `passed` | 0.730 | `True` | `ir_checklist` | `answer_json_bridge` | 0.966 | 29 | traj, tx |
| [sgonly_django-modeladmin-impact-001](../tasks/csb_sdlc_design_haiku_022326--mcp--sgonly_django-modeladmin-impact-001--0bcf41a749.html) | `passed` | 1.000 | `True` | `-` | `-` | 0.939 | 33 | traj, tx |
| [sgonly_django-orm-query-arch-001](../tasks/csb_sdlc_design_haiku_022326--mcp--sgonly_django-orm-query-arch-001--85e160b20f.html) | `passed` | 0.990 | `True` | `ir_checklist` | `answer_json_bridge` | 0.969 | 32 | traj, tx |
| [sgonly_django-pre-validate-signal-design-001](../tasks/csb_sdlc_design_haiku_022326--mcp--sgonly_django-pre-validate-signal-design-001--f2ee2db3c5.html) | `passed` | 1.000 | `True` | `repo_state_heuristic` | `answer_json_native` | 0.157 | 70 | traj, tx |
| [sgonly_django-rate-limit-design-001](../tasks/csb_sdlc_design_haiku_022326--mcp--sgonly_django-rate-limit-design-001--471d9152e6.html) | `passed` | 1.000 | `True` | `repo_state_heuristic` | `answer_json_native` | 0.333 | 21 | traj, tx |
| [sgonly_envoy-routeconfig-dep-chain-001](../tasks/csb_sdlc_design_haiku_022326--mcp--sgonly_envoy-routeconfig-dep-chain-001--2b7eeddfae.html) | `passed` | 1.000 | `True` | `-` | `-` | 0.857 | 14 | traj, tx |
| [sgonly_envoy-stream-aggregated-sym-001](../tasks/csb_sdlc_design_haiku_022326--mcp--sgonly_envoy-stream-aggregated-sym-001--38a4ed2aa0.html) | `passed` | 0.320 | `True` | `-` | `-` | 0.971 | 35 | traj, tx |
| [sgonly_etcd-grpc-api-upgrade-001](../tasks/csb_sdlc_design_haiku_022326--mcp--sgonly_etcd-grpc-api-upgrade-001--71fdb29d12.html) | `passed` | 0.714 | `True` | `semantic_similarity` | `repo_state` | 0.108 | 74 | traj, tx |
| [sgonly_flink-checkpoint-arch-001](../tasks/csb_sdlc_design_haiku_022326--mcp--sgonly_flink-checkpoint-arch-001--36a462d699.html) | `passed` | 0.730 | `True` | `ir_checklist` | `answer_json_bridge` | 0.958 | 24 | traj, tx |
| [sgonly_flipt-protobuf-metadata-design-001](../tasks/csb_sdlc_design_haiku_022326--mcp--sgonly_flipt-protobuf-metadata-design-001--1c4a80a6c2.html) | `passed` | 0.330 | `True` | `repo_state_heuristic` | `answer_json_native` | 0.345 | 55 | traj, tx |
| [sgonly_flipt-transitive-deps-001](../tasks/csb_sdlc_design_haiku_022326--mcp--sgonly_flipt-transitive-deps-001--42ecbd5b35.html) | `passed` | 0.711 | `True` | `-` | `-` | 0.949 | 39 | traj, tx |
| [sgonly_k8s-crd-lifecycle-arch-001](../tasks/csb_sdlc_design_haiku_022326--mcp--sgonly_k8s-crd-lifecycle-arch-001--fa8cb6c070.html) | `passed` | 0.770 | `True` | `ir_checklist` | `answer_json_bridge` | 0.829 | 35 | traj, tx |
| [sgonly_k8s-dra-allocation-impact-001](../tasks/csb_sdlc_design_haiku_022326--mcp--sgonly_k8s-dra-allocation-impact-001--17426c4bcb.html) | `passed` | 0.900 | `True` | `-` | `-` | 0.913 | 23 | traj, tx |
| [sgonly_k8s-scheduler-arch-001](../tasks/csb_sdlc_design_haiku_022326--mcp--sgonly_k8s-scheduler-arch-001--9d78a7bc3f.html) | `passed` | 0.720 | `True` | `-` | `-` | 0.773 | 22 | traj, tx |
| [sgonly_k8s-sharedinformer-sym-001](../tasks/csb_sdlc_design_haiku_022326--mcp--sgonly_k8s-sharedinformer-sym-001--555b15a9a2.html) | `passed` | 0.620 | `True` | `-` | `-` | 0.967 | 60 | traj, tx |
| [sgonly_k8s-typemeta-dep-chain-001](../tasks/csb_sdlc_design_haiku_022326--mcp--sgonly_k8s-typemeta-dep-chain-001--f65281607b.html) | `passed` | 0.670 | `True` | `-` | `-` | 0.833 | 18 | traj, tx |
| [sgonly_kafka-flink-streaming-arch-001](../tasks/csb_sdlc_design_haiku_022326--mcp--sgonly_kafka-flink-streaming-arch-001--fe7ff4144d.html) | `passed` | 0.400 | `True` | `ir_checklist` | `answer_json_bridge` | 0.896 | 48 | traj, tx |
| [sgonly_postgres-query-exec-arch-001](../tasks/csb_sdlc_design_haiku_022326--mcp--sgonly_postgres-query-exec-arch-001--a67dde0e07.html) | `passed` | 0.830 | `True` | `ir_checklist` | `answer_json_bridge` | 0.976 | 42 | traj, tx |
| [sgonly_quantlib-barrier-pricing-arch-001](../tasks/csb_sdlc_design_haiku_022326--mcp--sgonly_quantlib-barrier-pricing-arch-001--e6760f185f.html) | `passed` | 0.830 | `True` | `-` | `-` | 0.968 | 31 | traj, tx |
| [sgonly_terraform-provider-iface-sym-001](../tasks/csb_sdlc_design_haiku_022326--mcp--sgonly_terraform-provider-iface-sym-001--4171b192d3.html) | `passed` | 0.090 | `True` | `-` | `-` | 0.929 | 28 | traj, tx |
