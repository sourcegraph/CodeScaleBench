# csb_sdlc_fix_haiku_20260228_185835

## baseline-local-direct

- Valid tasks: `25`
- Mean reward: `0.471`
- Pass rate: `0.640`
- Scorer families: `unknown (10), diff_similarity (8), ir_checklist (3), test_ratio (3), repo_state_heuristic (1)`
- Output contracts: `answer_json_bridge (15), unknown (10)`

| Task | Status | Reward | Passed | Scorer Family | Output Contract | MCP Ratio | Tool Calls | Trace |
|---|---|---:|---|---|---|---:|---:|---|
| [navidrome-windows-log-fix-001](../tasks/csb_sdlc_fix_haiku_20260228_185835--baseline-local-direct--navidrome-windows-log-fix-001--a92c9ac855.html) | `failed` | 0.000 | `False` | `-` | `-` | 0.000 | 47 | traj, tx |
| [nodebb-notif-dropdown-fix-001](../tasks/csb_sdlc_fix_haiku_20260228_185835--baseline-local-direct--nodebb-notif-dropdown-fix-001--919883b897.html) | `failed` | 0.000 | `False` | `test_ratio` | `answer_json_bridge` | 0.000 | 139 | traj, tx |
| [nodebb-plugin-validate-fix-001](../tasks/csb_sdlc_fix_haiku_20260228_185835--baseline-local-direct--nodebb-plugin-validate-fix-001--8c23c62541.html) | `failed` | 0.000 | `False` | `test_ratio` | `answer_json_bridge` | 0.000 | 73 | traj, tx |
| [openlibrary-search-query-fix-001](../tasks/csb_sdlc_fix_haiku_20260228_185835--baseline-local-direct--openlibrary-search-query-fix-001--b9be83224f.html) | `failed` | 0.000 | `False` | `-` | `-` | 0.000 | 157 | traj, tx |
| [openlibrary-solr-boolean-fix-001](../tasks/csb_sdlc_fix_haiku_20260228_185835--baseline-local-direct--openlibrary-solr-boolean-fix-001--5cf3b8824b.html) | `failed` | 0.000 | `False` | `-` | `-` | 0.000 | 33 | traj, tx |
| [pytorch-cudnn-version-fix-001](../tasks/csb_sdlc_fix_haiku_20260228_185835--baseline-local-direct--pytorch-cudnn-version-fix-001--7d23af7834.html) | `failed` | 0.000 | `False` | `diff_similarity` | `answer_json_bridge` | 0.000 | 80 | traj, tx |
| [pytorch-dynamo-keyerror-fix-001](../tasks/csb_sdlc_fix_haiku_20260228_185835--baseline-local-direct--pytorch-dynamo-keyerror-fix-001--4b900d0bb5.html) | `failed` | 0.000 | `False` | `diff_similarity` | `answer_json_bridge` | 0.000 | 79 | traj, tx |
| [pytorch-release-210-fix-001](../tasks/csb_sdlc_fix_haiku_20260228_185835--baseline-local-direct--pytorch-release-210-fix-001--b8ed532211.html) | `failed` | 0.000 | `False` | `diff_similarity` | `answer_json_bridge` | 0.000 | 94 | traj, tx |
| [pytorch-tracer-graph-cleanup-fix-001](../tasks/csb_sdlc_fix_haiku_20260228_185835--baseline-local-direct--pytorch-tracer-graph-cleanup-fix-001--8d55eaecb1.html) | `failed` | 0.000 | `False` | `diff_similarity` | `answer_json_bridge` | 0.000 | 81 | traj, tx |
| [ansible-abc-imports-fix-001](../tasks/csb_sdlc_fix_haiku_20260228_185835--baseline-local-direct--ansible-abc-imports-fix-001--5b2b51eaa9.html) | `passed` | 0.943 | `True` | `test_ratio` | `answer_json_bridge` | 0.000 | 114 | traj, tx |
| [ansible-module-respawn-fix-001](../tasks/csb_sdlc_fix_haiku_20260228_185835--baseline-local-direct--ansible-module-respawn-fix-001--4044268088.html) | `passed` | 0.471 | `True` | `-` | `-` | 0.000 | 6 | traj, tx |
| [django-modelchoice-fk-fix-001](../tasks/csb_sdlc_fix_haiku_20260228_185835--baseline-local-direct--django-modelchoice-fk-fix-001--a4a7cba3bf.html) | `passed` | 0.450 | `True` | `repo_state_heuristic` | `answer_json_bridge` | 0.000 | 142 | traj, tx |
| [django-select-for-update-fix-001](../tasks/csb_sdlc_fix_haiku_20260228_185835--baseline-local-direct--django-select-for-update-fix-001--507f4a6f70.html) | `passed` | 0.670 | `True` | `ir_checklist` | `answer_json_bridge` | 0.000 | 55 | traj, tx |
| [envoy-dfp-host-leak-fix-001](../tasks/csb_sdlc_fix_haiku_20260228_185835--baseline-local-direct--envoy-dfp-host-leak-fix-001--a7ca74de98.html) | `passed` | 0.791 | `True` | `diff_similarity` | `answer_json_bridge` | 0.000 | 79 | traj, tx |
| [envoy-udp-proxy-cds-fix-001](../tasks/csb_sdlc_fix_haiku_20260228_185835--baseline-local-direct--envoy-udp-proxy-cds-fix-001--afe00ccff6.html) | `passed` | 0.740 | `True` | `diff_similarity` | `answer_json_bridge` | 0.000 | 30 | traj, tx |
| [flipt-cockroachdb-backend-fix-001](../tasks/csb_sdlc_fix_haiku_20260228_185835--baseline-local-direct--flipt-cockroachdb-backend-fix-001--a22dfbbaa5.html) | `passed` | 0.973 | `True` | `-` | `-` | 0.000 | 179 | traj, tx |
| [flipt-ecr-auth-oci-fix-001](../tasks/csb_sdlc_fix_haiku_20260228_185835--baseline-local-direct--flipt-ecr-auth-oci-fix-001--af31df4aff.html) | `passed` | 0.987 | `True` | `-` | `-` | 0.000 | 88 | traj, tx |
| [flipt-eval-latency-fix-001](../tasks/csb_sdlc_fix_haiku_20260228_185835--baseline-local-direct--flipt-eval-latency-fix-001--55525d1c2c.html) | `passed` | 0.250 | `True` | `-` | `-` | 0.000 | 34 | traj, tx |
| [flipt-otlp-exporter-fix-001](../tasks/csb_sdlc_fix_haiku_20260228_185835--baseline-local-direct--flipt-otlp-exporter-fix-001--9f0e55d8b1.html) | `passed` | 0.978 | `True` | `-` | `-` | 0.000 | 75 | traj, tx |
| [flipt-trace-sampling-fix-001](../tasks/csb_sdlc_fix_haiku_20260228_185835--baseline-local-direct--flipt-trace-sampling-fix-001--3f1d3d1519.html) | `passed` | 0.984 | `True` | `-` | `-` | 0.000 | 128 | traj, tx |
| [k8s-dra-scheduler-event-fix-001](../tasks/csb_sdlc_fix_haiku_20260228_185835--baseline-local-direct--k8s-dra-scheduler-event-fix-001--69f629b946.html) | `passed` | 0.730 | `True` | `ir_checklist` | `answer_json_bridge` | 0.000 | 48 | traj, tx |
| [kafka-producer-bufpool-fix-001](../tasks/csb_sdlc_fix_haiku_20260228_185835--baseline-local-direct--kafka-producer-bufpool-fix-001--d5d2626f83.html) | `passed` | 0.650 | `True` | `ir_checklist` | `answer_json_bridge` | 0.000 | 43 | traj, tx |
| [openlibrary-fntocli-adapter-fix-001](../tasks/csb_sdlc_fix_haiku_20260228_185835--baseline-local-direct--openlibrary-fntocli-adapter-fix-001--c9409212d5.html) | `passed` | 0.667 | `True` | `-` | `-` | 0.000 | 26 | traj, tx |
| [pytorch-relu-gelu-fusion-fix-001](../tasks/csb_sdlc_fix_haiku_20260228_185835--baseline-local-direct--pytorch-relu-gelu-fusion-fix-001--1c0270ae83.html) | `passed` | 0.654 | `True` | `diff_similarity` | `answer_json_bridge` | 0.000 | 44 | traj, tx |
| [terraform-plan-null-unknown-fix-001](../tasks/csb_sdlc_fix_haiku_20260228_185835--baseline-local-direct--terraform-plan-null-unknown-fix-001--438c090131.html) | `passed` | 0.841 | `True` | `diff_similarity` | `answer_json_bridge` | 0.000 | 61 | traj, tx |

