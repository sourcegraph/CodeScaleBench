# document_sonnet_20260218_190929__sgfull_invalid_truncation_gap

## baseline-local-direct

- Valid tasks: `9`
- Mean reward: `0.828`
- Pass rate: `1.000`
- Scorer families: `checklist (4), unknown (3), continuous (2)`
- Output contracts: `answer_json_bridge (6), unknown (3)`

| Task | Status | Reward | Passed | Scorer Family | Output Contract | MCP Ratio | Tool Calls | Trace |
|---|---|---:|---|---|---|---:|---:|---|
| [envoy-arch-doc-gen-001](../tasks/document_sonnet_20260218_190929__sgfull_invalid_truncation_gap--baseline--envoy-arch-doc-gen-001--8a1f720583.html) | `passed` | 0.930 | `True` | `checklist` | `answer_json_bridge` | 0.000 | 35 | traj, tx |
| [envoy-migration-doc-gen-001](../tasks/document_sonnet_20260218_190929__sgfull_invalid_truncation_gap--baseline--envoy-migration-doc-gen-001--ca513e78e2.html) | `passed` | 0.800 | `True` | `continuous` | `answer_json_bridge` | 0.000 | 54 | traj, tx |
| [istio-arch-doc-gen-001](../tasks/document_sonnet_20260218_190929__sgfull_invalid_truncation_gap--baseline--istio-arch-doc-gen-001--afc22eb26b.html) | `passed` | 1.000 | `True` | `-` | `-` | 0.000 | 38 | traj, tx |
| [k8s-applyconfig-doc-gen-001](../tasks/document_sonnet_20260218_190929__sgfull_invalid_truncation_gap--baseline--k8s-applyconfig-doc-gen-001--cdf92484ad.html) | `passed` | 1.000 | `True` | `checklist` | `answer_json_bridge` | 0.000 | 19 | traj, tx |
| [k8s-clientgo-doc-gen-001](../tasks/document_sonnet_20260218_190929__sgfull_invalid_truncation_gap--baseline--k8s-clientgo-doc-gen-001--c63e4d890c.html) | `passed` | 0.980 | `True` | `checklist` | `answer_json_bridge` | 0.000 | 51 | traj, tx |
| [k8s-controller-mgr-doc-gen-001](../tasks/document_sonnet_20260218_190929__sgfull_invalid_truncation_gap--baseline--k8s-controller-mgr-doc-gen-001--568aba33e1.html) | `passed` | 0.770 | `True` | `-` | `-` | 0.000 | 17 | traj, tx |
| [k8s-fairqueuing-doc-gen-001](../tasks/document_sonnet_20260218_190929__sgfull_invalid_truncation_gap--baseline--k8s-fairqueuing-doc-gen-001--c52a8cd975.html) | `passed` | 0.320 | `True` | `checklist` | `answer_json_bridge` | 0.000 | 56 | traj, tx |
| [kafka-api-doc-gen-001](../tasks/document_sonnet_20260218_190929__sgfull_invalid_truncation_gap--baseline--kafka-api-doc-gen-001--7d1a83d89d.html) | `passed` | 0.950 | `True` | `continuous` | `answer_json_bridge` | 0.000 | 15 | traj, tx |
| [terraform-arch-doc-gen-001](../tasks/document_sonnet_20260218_190929__sgfull_invalid_truncation_gap--baseline--terraform-arch-doc-gen-001--0182b9a779.html) | `passed` | 0.700 | `True` | `-` | `-` | 0.000 | 83 | traj, tx |

## sourcegraph_full

- Valid tasks: `12`
- Mean reward: `0.883`
- Pass rate: `1.000`
- Scorer families: `unknown (12)`
- Output contracts: `unknown (12)`

