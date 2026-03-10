# csb_sdlc_design_haiku_20260226_015500_backfill

## baseline-local-direct

- Valid tasks: `5`
- Mean reward: `0.666`
- Pass rate: `0.800`
- Scorer families: `ir_checklist (4), semantic_similarity (1)`
- Output contracts: `answer_json_bridge (4), repo_state (1)`

| Task | Status | Reward | Passed | Scorer Family | Output Contract | MCP Ratio | Tool Calls | Trace |
|---|---|---:|---|---|---|---:|---:|---|
| [etcd-grpc-api-upgrade-001](../tasks/csb_sdlc_design_haiku_20260226_015500_backfill--baseline-local-direct--etcd-grpc-api-upgrade-001--8fa0cb3552.html) | `failed` | 0.000 | `False` | `semantic_similarity` | `repo_state` | 0.000 | 169 | traj, tx |
| [camel-routing-arch-001](../tasks/csb_sdlc_design_haiku_20260226_015500_backfill--baseline-local-direct--camel-routing-arch-001--21a57584e8.html) | `passed` | 0.870 | `True` | `ir_checklist` | `answer_json_bridge` | 0.000 | 50 | traj, tx |
| [flink-checkpoint-arch-001](../tasks/csb_sdlc_design_haiku_20260226_015500_backfill--baseline-local-direct--flink-checkpoint-arch-001--df05c989ef.html) | `passed` | 0.800 | `True` | `ir_checklist` | `answer_json_bridge` | 0.000 | 34 | traj, tx |
| [k8s-crd-lifecycle-arch-001](../tasks/csb_sdlc_design_haiku_20260226_015500_backfill--baseline-local-direct--k8s-crd-lifecycle-arch-001--344fc95dce.html) | `passed` | 0.690 | `True` | `ir_checklist` | `answer_json_bridge` | 0.000 | 52 | traj, tx |
| [kafka-flink-streaming-arch-001](../tasks/csb_sdlc_design_haiku_20260226_015500_backfill--baseline-local-direct--kafka-flink-streaming-arch-001--a950d1194b.html) | `passed` | 0.970 | `True` | `ir_checklist` | `answer_json_bridge` | 0.000 | 36 | traj, tx |