## mcp-remote-direct

- Valid tasks: `25`
- Mean reward: `0.592`
- Pass rate: `0.720`
- Scorer families: `unknown (10), diff_similarity (8), ir_checklist (3), test_ratio (3), repo_state_heuristic (1)`
- Output contracts: `answer_json_bridge (15), unknown (10)`

| Task | Status | Reward | Passed | Scorer Family | Output Contract | MCP Ratio | Tool Calls | Trace |
|---|---|---:|---|---|---|---:|---:|---|
| [mcp_navidrome-windows-log-fix-001_QfarEE](../tasks/csb_sdlc_fix_haiku_20260228_185835--mcp-remote-direct--mcp_navidrome-windows-log-fix-001_QfarEE--d859654785.html) | `failed` | 0.000 | `False` | `-` | `-` | 0.310 | 29 | traj, tx |
| [mcp_nodebb-notif-dropdown-fix-001_fbthJ3](../tasks/csb_sdlc_fix_haiku_20260228_185835--mcp-remote-direct--mcp_nodebb-notif-dropdown-fix-001_fbthJ3--bb7b88f669.html) | `failed` | 0.000 | `False` | `test_ratio` | `answer_json_bridge` | 0.274 | 73 | traj, tx |
| [mcp_nodebb-plugin-validate-fix-001_r0VSJI](../tasks/csb_sdlc_fix_haiku_20260228_185835--mcp-remote-direct--mcp_nodebb-plugin-validate-fix-001_r0VSJI--f3407d12e3.html) | `failed` | 0.000 | `False` | `test_ratio` | `answer_json_bridge` | 0.100 | 100 | traj, tx |
| [mcp_openlibrary-search-query-fix-001_wxswww](../tasks/csb_sdlc_fix_haiku_20260228_185835--mcp-remote-direct--mcp_openlibrary-search-query-fix-001_wxswww--3907edb9ac.html) | `failed` | 0.000 | `False` | `-` | `-` | 0.203 | 69 | traj, tx |
| [mcp_pytorch-cudnn-version-fix-001_5MmKdu](../tasks/csb_sdlc_fix_haiku_20260228_185835--mcp-remote-direct--mcp_pytorch-cudnn-version-fix-001_5MmKdu--aa84003b7e.html) | `failed` | 0.000 | `False` | `diff_similarity` | `answer_json_bridge` | 0.590 | 61 | traj, tx |
| [mcp_pytorch-dynamo-keyerror-fix-001_ufG1h3](../tasks/csb_sdlc_fix_haiku_20260228_185835--mcp-remote-direct--mcp_pytorch-dynamo-keyerror-fix-001_ufG1h3--6be1a0e23f.html) | `failed` | 0.000 | `False` | `diff_similarity` | `answer_json_bridge` | 0.507 | 146 | traj, tx |
| [mcp_pytorch-tracer-graph-cleanup-fix-001_o7Q3V3](../tasks/csb_sdlc_fix_haiku_20260228_185835--mcp-remote-direct--mcp_pytorch-tracer-graph-cleanup-fix-001_o7Q3V3--7748c6bc07.html) | `failed` | 0.000 | `False` | `diff_similarity` | `answer_json_bridge` | 0.485 | 134 | traj, tx |
| [mcp_ansible-abc-imports-fix-001_4HZCfw](../tasks/csb_sdlc_fix_haiku_20260228_185835--mcp-remote-direct--mcp_ansible-abc-imports-fix-001_4HZCfw--3d2d587a75.html) | `passed` | 1.000 | `True` | `test_ratio` | `answer_json_bridge` | 0.289 | 135 | traj, tx |
| [mcp_ansible-module-respawn-fix-001_Hgtxog](../tasks/csb_sdlc_fix_haiku_20260228_185835--mcp-remote-direct--mcp_ansible-module-respawn-fix-001_Hgtxog--4de117f29a.html) | `passed` | 1.000 | `True` | `-` | `-` | 0.296 | 125 | traj, tx |
| [mcp_django-modelchoice-fk-fix-001_rCYt5Z](../tasks/csb_sdlc_fix_haiku_20260228_185835--mcp-remote-direct--mcp_django-modelchoice-fk-fix-001_rCYt5Z--65c70a2538.html) | `passed` | 0.850 | `True` | `repo_state_heuristic` | `answer_json_bridge` | 0.605 | 76 | traj, tx |
| [mcp_django-select-for-update-fix-001_H0nMDL](../tasks/csb_sdlc_fix_haiku_20260228_185835--mcp-remote-direct--mcp_django-select-for-update-fix-001_H0nMDL--b79b3eda62.html) | `passed` | 0.820 | `True` | `ir_checklist` | `answer_json_bridge` | 0.789 | 38 | traj, tx |
| [mcp_envoy-dfp-host-leak-fix-001_FnvD2P](../tasks/csb_sdlc_fix_haiku_20260228_185835--mcp-remote-direct--mcp_envoy-dfp-host-leak-fix-001_FnvD2P--0fda3b24e2.html) | `passed` | 0.593 | `True` | `diff_similarity` | `answer_json_bridge` | 0.306 | 36 | traj, tx |
| [mcp_envoy-udp-proxy-cds-fix-001_KFbv1E](../tasks/csb_sdlc_fix_haiku_20260228_185835--mcp-remote-direct--mcp_envoy-udp-proxy-cds-fix-001_KFbv1E--0be57c7469.html) | `passed` | 0.669 | `True` | `diff_similarity` | `answer_json_bridge` | 0.279 | 43 | traj, tx |
| [mcp_flipt-cockroachdb-backend-fix-001_O93D7t](../tasks/csb_sdlc_fix_haiku_20260228_185835--mcp-remote-direct--mcp_flipt-cockroachdb-backend-fix-001_O93D7t--877562e65e.html) | `passed` | 0.973 | `True` | `-` | `-` | 0.205 | 83 | traj, tx |
| [mcp_flipt-ecr-auth-oci-fix-001_8o7G78](../tasks/csb_sdlc_fix_haiku_20260228_185835--mcp-remote-direct--mcp_flipt-ecr-auth-oci-fix-001_8o7G78--78a8fca4b2.html) | `passed` | 0.995 | `True` | `-` | `-` | 0.185 | 81 | traj, tx |
| [mcp_flipt-eval-latency-fix-001_gQ5wnj](../tasks/csb_sdlc_fix_haiku_20260228_185835--mcp-remote-direct--mcp_flipt-eval-latency-fix-001_gQ5wnj--eeb60f089f.html) | `passed` | 0.550 | `True` | `-` | `-` | 0.140 | 43 | traj, tx |
| [mcp_flipt-otlp-exporter-fix-001_aZH2yD](../tasks/csb_sdlc_fix_haiku_20260228_185835--mcp-remote-direct--mcp_flipt-otlp-exporter-fix-001_aZH2yD--33c1f139ce.html) | `passed` | 0.979 | `True` | `-` | `-` | 0.355 | 62 | traj, tx |
| [mcp_flipt-trace-sampling-fix-001_HHLWjw](../tasks/csb_sdlc_fix_haiku_20260228_185835--mcp-remote-direct--mcp_flipt-trace-sampling-fix-001_HHLWjw--07906a2a55.html) | `passed` | 0.985 | `True` | `-` | `-` | 0.353 | 51 | traj, tx |
| [mcp_k8s-dra-scheduler-event-fix-001_VRGt4l](../tasks/csb_sdlc_fix_haiku_20260228_185835--mcp-remote-direct--mcp_k8s-dra-scheduler-event-fix-001_VRGt4l--b88fac8404.html) | `passed` | 0.810 | `True` | `ir_checklist` | `answer_json_bridge` | 0.885 | 26 | traj, tx |
| [mcp_kafka-producer-bufpool-fix-001_B3DWiu](../tasks/csb_sdlc_fix_haiku_20260228_185835--mcp-remote-direct--mcp_kafka-producer-bufpool-fix-001_B3DWiu--ebbf5f0251.html) | `passed` | 0.690 | `True` | `ir_checklist` | `answer_json_bridge` | 0.780 | 41 | traj, tx |
| [mcp_openlibrary-fntocli-adapter-fix-001_IMvWES](../tasks/csb_sdlc_fix_haiku_20260228_185835--mcp-remote-direct--mcp_openlibrary-fntocli-adapter-fix-001_IMvWES--7d73bb3f3f.html) | `passed` | 1.000 | `True` | `-` | `-` | 0.193 | 57 | traj, tx |
| [mcp_openlibrary-solr-boolean-fix-001_TeGlod](../tasks/csb_sdlc_fix_haiku_20260228_185835--mcp-remote-direct--mcp_openlibrary-solr-boolean-fix-001_TeGlod--e232ee9724.html) | `passed` | 0.667 | `True` | `-` | `-` | - | - | tx |
| [mcp_pytorch-release-210-fix-001_VZFTMM](../tasks/csb_sdlc_fix_haiku_20260228_185835--mcp-remote-direct--mcp_pytorch-release-210-fix-001_VZFTMM--a6bc64e408.html) | `passed` | 0.787 | `True` | `diff_similarity` | `answer_json_bridge` | 0.208 | 48 | traj, tx |
| [mcp_pytorch-relu-gelu-fusion-fix-001_FMIUaS](../tasks/csb_sdlc_fix_haiku_20260228_185835--mcp-remote-direct--mcp_pytorch-relu-gelu-fusion-fix-001_FMIUaS--398fb0713c.html) | `passed` | 0.656 | `True` | `diff_similarity` | `answer_json_bridge` | 0.448 | 58 | traj, tx |
| [mcp_terraform-plan-null-unknown-fix-001_A0MbH8](../tasks/csb_sdlc_fix_haiku_20260228_185835--mcp-remote-direct--mcp_terraform-plan-null-unknown-fix-001_A0MbH8--3d929ea3ff.html) | `passed` | 0.775 | `True` | `diff_similarity` | `answer_json_bridge` | 0.434 | 152 | traj, tx |
