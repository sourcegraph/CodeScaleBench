# csb_sdlc_fix_haiku_20260301_173337

## baseline-local-direct

- Valid tasks: `9`
- Mean reward: `0.597`
- Pass rate: `0.889`
- Scorer families: `diff_similarity (4), ir_checklist (3), repo_state_heuristic (1), unknown (1)`
- Output contracts: `answer_json_bridge (8), unknown (1)`

| Task | Status | Reward | Passed | Scorer Family | Output Contract | MCP Ratio | Tool Calls | Trace |
|---|---|---:|---|---|---|---:|---:|---|
| [pytorch-cudnn-version-fix-001](../tasks/csb_sdlc_fix_haiku_20260301_173337--baseline-local-direct--pytorch-cudnn-version-fix-001--ecbb426565.html) | `failed` | 0.000 | `False` | `diff_similarity` | `answer_json_bridge` | 0.000 | 68 | traj, tx |
| [django-modelchoice-fk-fix-001](../tasks/csb_sdlc_fix_haiku_20260301_173337--baseline-local-direct--django-modelchoice-fk-fix-001--456471dadf.html) | `passed` | 0.450 | `True` | `repo_state_heuristic` | `answer_json_bridge` | 0.000 | 127 | traj, tx |
| [django-select-for-update-fix-001](../tasks/csb_sdlc_fix_haiku_20260301_173337--baseline-local-direct--django-select-for-update-fix-001--3c8b768534.html) | `passed` | 0.650 | `True` | `ir_checklist` | `answer_json_bridge` | 0.000 | 78 | traj, tx |
| [envoy-dfp-host-leak-fix-001](../tasks/csb_sdlc_fix_haiku_20260301_173337--baseline-local-direct--envoy-dfp-host-leak-fix-001--7aa4a34e54.html) | `passed` | 0.754 | `True` | `diff_similarity` | `answer_json_bridge` | 0.000 | 47 | traj, tx |
| [envoy-udp-proxy-cds-fix-001](../tasks/csb_sdlc_fix_haiku_20260301_173337--baseline-local-direct--envoy-udp-proxy-cds-fix-001--6b9dcde07c.html) | `passed` | 0.616 | `True` | `diff_similarity` | `answer_json_bridge` | 0.000 | 45 | traj, tx |
| [flipt-eval-latency-fix-001](../tasks/csb_sdlc_fix_haiku_20260301_173337--baseline-local-direct--flipt-eval-latency-fix-001--87a1006e61.html) | `passed` | 0.550 | `True` | `-` | `-` | 0.000 | 28 | traj, tx |
| [k8s-dra-scheduler-event-fix-001](../tasks/csb_sdlc_fix_haiku_20260301_173337--baseline-local-direct--k8s-dra-scheduler-event-fix-001--b70158a9aa.html) | `passed` | 0.750 | `True` | `ir_checklist` | `answer_json_bridge` | 0.000 | 40 | traj, tx |
| [kafka-producer-bufpool-fix-001](../tasks/csb_sdlc_fix_haiku_20260301_173337--baseline-local-direct--kafka-producer-bufpool-fix-001--392ba44b2b.html) | `passed` | 0.740 | `True` | `ir_checklist` | `answer_json_bridge` | 0.000 | 31 | traj, tx |
| [terraform-plan-null-unknown-fix-001](../tasks/csb_sdlc_fix_haiku_20260301_173337--baseline-local-direct--terraform-plan-null-unknown-fix-001--b8bcc8f9cc.html) | `passed` | 0.865 | `True` | `diff_similarity` | `answer_json_bridge` | 0.000 | 78 | traj, tx |

## mcp-remote-direct

- Valid tasks: `5`
- Mean reward: `0.646`
- Pass rate: `1.000`
- Scorer families: `ir_checklist (3), repo_state_heuristic (1), unknown (1)`
- Output contracts: `answer_json_bridge (4), unknown (1)`

| Task | Status | Reward | Passed | Scorer Family | Output Contract | MCP Ratio | Tool Calls | Trace |
|---|---|---:|---|---|---|---:|---:|---|
| [mcp_django-modelchoice-fk-fix-001_0piinq](../tasks/csb_sdlc_fix_haiku_20260301_173337--mcp-remote-direct--mcp_django-modelchoice-fk-fix-001_0piinq--7ac1faee18.html) | `passed` | 0.750 | `True` | `repo_state_heuristic` | `answer_json_bridge` | 0.561 | 66 | traj, tx |
| [mcp_django-select-for-update-fix-001_8tqisu](../tasks/csb_sdlc_fix_haiku_20260301_173337--mcp-remote-direct--mcp_django-select-for-update-fix-001_8tqisu--b170413d79.html) | `passed` | 0.730 | `True` | `ir_checklist` | `answer_json_bridge` | 0.525 | 59 | traj, tx |
| [mcp_flipt-eval-latency-fix-001_vcbcjj](../tasks/csb_sdlc_fix_haiku_20260301_173337--mcp-remote-direct--mcp_flipt-eval-latency-fix-001_vcbcjj--1e2c350603.html) | `passed` | 0.250 | `True` | `-` | `-` | 0.188 | 32 | traj, tx |
| [mcp_k8s-dra-scheduler-event-fix-001_przixb](../tasks/csb_sdlc_fix_haiku_20260301_173337--mcp-remote-direct--mcp_k8s-dra-scheduler-event-fix-001_przixb--aa0180b5b3.html) | `passed` | 0.670 | `True` | `ir_checklist` | `answer_json_bridge` | 0.815 | 27 | traj, tx |
| [mcp_kafka-producer-bufpool-fix-001_iaiawb](../tasks/csb_sdlc_fix_haiku_20260301_173337--mcp-remote-direct--mcp_kafka-producer-bufpool-fix-001_iaiawb--1de5e506ee.html) | `passed` | 0.830 | `True` | `ir_checklist` | `answer_json_bridge` | 0.780 | 50 | traj, tx |
