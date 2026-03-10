# csb_sdlc_design_sonnet_20260308_034803

## baseline-local-direct

- Valid tasks: `11`
- Mean reward: `0.896`
- Pass rate: `1.000`
- Scorer families: `ir_checklist (6), repo_state_heuristic (4), semantic_similarity (1)`
- Output contracts: `answer_json_bridge (7), answer_json_native (3), repo_state (1)`

| Task | Status | Reward | Passed | Scorer Family | Output Contract | MCP Ratio | Tool Calls | Trace |
|---|---|---:|---|---|---|---:|---:|---|
| [camel-routing-arch-001](../tasks/csb_sdlc_design_sonnet_20260308_034803--baseline-local-direct--camel-routing-arch-001--c867457251.html) | `passed` | 0.810 | `True` | `ir_checklist` | `answer_json_bridge` | 0.000 | 41 | traj, tx |
| [django-orm-query-arch-001](../tasks/csb_sdlc_design_sonnet_20260308_034803--baseline-local-direct--django-orm-query-arch-001--10ed229167.html) | `passed` | 0.870 | `True` | `ir_checklist` | `answer_json_bridge` | 0.000 | 37 | traj, tx |
| [django-pre-validate-signal-design-001](../tasks/csb_sdlc_design_sonnet_20260308_034803--baseline-local-direct--django-pre-validate-signal-design-001--3d35fcea64.html) | `passed` | 1.000 | `True` | `repo_state_heuristic` | `answer_json_native` | 0.000 | 17 | traj, tx |
| [django-rate-limit-design-001](../tasks/csb_sdlc_design_sonnet_20260308_034803--baseline-local-direct--django-rate-limit-design-001--85d41b3fa1.html) | `passed` | 1.000 | `True` | `repo_state_heuristic` | `answer_json_native` | 0.000 | 8 | traj, tx |
| [elasticsearch-shard-alloc-design-001](../tasks/csb_sdlc_design_sonnet_20260308_034803--baseline-local-direct--elasticsearch-shard-alloc-design-001--62571724ce.html) | `passed` | 1.000 | `True` | `repo_state_heuristic` | `answer_json_bridge` | 0.000 | 17 | traj, tx |
| [etcd-grpc-api-upgrade-001](../tasks/csb_sdlc_design_sonnet_20260308_034803--baseline-local-direct--etcd-grpc-api-upgrade-001--fed7f61244.html) | `passed` | 0.771 | `True` | `semantic_similarity` | `repo_state` | 0.000 | 108 | traj, tx |
| [flink-checkpoint-arch-001](../tasks/csb_sdlc_design_sonnet_20260308_034803--baseline-local-direct--flink-checkpoint-arch-001--2f2757166a.html) | `passed` | 0.800 | `True` | `ir_checklist` | `answer_json_bridge` | 0.000 | 53 | traj, tx |
| [flipt-protobuf-metadata-design-001](../tasks/csb_sdlc_design_sonnet_20260308_034803--baseline-local-direct--flipt-protobuf-metadata-design-001--70df638fe4.html) | `passed` | 1.000 | `True` | `repo_state_heuristic` | `answer_json_native` | 0.000 | 48 | traj, tx |
| [k8s-crd-lifecycle-arch-001](../tasks/csb_sdlc_design_sonnet_20260308_034803--baseline-local-direct--k8s-crd-lifecycle-arch-001--9d5786f62b.html) | `passed` | 0.810 | `True` | `ir_checklist` | `answer_json_bridge` | 0.000 | 55 | traj, tx |
| [kafka-flink-streaming-arch-001](../tasks/csb_sdlc_design_sonnet_20260308_034803--baseline-local-direct--kafka-flink-streaming-arch-001--a6ab77d47f.html) | `passed` | 0.950 | `True` | `ir_checklist` | `answer_json_bridge` | 0.000 | 55 | traj, tx |
| [postgres-query-exec-arch-001](../tasks/csb_sdlc_design_sonnet_20260308_034803--baseline-local-direct--postgres-query-exec-arch-001--8f4d138f66.html) | `passed` | 0.850 | `True` | `ir_checklist` | `answer_json_bridge` | 0.000 | 51 | traj, tx |

## mcp-remote-direct

- Valid tasks: `11`
- Mean reward: `0.788`
- Pass rate: `0.909`
- Scorer families: `ir_checklist (6), repo_state_heuristic (4), semantic_similarity (1)`
- Output contracts: `answer_json_bridge (7), answer_json_native (3), repo_state (1)`

