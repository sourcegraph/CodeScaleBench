# csb_sdlc_understand_sonnet_20260308_034803

## baseline-local-direct

- Valid tasks: `9`
- Mean reward: `0.919`
- Pass rate: `1.000`
- Scorer families: `checklist (4), continuous (3), repo_state_heuristic (1), semantic_similarity (1)`
- Output contracts: `answer_json_bridge (7), answer_json_native (1), repo_state (1)`

| Task | Status | Reward | Passed | Scorer Family | Output Contract | MCP Ratio | Tool Calls | Trace |
|---|---|---:|---|---|---|---:|---:|---|
| [argocd-arch-orient-001](../tasks/csb_sdlc_understand_sonnet_20260308_034803--baseline-local-direct--argocd-arch-orient-001--068b95f0ab.html) | `passed` | 0.810 | `True` | `checklist` | `answer_json_bridge` | 0.000 | 80 | traj, tx |
| [cilium-ebpf-fault-qa-001](../tasks/csb_sdlc_understand_sonnet_20260308_034803--baseline-local-direct--cilium-ebpf-fault-qa-001--d4a3103ded.html) | `passed` | 0.850 | `True` | `checklist` | `answer_json_bridge` | 0.000 | 36 | traj, tx |
| [cilium-project-orient-001](../tasks/csb_sdlc_understand_sonnet_20260308_034803--baseline-local-direct--cilium-project-orient-001--42393a7820.html) | `passed` | 0.950 | `True` | `checklist` | `answer_json_bridge` | 0.000 | 93 | traj, tx |
| [django-composite-field-recover-001](../tasks/csb_sdlc_understand_sonnet_20260308_034803--baseline-local-direct--django-composite-field-recover-001--f87d21a762.html) | `passed` | 1.000 | `True` | `repo_state_heuristic` | `answer_json_native` | 0.000 | 29 | traj, tx |
| [envoy-request-routing-qa-001](../tasks/csb_sdlc_understand_sonnet_20260308_034803--baseline-local-direct--envoy-request-routing-qa-001--a1f256760d.html) | `passed` | 0.960 | `True` | `checklist` | `answer_json_bridge` | 0.000 | 76 | traj, tx |
| [grafana-platform-orient-001](../tasks/csb_sdlc_understand_sonnet_20260308_034803--baseline-local-direct--grafana-platform-orient-001--7a55d74313.html) | `passed` | 1.000 | `True` | `continuous` | `answer_json_bridge` | 0.000 | 75 | traj, tx |
| [kafka-build-orient-001](../tasks/csb_sdlc_understand_sonnet_20260308_034803--baseline-local-direct--kafka-build-orient-001--36e7248a1b.html) | `passed` | 0.910 | `True` | `continuous` | `answer_json_bridge` | 0.000 | 63 | traj, tx |
| [kafka-contributor-workflow-001](../tasks/csb_sdlc_understand_sonnet_20260308_034803--baseline-local-direct--kafka-contributor-workflow-001--2a25dd42bc.html) | `passed` | 0.860 | `True` | `continuous` | `answer_json_bridge` | 0.000 | 17 | traj, tx |
| [numpy-dtype-localize-001](../tasks/csb_sdlc_understand_sonnet_20260308_034803--baseline-local-direct--numpy-dtype-localize-001--ab4cd7d012.html) | `passed` | 0.933 | `True` | `semantic_similarity` | `repo_state` | 0.000 | 52 | traj, tx |

## mcp-remote-direct

- Valid tasks: `10`
- Mean reward: `0.902`
- Pass rate: `1.000`
- Scorer families: `checklist (4), continuous (3), repo_state_heuristic (3)`
- Output contracts: `answer_json_bridge (8), answer_json_native (2)`

| Task | Status | Reward | Passed | Scorer Family | Output Contract | MCP Ratio | Tool Calls | Trace |
|---|---|---:|---|---|---|---:|---:|---|
| [mcp_argocd-arch-orient-001_x0rjaz](../tasks/csb_sdlc_understand_sonnet_20260308_034803--mcp-remote-direct--mcp_argocd-arch-orient-001_x0rjaz--edaee4082a.html) | `passed` | 0.710 | `True` | `checklist` | `answer_json_bridge` | 0.927 | 55 | traj, tx |
| [mcp_cilium-ebpf-fault-qa-001_waz1q5](../tasks/csb_sdlc_understand_sonnet_20260308_034803--mcp-remote-direct--mcp_cilium-ebpf-fault-qa-001_waz1q5--92c866931e.html) | `passed` | 0.860 | `True` | `checklist` | `answer_json_bridge` | 0.882 | 34 | traj, tx |
| [mcp_cilium-project-orient-001_1btfol](../tasks/csb_sdlc_understand_sonnet_20260308_034803--mcp-remote-direct--mcp_cilium-project-orient-001_1btfol--cee64a475c.html) | `passed` | 0.980 | `True` | `checklist` | `answer_json_bridge` | 0.929 | 56 | traj, tx |
| [mcp_clickhouse-mergetree-arch-understand-001_vivvg9](../tasks/csb_sdlc_understand_sonnet_20260308_034803--mcp-remote-direct--mcp_clickhouse-mergetree-arch-understand-001_vivvg9--6b3774334f.html) | `passed` | 1.000 | `True` | `repo_state_heuristic` | `answer_json_bridge` | 0.833 | 24 | traj, tx |
| [mcp_django-composite-field-recover-001_jga0sj](../tasks/csb_sdlc_understand_sonnet_20260308_034803--mcp-remote-direct--mcp_django-composite-field-recover-001_jga0sj--43dff9447f.html) | `passed` | 1.000 | `True` | `repo_state_heuristic` | `answer_json_native` | 0.286 | 21 | traj, tx |
| [mcp_django-template-inherit-recall-001_h3l7u7](../tasks/csb_sdlc_understand_sonnet_20260308_034803--mcp-remote-direct--mcp_django-template-inherit-recall-001_h3l7u7--3b731fd059.html) | `passed` | 0.800 | `True` | `repo_state_heuristic` | `answer_json_native` | 0.352 | 91 | traj, tx |
| [mcp_envoy-request-routing-qa-001_ib80ak](../tasks/csb_sdlc_understand_sonnet_20260308_034803--mcp-remote-direct--mcp_envoy-request-routing-qa-001_ib80ak--b3310e2cd0.html) | `passed` | 0.910 | `True` | `checklist` | `answer_json_bridge` | 0.946 | 56 | traj, tx |
| [mcp_grafana-platform-orient-001_krbqo9](../tasks/csb_sdlc_understand_sonnet_20260308_034803--mcp-remote-direct--mcp_grafana-platform-orient-001_krbqo9--25e217c906.html) | `passed` | 1.000 | `True` | `continuous` | `answer_json_bridge` | 0.939 | 49 | traj, tx |
| [mcp_kafka-build-orient-001_svikjq](../tasks/csb_sdlc_understand_sonnet_20260308_034803--mcp-remote-direct--mcp_kafka-build-orient-001_svikjq--e90ff7d5c6.html) | `passed` | 0.900 | `True` | `continuous` | `answer_json_bridge` | 0.893 | 28 | traj, tx |
| [mcp_kafka-contributor-workflow-001_qjqivf](../tasks/csb_sdlc_understand_sonnet_20260308_034803--mcp-remote-direct--mcp_kafka-contributor-workflow-001_qjqivf--ded0ef68c6.html) | `passed` | 0.860 | `True` | `continuous` | `answer_json_bridge` | 0.692 | 13 | traj, tx |