| Task | Status | Reward | Passed | Scorer Family | Output Contract | MCP Ratio | Tool Calls | Trace |
|---|---|---:|---|---|---|---:|---:|---|
| [sdlc_document_cilium-api-doc-gen-001_GxuDbR](../tasks/document_sonnet_20260218_190929__sgfull_invalid_truncation_gap--sourcegraph_full--sdlc_document_cilium-api-doc-gen-001_GxuDbR--b41d0ee25f.html) | `passed` | 0.980 | `True` | `-` | `-` | 0.933 | 15 | traj, tx |
| [sdlc_document_envoy-arch-doc-gen-001_YnIrw0](../tasks/document_sonnet_20260218_190929__sgfull_invalid_truncation_gap--sourcegraph_full--sdlc_document_envoy-arch-doc-gen-001_YnIrw0--9e2ebd934f.html) | `passed` | 1.000 | `True` | `-` | `-` | 0.955 | 22 | traj, tx |
| [sdlc_document_istio-arch-doc-gen-001_MwDJGJ](../tasks/document_sonnet_20260218_190929__sgfull_invalid_truncation_gap--sourcegraph_full--sdlc_document_istio-arch-doc-gen-001_MwDJGJ--48b7a8108e.html) | `passed` | 1.000 | `True` | `-` | `-` | 0.958 | 24 | traj, tx |
| [sdlc_document_k8s-apiserver-doc-gen-001_BLR15u](../tasks/document_sonnet_20260218_190929__sgfull_invalid_truncation_gap--sourcegraph_full--sdlc_document_k8s-apiserver-doc-gen-001_BLR15u--36fb5fd9e6.html) | `passed` | 1.000 | `True` | `-` | `-` | 0.973 | 37 | traj, tx |
| [sdlc_document_k8s-applyconfig-doc-gen-001_PQL431](../tasks/document_sonnet_20260218_190929__sgfull_invalid_truncation_gap--sourcegraph_full--sdlc_document_k8s-applyconfig-doc-gen-001_PQL431--92cb8e40a4.html) | `passed` | 0.800 | `True` | `-` | `-` | 0.977 | 44 | traj, tx |
| [sdlc_document_k8s-clientgo-doc-gen-001_MVzNu4](../tasks/document_sonnet_20260218_190929__sgfull_invalid_truncation_gap--sourcegraph_full--sdlc_document_k8s-clientgo-doc-gen-001_MVzNu4--1516de970a.html) | `passed` | 0.920 | `True` | `-` | `-` | 0.750 | 32 | traj, tx |
| [sdlc_document_k8s-controller-mgr-doc-gen-001_394ZEL](../tasks/document_sonnet_20260218_190929__sgfull_invalid_truncation_gap--sourcegraph_full--sdlc_document_k8s-controller-mgr-doc-gen-001_394ZEL--04ef30eadc.html) | `passed` | 0.730 | `True` | `-` | `-` | 0.973 | 37 | traj, tx |
| [sdlc_document_k8s-fairqueuing-doc-gen-001_fpj3k4](../tasks/document_sonnet_20260218_190929__sgfull_invalid_truncation_gap--sourcegraph_full--sdlc_document_k8s-fairqueuing-doc-gen-001_fpj3k4--e3e0b63f9b.html) | `passed` | 0.450 | `True` | `-` | `-` | 0.175 | 63 | traj, tx |
| [sdlc_document_kafka-api-doc-gen-001_o1NWty](../tasks/document_sonnet_20260218_190929__sgfull_invalid_truncation_gap--sourcegraph_full--sdlc_document_kafka-api-doc-gen-001_o1NWty--a2fce0622b.html) | `passed` | 0.980 | `True` | `-` | `-` | 0.950 | 20 | traj, tx |
| [sdlc_document_terraform-arch-doc-gen-001_8meJF7](../tasks/document_sonnet_20260218_190929__sgfull_invalid_truncation_gap--sourcegraph_full--sdlc_document_terraform-arch-doc-gen-001_8meJF7--e2b5562c55.html) | `passed` | 0.760 | `True` | `-` | `-` | 0.958 | 24 | traj, tx |
| [sdlc_document_terraform-migration-doc-gen-001_pk8ZPr](../tasks/document_sonnet_20260218_190929__sgfull_invalid_truncation_gap--sourcegraph_full--sdlc_document_terraform-migration-doc-gen-001_pk8ZPr--f63a4af485.html) | `passed` | 1.000 | `True` | `-` | `-` | 0.350 | 120 | traj, tx |
| [sdlc_document_vscode-api-doc-gen-001_YVrbY5](../tasks/document_sonnet_20260218_190929__sgfull_invalid_truncation_gap--sourcegraph_full--sdlc_document_vscode-api-doc-gen-001_YVrbY5--f2c841e679.html) | `passed` | 0.980 | `True` | `-` | `-` | 0.968 | 31 | traj, tx |
