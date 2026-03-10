# csb_sdlc_document_haiku_022326

## baseline-local-direct

- Valid tasks: `8`
- Mean reward: `0.839`
- Pass rate: `1.000`
- Scorer families: `unknown (4), checklist (2), continuous (2)`
- Output contracts: `answer_json_bridge (4), unknown (4)`

| Task | Status | Reward | Passed | Scorer Family | Output Contract | MCP Ratio | Tool Calls | Trace |
|---|---|---:|---|---|---|---:|---:|---|
| [docgen-changelog-002](../tasks/csb_sdlc_document_haiku_022326--baseline--docgen-changelog-002--d5997709f1.html) | `passed` | 0.700 | `True` | `-` | `-` | 0.000 | 31 | traj, tx |
| [docgen-inline-002](../tasks/csb_sdlc_document_haiku_022326--baseline--docgen-inline-002--1c711f56be.html) | `passed` | 1.000 | `True` | `checklist` | `answer_json_bridge` | 0.000 | 32 | traj, tx |
| [docgen-runbook-001](../tasks/csb_sdlc_document_haiku_022326--baseline--docgen-runbook-001--dc3dd1461c.html) | `passed` | 1.000 | `True` | `-` | `-` | 0.000 | 32 | traj, tx |
| [envoy-arch-doc-gen-001](../tasks/csb_sdlc_document_haiku_022326--baseline--envoy-arch-doc-gen-001--7ad1d6a791.html) | `passed` | 1.000 | `True` | `checklist` | `answer_json_bridge` | 0.000 | 56 | traj, tx |
| [envoy-migration-doc-gen-001](../tasks/csb_sdlc_document_haiku_022326--baseline--envoy-migration-doc-gen-001--30e320838f.html) | `passed` | 0.650 | `True` | `continuous` | `answer_json_bridge` | 0.000 | 25 | traj, tx |
| [istio-arch-doc-gen-001](../tasks/csb_sdlc_document_haiku_022326--baseline--istio-arch-doc-gen-001--8ca15418cf.html) | `passed` | 1.000 | `True` | `-` | `-` | 0.000 | 57 | traj, tx |
| [kafka-api-doc-gen-001](../tasks/csb_sdlc_document_haiku_022326--baseline--kafka-api-doc-gen-001--9eeb217bac.html) | `passed` | 0.940 | `True` | `continuous` | `answer_json_bridge` | 0.000 | 11 | traj, tx |
| [terraform-arch-doc-gen-001](../tasks/csb_sdlc_document_haiku_022326--baseline--terraform-arch-doc-gen-001--ccd3f40c01.html) | `passed` | 0.420 | `True` | `-` | `-` | 0.000 | 1 | traj, tx |

## mcp-remote-direct

- Valid tasks: `15`
- Mean reward: `0.953`
- Pass rate: `1.000`
- Scorer families: `unknown (11), checklist (2), continuous (2)`
- Output contracts: `unknown (11), answer_json_bridge (4)`

| Task | Status | Reward | Passed | Scorer Family | Output Contract | MCP Ratio | Tool Calls | Trace |
|---|---|---:|---|---|---|---:|---:|---|
| [sgonly_cilium-api-doc-gen-001](../tasks/csb_sdlc_document_haiku_022326--mcp--sgonly_cilium-api-doc-gen-001--e8d67a24ed.html) | `passed` | 0.980 | `True` | `-` | `-` | 0.929 | 14 | traj, tx |
| [sgonly_docgen-changelog-001](../tasks/csb_sdlc_document_haiku_022326--mcp--sgonly_docgen-changelog-001--20077a86ba.html) | `passed` | 1.000 | `True` | `-` | `-` | 0.921 | 38 | traj, tx |
| [sgonly_docgen-changelog-002](../tasks/csb_sdlc_document_haiku_022326--mcp--sgonly_docgen-changelog-002--13ea3e02a1.html) | `passed` | 1.000 | `True` | `-` | `-` | 0.909 | 22 | traj, tx |
| [sgonly_docgen-inline-001](../tasks/csb_sdlc_document_haiku_022326--mcp--sgonly_docgen-inline-001--37323fc2e7.html) | `passed` | 1.000 | `True` | `-` | `-` | 0.357 | 14 | traj, tx |
| [sgonly_docgen-inline-002](../tasks/csb_sdlc_document_haiku_022326--mcp--sgonly_docgen-inline-002--50d8e1b675.html) | `passed` | 1.000 | `True` | `checklist` | `answer_json_bridge` | 0.206 | 34 | traj, tx |
| [sgonly_docgen-onboard-001](../tasks/csb_sdlc_document_haiku_022326--mcp--sgonly_docgen-onboard-001--b976052ed5.html) | `passed` | 1.000 | `True` | `-` | `-` | 0.950 | 20 | traj, tx |
| [sgonly_docgen-runbook-001](../tasks/csb_sdlc_document_haiku_022326--mcp--sgonly_docgen-runbook-001--0aa64b9ff9.html) | `passed` | 1.000 | `True` | `-` | `-` | 0.773 | 22 | traj, tx |
| [sgonly_docgen-runbook-002](../tasks/csb_sdlc_document_haiku_022326--mcp--sgonly_docgen-runbook-002--19f9cba97f.html) | `passed` | 1.000 | `True` | `-` | `-` | 0.857 | 28 | traj, tx |
| [sgonly_envoy-arch-doc-gen-001](../tasks/csb_sdlc_document_haiku_022326--mcp--sgonly_envoy-arch-doc-gen-001--2971d7f281.html) | `passed` | 1.000 | `True` | `checklist` | `answer_json_bridge` | 0.833 | 18 | traj, tx |
| [sgonly_envoy-migration-doc-gen-001](../tasks/csb_sdlc_document_haiku_022326--mcp--sgonly_envoy-migration-doc-gen-001--5b97c4cf19.html) | `passed` | 0.790 | `True` | `continuous` | `answer_json_bridge` | 0.826 | 23 | traj, tx |
| [sgonly_istio-arch-doc-gen-001](../tasks/csb_sdlc_document_haiku_022326--mcp--sgonly_istio-arch-doc-gen-001--9f0f45fd1b.html) | `passed` | 1.000 | `True` | `-` | `-` | 0.962 | 26 | traj, tx |
| [sgonly_kafka-api-doc-gen-001](../tasks/csb_sdlc_document_haiku_022326--mcp--sgonly_kafka-api-doc-gen-001--3cbbffdf79.html) | `passed` | 0.940 | `True` | `continuous` | `answer_json_bridge` | 0.794 | 102 | traj, tx |
| [sgonly_terraform-arch-doc-gen-001](../tasks/csb_sdlc_document_haiku_022326--mcp--sgonly_terraform-arch-doc-gen-001--68bf9cb8e0.html) | `passed` | 0.590 | `True` | `-` | `-` | 0.962 | 26 | traj, tx |
| [sgonly_terraform-migration-doc-gen-001](../tasks/csb_sdlc_document_haiku_022326--mcp--sgonly_terraform-migration-doc-gen-001--0bbce6fd51.html) | `passed` | 1.000 | `True` | `-` | `-` | 0.933 | 15 | traj, tx |
| [sgonly_vscode-api-doc-gen-001](../tasks/csb_sdlc_document_haiku_022326--mcp--sgonly_vscode-api-doc-gen-001--db8214f31d.html) | `passed` | 1.000 | `True` | `-` | `-` | 0.952 | 21 | traj, tx |
