# csb_sdlc_document_haiku_20260302_221730

## baseline-local-direct

- Valid tasks: `8`
- Mean reward: `0.776`
- Pass rate: `1.000`
- Scorer families: `checklist (6), unknown (2)`
- Output contracts: `answer_json_bridge (6), unknown (2)`

| Task | Status | Reward | Passed | Scorer Family | Output Contract | MCP Ratio | Tool Calls | Trace |
|---|---|---:|---|---|---|---:|---:|---|
| [docgen-changelog-002](../tasks/csb_sdlc_document_haiku_20260302_221730--baseline-local-direct--docgen-changelog-002--4384e4151c.html) | `passed` | 1.000 | `None` | `-` | `-` | 0.000 | 36 | traj, tx |
| [docgen-inline-002](../tasks/csb_sdlc_document_haiku_20260302_221730--baseline-local-direct--docgen-inline-002--f22c1d0538.html) | `passed` | 1.000 | `None` | `checklist` | `answer_json_bridge` | 0.000 | 36 | traj, tx |
| [envoy-arch-doc-gen-001](../tasks/csb_sdlc_document_haiku_20260302_221730--baseline-local-direct--envoy-arch-doc-gen-001--60841eae2a.html) | `passed` | 0.930 | `None` | `checklist` | `answer_json_bridge` | 0.000 | 33 | traj, tx |
| [istio-arch-doc-gen-001](../tasks/csb_sdlc_document_haiku_20260302_221730--baseline-local-direct--istio-arch-doc-gen-001--60d122ca70.html) | `passed` | 1.000 | `None` | `-` | `-` | 0.000 | 29 | traj, tx |
| [k8s-apiserver-doc-gen-001](../tasks/csb_sdlc_document_haiku_20260302_221730--baseline-local-direct--k8s-apiserver-doc-gen-001--96d9f1ce69.html) | `passed` | 0.520 | `None` | `checklist` | `answer_json_bridge` | 0.000 | 34 | traj, tx |
| [k8s-applyconfig-doc-gen-001](../tasks/csb_sdlc_document_haiku_20260302_221730--baseline-local-direct--k8s-applyconfig-doc-gen-001--7d7c677222.html) | `passed` | 0.790 | `None` | `checklist` | `answer_json_bridge` | 0.000 | 40 | traj, tx |
| [k8s-fairqueuing-doc-gen-001](../tasks/csb_sdlc_document_haiku_20260302_221730--baseline-local-direct--k8s-fairqueuing-doc-gen-001--0a3fd170b8.html) | `passed` | 0.320 | `None` | `checklist` | `answer_json_bridge` | 0.000 | 30 | traj, tx |
| [k8s-kubelet-cm-doc-gen-001](../tasks/csb_sdlc_document_haiku_20260302_221730--baseline-local-direct--k8s-kubelet-cm-doc-gen-001--4fa846433d.html) | `passed` | 0.650 | `None` | `checklist` | `answer_json_bridge` | 0.000 | 23 | traj, tx |

## mcp-remote-direct

- Valid tasks: `9`
- Mean reward: `0.844`
- Pass rate: `1.000`
- Scorer families: `checklist (4), unknown (3), continuous (2)`
- Output contracts: `answer_json_bridge (6), unknown (3)`

| Task | Status | Reward | Passed | Scorer Family | Output Contract | MCP Ratio | Tool Calls | Trace |
|---|---|---:|---|---|---|---:|---:|---|
| [mcp_docgen-inline-002_l0mqf7](../tasks/csb_sdlc_document_haiku_20260302_221730--mcp-remote-direct--mcp_docgen-inline-002_l0mqf7--0b5b7e9762.html) | `passed` | 1.000 | `None` | `checklist` | `answer_json_bridge` | 0.368 | 19 | traj, tx |
| [mcp_docgen-runbook-001_im4s9i](../tasks/csb_sdlc_document_haiku_20260302_221730--mcp-remote-direct--mcp_docgen-runbook-001_im4s9i--ff66920f0b.html) | `passed` | 0.920 | `None` | `-` | `-` | 0.966 | 29 | traj, tx |
| [mcp_envoy-migration-doc-gen-001_neszpz](../tasks/csb_sdlc_document_haiku_20260302_221730--mcp-remote-direct--mcp_envoy-migration-doc-gen-001_neszpz--df094f11fd.html) | `passed` | 0.760 | `None` | `continuous` | `answer_json_bridge` | 0.905 | 21 | traj, tx |
| [mcp_istio-arch-doc-gen-001_nhlp1o](../tasks/csb_sdlc_document_haiku_20260302_221730--mcp-remote-direct--mcp_istio-arch-doc-gen-001_nhlp1o--2c0338f48d.html) | `passed` | 0.950 | `None` | `-` | `-` | 0.964 | 28 | traj, tx |
| [mcp_k8s-applyconfig-doc-gen-001_4vndvw](../tasks/csb_sdlc_document_haiku_20260302_221730--mcp-remote-direct--mcp_k8s-applyconfig-doc-gen-001_4vndvw--98665ee76e.html) | `passed` | 1.000 | `None` | `checklist` | `answer_json_bridge` | 0.958 | 24 | traj, tx |
| [mcp_k8s-clientgo-doc-gen-001_19q4yj](../tasks/csb_sdlc_document_haiku_20260302_221730--mcp-remote-direct--mcp_k8s-clientgo-doc-gen-001_19q4yj--26189fc819.html) | `passed` | 0.960 | `None` | `checklist` | `answer_json_bridge` | 0.933 | 45 | traj, tx |
| [mcp_k8s-fairqueuing-doc-gen-001_gwwdpd](../tasks/csb_sdlc_document_haiku_20260302_221730--mcp-remote-direct--mcp_k8s-fairqueuing-doc-gen-001_gwwdpd--3f11fa88c1.html) | `passed` | 0.420 | `None` | `checklist` | `answer_json_bridge` | 0.955 | 22 | traj, tx |
| [mcp_kafka-api-doc-gen-001_cznegq](../tasks/csb_sdlc_document_haiku_20260302_221730--mcp-remote-direct--mcp_kafka-api-doc-gen-001_cznegq--12125a7c41.html) | `passed` | 1.000 | `None` | `continuous` | `answer_json_bridge` | 0.824 | 17 | traj, tx |
| [mcp_terraform-arch-doc-gen-001_fvj949](../tasks/csb_sdlc_document_haiku_20260302_221730--mcp-remote-direct--mcp_terraform-arch-doc-gen-001_fvj949--8e12450a12.html) | `passed` | 0.590 | `None` | `-` | `-` | 0.889 | 27 | traj, tx |
