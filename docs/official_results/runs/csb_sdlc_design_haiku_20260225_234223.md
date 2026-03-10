# csb_sdlc_design_haiku_20260225_234223

## baseline-local-direct

- Valid tasks: `5`
- Mean reward: `0.666`
- Pass rate: `0.800`
- Scorer families: `ir_checklist (4), semantic_similarity (1)`
- Output contracts: `answer_json_bridge (4), repo_state (1)`

| Task | Status | Reward | Passed | Scorer Family | Output Contract | MCP Ratio | Tool Calls | Trace |
|---|---|---:|---|---|---|---:|---:|---|
| [etcd-grpc-api-upgrade-001](../tasks/csb_sdlc_design_haiku_20260225_234223--baseline-local-direct--etcd-grpc-api-upgrade-001--b4fe5bb7ce.html) | `failed` | 0.000 | `False` | `semantic_similarity` | `repo_state` | 0.000 | 169 | traj, tx |
| [camel-routing-arch-001](../tasks/csb_sdlc_design_haiku_20260225_234223--baseline-local-direct--camel-routing-arch-001--f33e384dff.html) | `passed` | 0.870 | `True` | `ir_checklist` | `answer_json_bridge` | 0.000 | 50 | traj, tx |
| [flink-checkpoint-arch-001](../tasks/csb_sdlc_design_haiku_20260225_234223--baseline-local-direct--flink-checkpoint-arch-001--6af40cace9.html) | `passed` | 0.800 | `True` | `ir_checklist` | `answer_json_bridge` | 0.000 | 34 | traj, tx |
| [k8s-crd-lifecycle-arch-001](../tasks/csb_sdlc_design_haiku_20260225_234223--baseline-local-direct--k8s-crd-lifecycle-arch-001--2a4ccd5d50.html) | `passed` | 0.690 | `True` | `ir_checklist` | `answer_json_bridge` | 0.000 | 52 | traj, tx |
| [kafka-flink-streaming-arch-001](../tasks/csb_sdlc_design_haiku_20260225_234223--baseline-local-direct--kafka-flink-streaming-arch-001--207962bf0b.html) | `passed` | 0.970 | `True` | `ir_checklist` | `answer_json_bridge` | 0.000 | 36 | traj, tx |