| Task | Status | Reward | Passed | Scorer Family | Output Contract | MCP Ratio | Tool Calls | Trace |
|---|---|---:|---|---|---|---:|---:|---|
| [mcp_etcd-grpc-api-upgrade-001_p1egkg](../tasks/csb_sdlc_design_sonnet_20260308_034803--mcp-remote-direct--mcp_etcd-grpc-api-upgrade-001_p1egkg--f12821973e.html) | `failed` | 0.000 | `False` | `semantic_similarity` | `repo_state` | 0.615 | 52 | traj, tx |
| [mcp_camel-routing-arch-001_s8vc1w](../tasks/csb_sdlc_design_sonnet_20260308_034803--mcp-remote-direct--mcp_camel-routing-arch-001_s8vc1w--5b0913325d.html) | `passed` | 0.800 | `True` | `ir_checklist` | `answer_json_bridge` | 0.889 | 36 | traj, tx |
| [mcp_django-orm-query-arch-001_mejpp6](../tasks/csb_sdlc_design_sonnet_20260308_034803--mcp-remote-direct--mcp_django-orm-query-arch-001_mejpp6--57680778e8.html) | `passed` | 0.900 | `True` | `ir_checklist` | `answer_json_bridge` | 0.935 | 46 | traj, tx |
| [mcp_django-pre-validate-signal-design-001_ow7mkr](../tasks/csb_sdlc_design_sonnet_20260308_034803--mcp-remote-direct--mcp_django-pre-validate-signal-design-001_ow7mkr--c9e8931cc7.html) | `passed` | 1.000 | `True` | `repo_state_heuristic` | `answer_json_native` | 0.333 | 78 | traj, tx |
| [mcp_django-rate-limit-design-001_7pv81u](../tasks/csb_sdlc_design_sonnet_20260308_034803--mcp-remote-direct--mcp_django-rate-limit-design-001_7pv81u--bd87ce5cbe.html) | `passed` | 1.000 | `True` | `repo_state_heuristic` | `answer_json_native` | 0.429 | 7 | traj, tx |
| [mcp_elasticsearch-shard-alloc-design-001_8mzndc](../tasks/csb_sdlc_design_sonnet_20260308_034803--mcp-remote-direct--mcp_elasticsearch-shard-alloc-design-001_8mzndc--186ca59f4f.html) | `passed` | 1.000 | `True` | `repo_state_heuristic` | `answer_json_bridge` | 0.688 | 16 | traj, tx |
| [mcp_flink-checkpoint-arch-001_weeezi](../tasks/csb_sdlc_design_sonnet_20260308_034803--mcp-remote-direct--mcp_flink-checkpoint-arch-001_weeezi--00b701f21e.html) | `passed` | 0.890 | `True` | `ir_checklist` | `answer_json_bridge` | 0.879 | 33 | traj, tx |
| [mcp_flipt-protobuf-metadata-design-001_a3nvgh](../tasks/csb_sdlc_design_sonnet_20260308_034803--mcp-remote-direct--mcp_flipt-protobuf-metadata-design-001_a3nvgh--6c66db85bf.html) | `passed` | 1.000 | `True` | `repo_state_heuristic` | `answer_json_native` | 0.294 | 51 | traj, tx |
| [mcp_k8s-crd-lifecycle-arch-001_fz6lbd](../tasks/csb_sdlc_design_sonnet_20260308_034803--mcp-remote-direct--mcp_k8s-crd-lifecycle-arch-001_fz6lbd--b20085ba75.html) | `passed` | 0.740 | `True` | `ir_checklist` | `answer_json_bridge` | 0.875 | 56 | traj, tx |
| [mcp_kafka-flink-streaming-arch-001_5bjj7y](../tasks/csb_sdlc_design_sonnet_20260308_034803--mcp-remote-direct--mcp_kafka-flink-streaming-arch-001_5bjj7y--d6e13a8644.html) | `passed` | 0.400 | `True` | `ir_checklist` | `answer_json_bridge` | 0.921 | 38 | traj, tx |
| [mcp_postgres-query-exec-arch-001_ztckck](../tasks/csb_sdlc_design_sonnet_20260308_034803--mcp-remote-direct--mcp_postgres-query-exec-arch-001_ztckck--976bee2aa8.html) | `passed` | 0.940 | `True` | `ir_checklist` | `answer_json_bridge` | 0.927 | 41 | traj, tx |
