# csb_sdlc_fix_haiku_20260228_205741

## baseline-local-direct

- Valid tasks: `25`
- Mean reward: `0.440`
- Pass rate: `0.600`
- Scorer families: `unknown (10), diff_similarity (8), ir_checklist (3), test_ratio (3), repo_state_heuristic (1)`
- Output contracts: `answer_json_bridge (15), unknown (10)`

| Task | Status | Reward | Passed | Scorer Family | Output Contract | MCP Ratio | Tool Calls | Trace |
|---|---|---:|---|---|---|---:|---:|---|
| [django-modelchoice-fk-fix-001](../tasks/csb_sdlc_fix_haiku_20260228_205741--baseline-local-direct--django-modelchoice-fk-fix-001--427003295d.html) | `failed` | 0.000 | `False` | `repo_state_heuristic` | `answer_json_bridge` | 0.000 | 246 | traj, tx |
| [navidrome-windows-log-fix-001](../tasks/csb_sdlc_fix_haiku_20260228_205741--baseline-local-direct--navidrome-windows-log-fix-001--77156871d9.html) | `failed` | 0.000 | `False` | `-` | `-` | 0.000 | 5 | traj, tx |
| [nodebb-notif-dropdown-fix-001](../tasks/csb_sdlc_fix_haiku_20260228_205741--baseline-local-direct--nodebb-notif-dropdown-fix-001--3c6c7cfc96.html) | `failed` | 0.000 | `False` | `test_ratio` | `answer_json_bridge` | 0.000 | 3 | traj, tx |
| [nodebb-plugin-validate-fix-001](../tasks/csb_sdlc_fix_haiku_20260228_205741--baseline-local-direct--nodebb-plugin-validate-fix-001--c0fda6e01f.html) | `failed` | 0.000 | `None` | `test_ratio` | `answer_json_bridge` | - | - | traj, tx |
| [openlibrary-search-query-fix-001](../tasks/csb_sdlc_fix_haiku_20260228_205741--baseline-local-direct--openlibrary-search-query-fix-001--7167e729ac.html) | `failed` | 0.000 | `False` | `-` | `-` | 0.000 | 44 | traj, tx |
| [openlibrary-solr-boolean-fix-001](../tasks/csb_sdlc_fix_haiku_20260228_205741--baseline-local-direct--openlibrary-solr-boolean-fix-001--4d2b5dd3c6.html) | `failed` | 0.000 | `False` | `-` | `-` | 0.000 | 35 | traj, tx |
| [pytorch-cudnn-version-fix-001](../tasks/csb_sdlc_fix_haiku_20260228_205741--baseline-local-direct--pytorch-cudnn-version-fix-001--1c8bd172c6.html) | `failed` | 0.000 | `False` | `diff_similarity` | `answer_json_bridge` | 0.000 | 51 | traj, tx |
| [pytorch-dynamo-keyerror-fix-001](../tasks/csb_sdlc_fix_haiku_20260228_205741--baseline-local-direct--pytorch-dynamo-keyerror-fix-001--33f01665f3.html) | `failed` | 0.000 | `False` | `diff_similarity` | `answer_json_bridge` | 0.000 | 113 | traj, tx |
| [pytorch-release-210-fix-001](../tasks/csb_sdlc_fix_haiku_20260228_205741--baseline-local-direct--pytorch-release-210-fix-001--31bdaa1a6e.html) | `failed` | 0.000 | `False` | `diff_similarity` | `answer_json_bridge` | 0.000 | 40 | traj, tx |
| [pytorch-tracer-graph-cleanup-fix-001](../tasks/csb_sdlc_fix_haiku_20260228_205741--baseline-local-direct--pytorch-tracer-graph-cleanup-fix-001--ab9cc73169.html) | `failed` | 0.000 | `False` | `diff_similarity` | `answer_json_bridge` | 0.000 | 121 | traj, tx |
| [ansible-abc-imports-fix-001](../tasks/csb_sdlc_fix_haiku_20260228_205741--baseline-local-direct--ansible-abc-imports-fix-001--c3cc94de7b.html) | `passed` | 0.943 | `True` | `test_ratio` | `answer_json_bridge` | 0.000 | 55 | traj, tx |
| [ansible-module-respawn-fix-001](../tasks/csb_sdlc_fix_haiku_20260228_205741--baseline-local-direct--ansible-module-respawn-fix-001--80cafde48e.html) | `passed` | 0.471 | `True` | `-` | `-` | 0.000 | 141 | traj, tx |
| [django-select-for-update-fix-001](../tasks/csb_sdlc_fix_haiku_20260228_205741--baseline-local-direct--django-select-for-update-fix-001--a1ad6179bf.html) | `passed` | 0.650 | `True` | `ir_checklist` | `answer_json_bridge` | 0.000 | 54 | traj, tx |
| [envoy-dfp-host-leak-fix-001](../tasks/csb_sdlc_fix_haiku_20260228_205741--baseline-local-direct--envoy-dfp-host-leak-fix-001--18be687f0b.html) | `passed` | 0.757 | `True` | `diff_similarity` | `answer_json_bridge` | 0.000 | 29 | traj, tx |
| [envoy-udp-proxy-cds-fix-001](../tasks/csb_sdlc_fix_haiku_20260228_205741--baseline-local-direct--envoy-udp-proxy-cds-fix-001--5b31ece13a.html) | `passed` | 0.673 | `True` | `diff_similarity` | `answer_json_bridge` | 0.000 | 47 | traj, tx |
| [flipt-cockroachdb-backend-fix-001](../tasks/csb_sdlc_fix_haiku_20260228_205741--baseline-local-direct--flipt-cockroachdb-backend-fix-001--123c8daf86.html) | `passed` | 0.973 | `True` | `-` | `-` | 0.000 | 106 | traj, tx |
| [flipt-ecr-auth-oci-fix-001](../tasks/csb_sdlc_fix_haiku_20260228_205741--baseline-local-direct--flipt-ecr-auth-oci-fix-001--b7d3252beb.html) | `passed` | 0.987 | `True` | `-` | `-` | 0.000 | 227 | traj, tx |
| [flipt-eval-latency-fix-001](../tasks/csb_sdlc_fix_haiku_20260228_205741--baseline-local-direct--flipt-eval-latency-fix-001--bd87f5c0df.html) | `passed` | 0.250 | `True` | `-` | `-` | 0.000 | 38 | traj, tx |
| [flipt-otlp-exporter-fix-001](../tasks/csb_sdlc_fix_haiku_20260228_205741--baseline-local-direct--flipt-otlp-exporter-fix-001--d1e459aac1.html) | `passed` | 0.978 | `True` | `-` | `-` | 0.000 | 84 | traj, tx |
| [flipt-trace-sampling-fix-001](../tasks/csb_sdlc_fix_haiku_20260228_205741--baseline-local-direct--flipt-trace-sampling-fix-001--35415b0fd4.html) | `passed` | 0.984 | `True` | `-` | `-` | 0.000 | 96 | traj, tx |
| [k8s-dra-scheduler-event-fix-001](../tasks/csb_sdlc_fix_haiku_20260228_205741--baseline-local-direct--k8s-dra-scheduler-event-fix-001--8d9d4b335a.html) | `passed` | 0.800 | `True` | `ir_checklist` | `answer_json_bridge` | 0.000 | 45 | traj, tx |
| [kafka-producer-bufpool-fix-001](../tasks/csb_sdlc_fix_haiku_20260228_205741--baseline-local-direct--kafka-producer-bufpool-fix-001--dcb6d550af.html) | `passed` | 0.740 | `True` | `ir_checklist` | `answer_json_bridge` | 0.000 | 29 | traj, tx |
| [openlibrary-fntocli-adapter-fix-001](../tasks/csb_sdlc_fix_haiku_20260228_205741--baseline-local-direct--openlibrary-fntocli-adapter-fix-001--3b68acf5ab.html) | `passed` | 0.667 | `True` | `-` | `-` | 0.000 | 40 | traj, tx |
| [pytorch-relu-gelu-fusion-fix-001](../tasks/csb_sdlc_fix_haiku_20260228_205741--baseline-local-direct--pytorch-relu-gelu-fusion-fix-001--577dede274.html) | `passed` | 0.376 | `True` | `diff_similarity` | `answer_json_bridge` | 0.000 | 39 | traj, tx |
| [terraform-plan-null-unknown-fix-001](../tasks/csb_sdlc_fix_haiku_20260228_205741--baseline-local-direct--terraform-plan-null-unknown-fix-001--0e2e423d7d.html) | `passed` | 0.753 | `True` | `diff_similarity` | `answer_json_bridge` | 0.000 | 107 | traj, tx |

