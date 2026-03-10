# csb_sdlc_document_haiku_20260228_025547

## baseline-local-direct

- Valid tasks: `13`
- Mean reward: `0.833`
- Pass rate: `1.000`
- Scorer families: `checklist (7), unknown (4), continuous (2)`
- Output contracts: `answer_json_bridge (9), unknown (4)`

| Task | Status | Reward | Passed | Scorer Family | Output Contract | MCP Ratio | Tool Calls | Trace |
|---|---|---:|---|---|---|---:|---:|---|
| [docgen-changelog-002](../tasks/csb_sdlc_document_haiku_20260228_025547--baseline-local-direct--docgen-changelog-002--0b62de96f8.html) | `passed` | 1.000 | `True` | `-` | `-` | 0.000 | 52 | traj, tx |
| [docgen-inline-002](../tasks/csb_sdlc_document_haiku_20260228_025547--baseline-local-direct--docgen-inline-002--0f2f5ed634.html) | `passed` | 1.000 | `True` | `checklist` | `answer_json_bridge` | 0.000 | 23 | traj, tx |
| [docgen-runbook-001](../tasks/csb_sdlc_document_haiku_20260228_025547--baseline-local-direct--docgen-runbook-001--1df6634858.html) | `passed` | 1.000 | `True` | `-` | `-` | 0.000 | 19 | traj, tx |
| [envoy-arch-doc-gen-001](../tasks/csb_sdlc_document_haiku_20260228_025547--baseline-local-direct--envoy-arch-doc-gen-001--d395788329.html) | `passed` | 0.930 | `True` | `checklist` | `answer_json_bridge` | 0.000 | 22 | traj, tx |
| [envoy-migration-doc-gen-001](../tasks/csb_sdlc_document_haiku_20260228_025547--baseline-local-direct--envoy-migration-doc-gen-001--d994ac6b26.html) | `passed` | 0.960 | `True` | `continuous` | `answer_json_bridge` | 0.000 | 38 | traj, tx |
| [istio-arch-doc-gen-001](../tasks/csb_sdlc_document_haiku_20260228_025547--baseline-local-direct--istio-arch-doc-gen-001--d6bcd76f56.html) | `passed` | 1.000 | `True` | `-` | `-` | 0.000 | 29 | traj, tx |
| [k8s-apiserver-doc-gen-001](../tasks/csb_sdlc_document_haiku_20260228_025547--baseline-local-direct--k8s-apiserver-doc-gen-001--175d7d8d93.html) | `passed` | 0.520 | `True` | `checklist` | `answer_json_bridge` | 0.000 | 44 | traj, tx |
| [k8s-applyconfig-doc-gen-001](../tasks/csb_sdlc_document_haiku_20260228_025547--baseline-local-direct--k8s-applyconfig-doc-gen-001--d9afde337e.html) | `passed` | 0.900 | `True` | `checklist` | `answer_json_bridge` | 0.000 | 56 | traj, tx |
| [k8s-clientgo-doc-gen-001](../tasks/csb_sdlc_document_haiku_20260228_025547--baseline-local-direct--k8s-clientgo-doc-gen-001--91a7b43783.html) | `passed` | 1.000 | `True` | `checklist` | `answer_json_bridge` | 0.000 | 25 | traj, tx |
| [k8s-fairqueuing-doc-gen-001](../tasks/csb_sdlc_document_haiku_20260228_025547--baseline-local-direct--k8s-fairqueuing-doc-gen-001--3b47df1494.html) | `passed` | 0.450 | `True` | `checklist` | `answer_json_bridge` | 0.000 | 29 | traj, tx |
| [k8s-kubelet-cm-doc-gen-001](../tasks/csb_sdlc_document_haiku_20260228_025547--baseline-local-direct--k8s-kubelet-cm-doc-gen-001--5f26546772.html) | `passed` | 0.650 | `True` | `checklist` | `answer_json_bridge` | 0.000 | 27 | traj, tx |
| [kafka-api-doc-gen-001](../tasks/csb_sdlc_document_haiku_20260228_025547--baseline-local-direct--kafka-api-doc-gen-001--ab9dfcba8a.html) | `passed` | 0.990 | `True` | `continuous` | `answer_json_bridge` | 0.000 | 21 | traj, tx |
| [terraform-arch-doc-gen-001](../tasks/csb_sdlc_document_haiku_20260228_025547--baseline-local-direct--terraform-arch-doc-gen-001--cc3b2a258e.html) | `passed` | 0.430 | `True` | `-` | `-` | 0.000 | 3 | traj, tx |

## mcp-remote-direct

- Valid tasks: `18`
- Mean reward: `0.887`
- Pass rate: `1.000`
- Scorer families: `unknown (9), checklist (7), continuous (2)`
- Output contracts: `answer_json_bridge (9), unknown (9)`

