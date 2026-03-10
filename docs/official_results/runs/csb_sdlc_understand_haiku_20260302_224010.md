# csb_sdlc_understand_haiku_20260302_224010

## baseline-local-direct

- Valid tasks: `8`
- Mean reward: `0.818`
- Pass rate: `1.000`
- Scorer families: `checklist (4), repo_state_heuristic (2), continuous (1), semantic_similarity (1)`
- Output contracts: `answer_json_bridge (5), answer_json_native (2), repo_state (1)`

| Task | Status | Reward | Passed | Scorer Family | Output Contract | MCP Ratio | Tool Calls | Trace |
|---|---|---:|---|---|---|---:|---:|---|
| [argocd-arch-orient-001](../tasks/csb_sdlc_understand_haiku_20260302_224010--baseline-local-direct--argocd-arch-orient-001--b2682e3557.html) | `passed` | 0.850 | `True` | `checklist` | `answer_json_bridge` | 0.000 | 37 | traj, tx |
| [cilium-ebpf-fault-qa-001](../tasks/csb_sdlc_understand_haiku_20260302_224010--baseline-local-direct--cilium-ebpf-fault-qa-001--bf908af734.html) | `passed` | 0.940 | `True` | `checklist` | `answer_json_bridge` | 0.000 | 35 | traj, tx |
| [cilium-project-orient-001](../tasks/csb_sdlc_understand_haiku_20260302_224010--baseline-local-direct--cilium-project-orient-001--8ca3d44e9f.html) | `passed` | 0.920 | `True` | `checklist` | `answer_json_bridge` | 0.000 | 63 | traj, tx |
| [django-composite-field-recover-001](../tasks/csb_sdlc_understand_haiku_20260302_224010--baseline-local-direct--django-composite-field-recover-001--2ed2161133.html) | `passed` | 0.400 | `True` | `repo_state_heuristic` | `answer_json_native` | 0.000 | 64 | traj, tx |
| [django-template-inherit-recall-001](../tasks/csb_sdlc_understand_haiku_20260302_224010--baseline-local-direct--django-template-inherit-recall-001--e8a078d23b.html) | `passed` | 0.900 | `None` | `repo_state_heuristic` | `answer_json_native` | 0.000 | 66 | traj, tx |
| [envoy-request-routing-qa-001](../tasks/csb_sdlc_understand_haiku_20260302_224010--baseline-local-direct--envoy-request-routing-qa-001--46e001fc7e.html) | `passed` | 0.950 | `None` | `checklist` | `answer_json_bridge` | 0.000 | 184 | traj, tx |
| [kafka-contributor-workflow-001](../tasks/csb_sdlc_understand_haiku_20260302_224010--baseline-local-direct--kafka-contributor-workflow-001--fd1f8df7d9.html) | `passed` | 0.950 | `True` | `continuous` | `answer_json_bridge` | 0.000 | 39 | traj, tx |
| [numpy-dtype-localize-001](../tasks/csb_sdlc_understand_haiku_20260302_224010--baseline-local-direct--numpy-dtype-localize-001--6e48a78502.html) | `passed` | 0.633 | `True` | `semantic_similarity` | `repo_state` | 0.000 | 51 | traj, tx |

## mcp-remote-direct

- Valid tasks: `3`
- Mean reward: `0.857`
- Pass rate: `1.000`
- Scorer families: `checklist (1), repo_state_heuristic (1), semantic_similarity (1)`
- Output contracts: `answer_json_bridge (1), answer_json_native (1), repo_state (1)`

| Task | Status | Reward | Passed | Scorer Family | Output Contract | MCP Ratio | Tool Calls | Trace |
|---|---|---:|---|---|---|---:|---:|---|
| [mcp_argocd-arch-orient-001_gz699w](../tasks/csb_sdlc_understand_haiku_20260302_224010--mcp-remote-direct--mcp_argocd-arch-orient-001_gz699w--ed4ab25cfb.html) | `passed` | 0.770 | `None` | `checklist` | `answer_json_bridge` | 0.976 | 42 | traj, tx |
| [mcp_django-template-inherit-recall-001_gvxsja](../tasks/csb_sdlc_understand_haiku_20260302_224010--mcp-remote-direct--mcp_django-template-inherit-recall-001_gvxsja--b35a218536.html) | `passed` | 0.800 | `None` | `repo_state_heuristic` | `answer_json_native` | 0.253 | 75 | traj, tx |
| [mcp_numpy-dtype-localize-001_st1kho](../tasks/csb_sdlc_understand_haiku_20260302_224010--mcp-remote-direct--mcp_numpy-dtype-localize-001_st1kho--91f9cd4f6a.html) | `passed` | 1.000 | `None` | `semantic_similarity` | `repo_state` | 0.957 | 23 | traj, tx |