## mcp-remote-direct

- Valid tasks: `25`
- Mean reward: `0.536`
- Pass rate: `0.680`
- Scorer families: `unknown (10), diff_similarity (8), ir_checklist (3), test_ratio (3), repo_state_heuristic (1)`
- Output contracts: `answer_json_bridge (15), unknown (10)`

| Task | Status | Reward | Passed | Scorer Family | Output Contract | MCP Ratio | Tool Calls | Trace |
|---|---|---:|---|---|---|---:|---:|---|
| [mcp_navidrome-windows-log-fix-001_Mhwc1X](../tasks/csb_sdlc_fix_haiku_20260228_205741--mcp-remote-direct--mcp_navidrome-windows-log-fix-001_Mhwc1X--4c3a588889.html) | `failed` | 0.000 | `False` | `-` | `-` | 0.389 | 18 | traj, tx |
| [mcp_nodebb-notif-dropdown-fix-001_Y18fTO](../tasks/csb_sdlc_fix_haiku_20260228_205741--mcp-remote-direct--mcp_nodebb-notif-dropdown-fix-001_Y18fTO--ebd701d815.html) | `failed` | 0.000 | `False` | `test_ratio` | `answer_json_bridge` | 0.448 | 67 | traj, tx |
| [mcp_nodebb-plugin-validate-fix-001_jEmJS6](../tasks/csb_sdlc_fix_haiku_20260228_205741--mcp-remote-direct--mcp_nodebb-plugin-validate-fix-001_jEmJS6--cc7b3cfdfe.html) | `failed` | 0.000 | `False` | `test_ratio` | `answer_json_bridge` | 0.140 | 86 | traj, tx |
| [mcp_openlibrary-search-query-fix-001_HmH4et](../tasks/csb_sdlc_fix_haiku_20260228_205741--mcp-remote-direct--mcp_openlibrary-search-query-fix-001_HmH4et--914a3c6603.html) | `failed` | 0.000 | `False` | `-` | `-` | 0.097 | 62 | traj, tx |
| [mcp_pytorch-cudnn-version-fix-001_fvmrS7](../tasks/csb_sdlc_fix_haiku_20260228_205741--mcp-remote-direct--mcp_pytorch-cudnn-version-fix-001_fvmrS7--26cf04b32a.html) | `failed` | 0.000 | `False` | `diff_similarity` | `answer_json_bridge` | 0.594 | 32 | traj, tx |
| [mcp_pytorch-dynamo-keyerror-fix-001_4XJYYk](../tasks/csb_sdlc_fix_haiku_20260228_205741--mcp-remote-direct--mcp_pytorch-dynamo-keyerror-fix-001_4XJYYk--af13bccae7.html) | `failed` | 0.000 | `False` | `diff_similarity` | `answer_json_bridge` | 0.303 | 66 | traj, tx |
| [mcp_pytorch-release-210-fix-001_HdQkmt](../tasks/csb_sdlc_fix_haiku_20260228_205741--mcp-remote-direct--mcp_pytorch-release-210-fix-001_HdQkmt--7b713ce9d8.html) | `failed` | 0.000 | `False` | `diff_similarity` | `answer_json_bridge` | 0.326 | 46 | traj, tx |
| [mcp_pytorch-tracer-graph-cleanup-fix-001_2j86Q8](../tasks/csb_sdlc_fix_haiku_20260228_205741--mcp-remote-direct--mcp_pytorch-tracer-graph-cleanup-fix-001_2j86Q8--e7b8c9fd39.html) | `failed` | 0.000 | `False` | `diff_similarity` | `answer_json_bridge` | 0.750 | 124 | traj, tx |
| [mcp_ansible-abc-imports-fix-001_1RC942](../tasks/csb_sdlc_fix_haiku_20260228_205741--mcp-remote-direct--mcp_ansible-abc-imports-fix-001_1RC942--d62b87cc57.html) | `passed` | 1.000 | `True` | `test_ratio` | `answer_json_bridge` | 0.347 | 75 | traj, tx |
| [mcp_ansible-module-respawn-fix-001_LEYP9n](../tasks/csb_sdlc_fix_haiku_20260228_205741--mcp-remote-direct--mcp_ansible-module-respawn-fix-001_LEYP9n--07fd09221b.html) | `passed` | 1.000 | `True` | `-` | `-` | 0.224 | 85 | traj, tx |
| [mcp_django-modelchoice-fk-fix-001_ZcKvvz](../tasks/csb_sdlc_fix_haiku_20260228_205741--mcp-remote-direct--mcp_django-modelchoice-fk-fix-001_ZcKvvz--1609ba3cb7.html) | `passed` | 0.600 | `True` | `repo_state_heuristic` | `answer_json_bridge` | 0.533 | 92 | traj, tx |
| [mcp_django-select-for-update-fix-001_eOai5V](../tasks/csb_sdlc_fix_haiku_20260228_205741--mcp-remote-direct--mcp_django-select-for-update-fix-001_eOai5V--42192ed195.html) | `passed` | 0.730 | `True` | `ir_checklist` | `answer_json_bridge` | 0.714 | 28 | traj, tx |
| [mcp_envoy-dfp-host-leak-fix-001_4Rh5W8](../tasks/csb_sdlc_fix_haiku_20260228_205741--mcp-remote-direct--mcp_envoy-dfp-host-leak-fix-001_4Rh5W8--25535d427a.html) | `passed` | 0.714 | `True` | `diff_similarity` | `answer_json_bridge` | 0.415 | 53 | traj, tx |
| [mcp_envoy-udp-proxy-cds-fix-001_LNuaR3](../tasks/csb_sdlc_fix_haiku_20260228_205741--mcp-remote-direct--mcp_envoy-udp-proxy-cds-fix-001_LNuaR3--7f57ff788f.html) | `passed` | 0.747 | `True` | `diff_similarity` | `answer_json_bridge` | 0.260 | 50 | traj, tx |
| [mcp_flipt-cockroachdb-backend-fix-001_N3scMz](../tasks/csb_sdlc_fix_haiku_20260228_205741--mcp-remote-direct--mcp_flipt-cockroachdb-backend-fix-001_N3scMz--182ef59191.html) | `passed` | 0.973 | `True` | `-` | `-` | 0.295 | 88 | traj, tx |
| [mcp_flipt-ecr-auth-oci-fix-001_sHO3qF](../tasks/csb_sdlc_fix_haiku_20260228_205741--mcp-remote-direct--mcp_flipt-ecr-auth-oci-fix-001_sHO3qF--a1835bef2a.html) | `passed` | 0.995 | `True` | `-` | `-` | 0.338 | 65 | traj, tx |
| [mcp_flipt-eval-latency-fix-001_DFlDZt](../tasks/csb_sdlc_fix_haiku_20260228_205741--mcp-remote-direct--mcp_flipt-eval-latency-fix-001_DFlDZt--0ed9927945.html) | `passed` | 0.300 | `True` | `-` | `-` | 0.241 | 58 | traj, tx |
| [mcp_flipt-otlp-exporter-fix-001_RiZOtB](../tasks/csb_sdlc_fix_haiku_20260228_205741--mcp-remote-direct--mcp_flipt-otlp-exporter-fix-001_RiZOtB--918c54cffe.html) | `passed` | 0.979 | `True` | `-` | `-` | 0.188 | 96 | traj, tx |
| [mcp_flipt-trace-sampling-fix-001_DljxDi](../tasks/csb_sdlc_fix_haiku_20260228_205741--mcp-remote-direct--mcp_flipt-trace-sampling-fix-001_DljxDi--5c8c5db460.html) | `passed` | 0.985 | `True` | `-` | `-` | 0.092 | 142 | traj, tx |
| [mcp_k8s-dra-scheduler-event-fix-001_6KeDnw](../tasks/csb_sdlc_fix_haiku_20260228_205741--mcp-remote-direct--mcp_k8s-dra-scheduler-event-fix-001_6KeDnw--1189aa5a9c.html) | `passed` | 0.740 | `True` | `ir_checklist` | `answer_json_bridge` | 0.727 | 22 | traj, tx |
| [mcp_kafka-producer-bufpool-fix-001_dUp4AH](../tasks/csb_sdlc_fix_haiku_20260228_205741--mcp-remote-direct--mcp_kafka-producer-bufpool-fix-001_dUp4AH--37567e1a9f.html) | `passed` | 0.740 | `True` | `ir_checklist` | `answer_json_bridge` | 0.972 | 36 | traj, tx |
| [mcp_openlibrary-fntocli-adapter-fix-001_ODhL8U](../tasks/csb_sdlc_fix_haiku_20260228_205741--mcp-remote-direct--mcp_openlibrary-fntocli-adapter-fix-001_ODhL8U--266271bda8.html) | `passed` | 1.000 | `True` | `-` | `-` | 0.265 | 34 | traj, tx |
| [mcp_openlibrary-solr-boolean-fix-001_FLeVXK](../tasks/csb_sdlc_fix_haiku_20260228_205741--mcp-remote-direct--mcp_openlibrary-solr-boolean-fix-001_FLeVXK--f071cd6988.html) | `passed` | 0.667 | `True` | `-` | `-` | - | - | tx |
| [mcp_pytorch-relu-gelu-fusion-fix-001_he6k9B](../tasks/csb_sdlc_fix_haiku_20260228_205741--mcp-remote-direct--mcp_pytorch-relu-gelu-fusion-fix-001_he6k9B--85e6a886b8.html) | `passed` | 0.654 | `True` | `diff_similarity` | `answer_json_bridge` | 0.398 | 83 | traj, tx |
| [mcp_terraform-plan-null-unknown-fix-001_RIfUuo](../tasks/csb_sdlc_fix_haiku_20260228_205741--mcp-remote-direct--mcp_terraform-plan-null-unknown-fix-001_RIfUuo--927fe3af1e.html) | `passed` | 0.576 | `True` | `diff_similarity` | `answer_json_bridge` | 0.317 | 101 | traj, tx |