| Task | Status | Reward | Passed | Scorer Family | Output Contract | MCP Ratio | Tool Calls | Trace |
|---|---|---:|---|---|---|---:|---:|---|
| [mcp_cilium-api-doc-gen-001_091CkA](../tasks/csb_sdlc_document_haiku_20260228_025547--mcp-remote-direct--mcp_cilium-api-doc-gen-001_091CkA--8d70ee20b6.html) | `passed` | 0.970 | `True` | `-` | `-` | 0.958 | 24 | traj, tx |
| [mcp_docgen-changelog-001_dAdbQw](../tasks/csb_sdlc_document_haiku_20260228_025547--mcp-remote-direct--mcp_docgen-changelog-001_dAdbQw--216b9a2591.html) | `passed` | 1.000 | `True` | `-` | `-` | 0.970 | 33 | traj, tx |
| [mcp_docgen-changelog-002_FL0OCX](../tasks/csb_sdlc_document_haiku_20260228_025547--mcp-remote-direct--mcp_docgen-changelog-002_FL0OCX--3bd1c43d3a.html) | `passed` | 1.000 | `True` | `-` | `-` | 0.704 | 27 | traj, tx |
| [mcp_docgen-inline-002_5i12ae](../tasks/csb_sdlc_document_haiku_20260228_025547--mcp-remote-direct--mcp_docgen-inline-002_5i12ae--934d0e50af.html) | `passed` | 0.880 | `True` | `checklist` | `answer_json_bridge` | 0.261 | 46 | traj, tx |
| [mcp_docgen-onboard-001_hukfPp](../tasks/csb_sdlc_document_haiku_20260228_025547--mcp-remote-direct--mcp_docgen-onboard-001_hukfPp--55226086f6.html) | `passed` | 1.000 | `True` | `-` | `-` | 0.958 | 24 | traj, tx |
| [mcp_docgen-runbook-001_jYeNEv](../tasks/csb_sdlc_document_haiku_20260228_025547--mcp-remote-direct--mcp_docgen-runbook-001_jYeNEv--f478124227.html) | `passed` | 1.000 | `True` | `-` | `-` | 0.941 | 17 | traj, tx |
| [mcp_docgen-runbook-002_DNuQLB](../tasks/csb_sdlc_document_haiku_20260228_025547--mcp-remote-direct--mcp_docgen-runbook-002_DNuQLB--5a9812c109.html) | `passed` | 1.000 | `True` | `-` | `-` | 0.944 | 18 | traj, tx |
| [mcp_envoy-arch-doc-gen-001_uEBdoF](../tasks/csb_sdlc_document_haiku_20260228_025547--mcp-remote-direct--mcp_envoy-arch-doc-gen-001_uEBdoF--217ca44ff5.html) | `passed` | 1.000 | `True` | `checklist` | `answer_json_bridge` | 0.955 | 22 | traj, tx |
| [mcp_envoy-migration-doc-gen-001_RmzLDJ](../tasks/csb_sdlc_document_haiku_20260228_025547--mcp-remote-direct--mcp_envoy-migration-doc-gen-001_RmzLDJ--fd3030091d.html) | `passed` | 0.630 | `True` | `continuous` | `answer_json_bridge` | 0.917 | 24 | traj, tx |
| [mcp_istio-arch-doc-gen-001_TsE9lp](../tasks/csb_sdlc_document_haiku_20260228_025547--mcp-remote-direct--mcp_istio-arch-doc-gen-001_TsE9lp--1e00c6c3c6.html) | `passed` | 0.960 | `True` | `-` | `-` | 0.947 | 19 | traj, tx |
| [mcp_k8s-apiserver-doc-gen-001_G2WWxT](../tasks/csb_sdlc_document_haiku_20260228_025547--mcp-remote-direct--mcp_k8s-apiserver-doc-gen-001_G2WWxT--30e65f2604.html) | `passed` | 0.770 | `True` | `checklist` | `answer_json_bridge` | 0.971 | 34 | traj, tx |
| [mcp_k8s-applyconfig-doc-gen-001_KXIqYx](../tasks/csb_sdlc_document_haiku_20260228_025547--mcp-remote-direct--mcp_k8s-applyconfig-doc-gen-001_KXIqYx--43544be061.html) | `passed` | 1.000 | `True` | `checklist` | `answer_json_bridge` | 0.947 | 19 | traj, tx |
| [mcp_k8s-clientgo-doc-gen-001_rKIpaI](../tasks/csb_sdlc_document_haiku_20260228_025547--mcp-remote-direct--mcp_k8s-clientgo-doc-gen-001_rKIpaI--cc10773e83.html) | `passed` | 1.000 | `True` | `checklist` | `answer_json_bridge` | 0.974 | 38 | traj, tx |
| [mcp_k8s-fairqueuing-doc-gen-001_62urr3](../tasks/csb_sdlc_document_haiku_20260228_025547--mcp-remote-direct--mcp_k8s-fairqueuing-doc-gen-001_62urr3--6c7f2e14bd.html) | `passed` | 0.520 | `True` | `checklist` | `answer_json_bridge` | 0.882 | 17 | traj, tx |
| [mcp_k8s-kubelet-cm-doc-gen-001_n6VqU9](../tasks/csb_sdlc_document_haiku_20260228_025547--mcp-remote-direct--mcp_k8s-kubelet-cm-doc-gen-001_n6VqU9--9b38d5c2e5.html) | `passed` | 0.650 | `True` | `checklist` | `answer_json_bridge` | 0.952 | 21 | traj, tx |
| [mcp_kafka-api-doc-gen-001_Kv6biZ](../tasks/csb_sdlc_document_haiku_20260228_025547--mcp-remote-direct--mcp_kafka-api-doc-gen-001_Kv6biZ--d9cb0fda2b.html) | `passed` | 0.990 | `True` | `continuous` | `answer_json_bridge` | 0.938 | 16 | traj, tx |
| [mcp_terraform-arch-doc-gen-001_4HxL3B](../tasks/csb_sdlc_document_haiku_20260228_025547--mcp-remote-direct--mcp_terraform-arch-doc-gen-001_4HxL3B--bf04fc9fd8.html) | `passed` | 0.590 | `True` | `-` | `-` | 0.920 | 25 | traj, tx |
| [mcp_terraform-migration-doc-gen-001_XjPeYr](../tasks/csb_sdlc_document_haiku_20260228_025547--mcp-remote-direct--mcp_terraform-migration-doc-gen-001_XjPeYr--098fb84a87.html) | `passed` | 1.000 | `True` | `-` | `-` | 0.857 | 28 | traj, tx |
