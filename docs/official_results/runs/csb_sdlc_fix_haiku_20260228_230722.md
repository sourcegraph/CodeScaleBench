# csb_sdlc_fix_haiku_20260228_230722

## baseline-local-direct

- Valid tasks: `20`
- Mean reward: `0.510`
- Pass rate: `0.650`
- Scorer families: `unknown (8), diff_similarity (5), ir_checklist (3), test_ratio (3), repo_state_heuristic (1)`
- Output contracts: `answer_json_bridge (12), unknown (8)`

| Task | Status | Reward | Passed | Scorer Family | Output Contract | MCP Ratio | Tool Calls | Trace |
|---|---|---:|---|---|---|---:|---:|---|
| [django-modelchoice-fk-fix-001](../tasks/csb_sdlc_fix_haiku_20260228_230722--baseline-local-direct--django-modelchoice-fk-fix-001--971961338f.html) | `failed` | 0.000 | `False` | `repo_state_heuristic` | `answer_json_bridge` | 0.000 | 114 | traj, tx |
| [navidrome-windows-log-fix-001](../tasks/csb_sdlc_fix_haiku_20260228_230722--baseline-local-direct--navidrome-windows-log-fix-001--1026ffa28c.html) | `failed` | 0.000 | `False` | `-` | `-` | 0.000 | 52 | traj, tx |
| [nodebb-notif-dropdown-fix-001](../tasks/csb_sdlc_fix_haiku_20260228_230722--baseline-local-direct--nodebb-notif-dropdown-fix-001--8104295534.html) | `failed` | 0.000 | `False` | `test_ratio` | `answer_json_bridge` | 0.000 | 103 | traj, tx |
| [nodebb-plugin-validate-fix-001](../tasks/csb_sdlc_fix_haiku_20260228_230722--baseline-local-direct--nodebb-plugin-validate-fix-001--2d17086589.html) | `failed` | 0.000 | `False` | `test_ratio` | `answer_json_bridge` | 0.000 | 91 | traj, tx |
| [openlibrary-solr-boolean-fix-001](../tasks/csb_sdlc_fix_haiku_20260228_230722--baseline-local-direct--openlibrary-solr-boolean-fix-001--fac3f5da94.html) | `failed` | 0.000 | `False` | `-` | `-` | 0.000 | 34 | traj, tx |
| [pytorch-cudnn-version-fix-001](../tasks/csb_sdlc_fix_haiku_20260228_230722--baseline-local-direct--pytorch-cudnn-version-fix-001--48ce641b3b.html) | `failed` | 0.000 | `False` | `diff_similarity` | `answer_json_bridge` | 0.000 | 123 | traj, tx |
| [pytorch-dynamo-keyerror-fix-001](../tasks/csb_sdlc_fix_haiku_20260228_230722--baseline-local-direct--pytorch-dynamo-keyerror-fix-001--c601faa977.html) | `failed` | 0.000 | `False` | `diff_similarity` | `answer_json_bridge` | 0.000 | 54 | traj, tx |
| [ansible-abc-imports-fix-001](../tasks/csb_sdlc_fix_haiku_20260228_230722--baseline-local-direct--ansible-abc-imports-fix-001--e09de27cbb.html) | `passed` | 0.943 | `True` | `test_ratio` | `answer_json_bridge` | 0.000 | 91 | traj, tx |
| [ansible-module-respawn-fix-001](../tasks/csb_sdlc_fix_haiku_20260228_230722--baseline-local-direct--ansible-module-respawn-fix-001--8a0cb32cfc.html) | `passed` | 0.471 | `True` | `-` | `-` | 0.000 | 98 | traj, tx |
| [django-select-for-update-fix-001](../tasks/csb_sdlc_fix_haiku_20260228_230722--baseline-local-direct--django-select-for-update-fix-001--a16298e069.html) | `passed` | 0.770 | `True` | `ir_checklist` | `answer_json_bridge` | 0.000 | 53 | traj, tx |
| [envoy-dfp-host-leak-fix-001](../tasks/csb_sdlc_fix_haiku_20260228_230722--baseline-local-direct--envoy-dfp-host-leak-fix-001--21a4ad92d7.html) | `passed` | 0.753 | `True` | `diff_similarity` | `answer_json_bridge` | 0.000 | 30 | traj, tx |
| [envoy-udp-proxy-cds-fix-001](../tasks/csb_sdlc_fix_haiku_20260228_230722--baseline-local-direct--envoy-udp-proxy-cds-fix-001--db02b8f792.html) | `passed` | 0.755 | `True` | `diff_similarity` | `answer_json_bridge` | 0.000 | 37 | traj, tx |
| [flipt-cockroachdb-backend-fix-001](../tasks/csb_sdlc_fix_haiku_20260228_230722--baseline-local-direct--flipt-cockroachdb-backend-fix-001--ab33606779.html) | `passed` | 0.973 | `True` | `-` | `-` | 0.000 | 166 | traj, tx |
| [flipt-ecr-auth-oci-fix-001](../tasks/csb_sdlc_fix_haiku_20260228_230722--baseline-local-direct--flipt-ecr-auth-oci-fix-001--2704931ada.html) | `passed` | 0.987 | `True` | `-` | `-` | 0.000 | 4 | traj, tx |
| [flipt-eval-latency-fix-001](../tasks/csb_sdlc_fix_haiku_20260228_230722--baseline-local-direct--flipt-eval-latency-fix-001--3fd584868a.html) | `passed` | 0.250 | `True` | `-` | `-` | 0.000 | 79 | traj, tx |
| [flipt-otlp-exporter-fix-001](../tasks/csb_sdlc_fix_haiku_20260228_230722--baseline-local-direct--flipt-otlp-exporter-fix-001--12753180b3.html) | `passed` | 0.978 | `True` | `-` | `-` | 0.000 | 133 | traj, tx |
| [flipt-trace-sampling-fix-001](../tasks/csb_sdlc_fix_haiku_20260228_230722--baseline-local-direct--flipt-trace-sampling-fix-001--e957b792c6.html) | `passed` | 0.987 | `True` | `-` | `-` | 0.000 | 140 | traj, tx |
| [k8s-dra-scheduler-event-fix-001](../tasks/csb_sdlc_fix_haiku_20260228_230722--baseline-local-direct--k8s-dra-scheduler-event-fix-001--9c68c28a10.html) | `passed` | 0.760 | `True` | `ir_checklist` | `answer_json_bridge` | 0.000 | 66 | traj, tx |
| [kafka-producer-bufpool-fix-001](../tasks/csb_sdlc_fix_haiku_20260228_230722--baseline-local-direct--kafka-producer-bufpool-fix-001--f667a06685.html) | `passed` | 0.660 | `True` | `ir_checklist` | `answer_json_bridge` | 0.000 | 64 | traj, tx |
| [terraform-plan-null-unknown-fix-001](../tasks/csb_sdlc_fix_haiku_20260228_230722--baseline-local-direct--terraform-plan-null-unknown-fix-001--026eb07e5e.html) | `passed` | 0.913 | `True` | `diff_similarity` | `answer_json_bridge` | 0.000 | 76 | traj, tx |

## mcp-remote-direct

- Valid tasks: `20`
- Mean reward: `0.593`
- Pass rate: `0.750`
- Scorer families: `unknown (8), diff_similarity (5), ir_checklist (3), test_ratio (3), repo_state_heuristic (1)`
- Output contracts: `answer_json_bridge (12), unknown (8)`

| Task | Status | Reward | Passed | Scorer Family | Output Contract | MCP Ratio | Tool Calls | Trace |
|---|---|---:|---|---|---|---:|---:|---|
| [mcp_navidrome-windows-log-fix-001_lTqEtf](../tasks/csb_sdlc_fix_haiku_20260228_230722--mcp-remote-direct--mcp_navidrome-windows-log-fix-001_lTqEtf--b7c4891ccc.html) | `failed` | 0.000 | `False` | `-` | `-` | 0.213 | 47 | traj, tx |
| [mcp_nodebb-notif-dropdown-fix-001_ucmNVg](../tasks/csb_sdlc_fix_haiku_20260228_230722--mcp-remote-direct--mcp_nodebb-notif-dropdown-fix-001_ucmNVg--d3ea9b6b9f.html) | `failed` | 0.000 | `False` | `test_ratio` | `answer_json_bridge` | 0.284 | 102 | traj, tx |
| [mcp_nodebb-plugin-validate-fix-001_jks41B](../tasks/csb_sdlc_fix_haiku_20260228_230722--mcp-remote-direct--mcp_nodebb-plugin-validate-fix-001_jks41B--e0bc43c300.html) | `failed` | 0.000 | `False` | `test_ratio` | `answer_json_bridge` | 0.187 | 75 | traj, tx |
| [mcp_pytorch-cudnn-version-fix-001_mKXDQ5](../tasks/csb_sdlc_fix_haiku_20260228_230722--mcp-remote-direct--mcp_pytorch-cudnn-version-fix-001_mKXDQ5--7b16c2e0e9.html) | `failed` | 0.000 | `False` | `diff_similarity` | `answer_json_bridge` | 0.542 | 48 | traj, tx |
| [mcp_pytorch-dynamo-keyerror-fix-001_XYVC0F](../tasks/csb_sdlc_fix_haiku_20260228_230722--mcp-remote-direct--mcp_pytorch-dynamo-keyerror-fix-001_XYVC0F--abc326d7f9.html) | `failed` | 0.000 | `False` | `diff_similarity` | `answer_json_bridge` | 0.481 | 106 | traj, tx |
| [mcp_ansible-abc-imports-fix-001_oNLzfI](../tasks/csb_sdlc_fix_haiku_20260228_230722--mcp-remote-direct--mcp_ansible-abc-imports-fix-001_oNLzfI--317c2cebbf.html) | `passed` | 1.000 | `True` | `test_ratio` | `answer_json_bridge` | 0.255 | 94 | traj, tx |
| [mcp_ansible-module-respawn-fix-001_MvUWba](../tasks/csb_sdlc_fix_haiku_20260228_230722--mcp-remote-direct--mcp_ansible-module-respawn-fix-001_MvUWba--e093a8ea48.html) | `passed` | 1.000 | `True` | `-` | `-` | 0.227 | 110 | traj, tx |
| [mcp_django-modelchoice-fk-fix-001_3ZPezv](../tasks/csb_sdlc_fix_haiku_20260228_230722--mcp-remote-direct--mcp_django-modelchoice-fk-fix-001_3ZPezv--5cac0cd98c.html) | `passed` | 0.450 | `True` | `repo_state_heuristic` | `answer_json_bridge` | 0.424 | 66 | traj, tx |
| [mcp_django-select-for-update-fix-001_SzPqm8](../tasks/csb_sdlc_fix_haiku_20260228_230722--mcp-remote-direct--mcp_django-select-for-update-fix-001_SzPqm8--eecc06c9af.html) | `passed` | 0.780 | `True` | `ir_checklist` | `answer_json_bridge` | 0.810 | 42 | traj, tx |
| [mcp_envoy-dfp-host-leak-fix-001_nyvsr4](../tasks/csb_sdlc_fix_haiku_20260228_230722--mcp-remote-direct--mcp_envoy-dfp-host-leak-fix-001_nyvsr4--863a11895c.html) | `passed` | 0.748 | `True` | `diff_similarity` | `answer_json_bridge` | 0.440 | 50 | traj, tx |
| [mcp_envoy-udp-proxy-cds-fix-001_MIczd5](../tasks/csb_sdlc_fix_haiku_20260228_230722--mcp-remote-direct--mcp_envoy-udp-proxy-cds-fix-001_MIczd5--7139a9d569.html) | `passed` | 0.389 | `True` | `diff_similarity` | `answer_json_bridge` | 0.712 | 52 | traj, tx |
| [mcp_flipt-cockroachdb-backend-fix-001_7anOLV](../tasks/csb_sdlc_fix_haiku_20260228_230722--mcp-remote-direct--mcp_flipt-cockroachdb-backend-fix-001_7anOLV--b02e9c39a3.html) | `passed` | 0.973 | `True` | `-` | `-` | 0.365 | 63 | traj, tx |
| [mcp_flipt-ecr-auth-oci-fix-001_kbzoBZ](../tasks/csb_sdlc_fix_haiku_20260228_230722--mcp-remote-direct--mcp_flipt-ecr-auth-oci-fix-001_kbzoBZ--faa4688763.html) | `passed` | 0.995 | `True` | `-` | `-` | 0.188 | 64 | traj, tx |
| [mcp_flipt-eval-latency-fix-001_zgd6kk](../tasks/csb_sdlc_fix_haiku_20260228_230722--mcp-remote-direct--mcp_flipt-eval-latency-fix-001_zgd6kk--75f518c375.html) | `passed` | 0.550 | `True` | `-` | `-` | 0.200 | 65 | traj, tx |
| [mcp_flipt-otlp-exporter-fix-001_VXFzO1](../tasks/csb_sdlc_fix_haiku_20260228_230722--mcp-remote-direct--mcp_flipt-otlp-exporter-fix-001_VXFzO1--9b44c477f1.html) | `passed` | 0.979 | `True` | `-` | `-` | 0.121 | 66 | traj, tx |
| [mcp_flipt-trace-sampling-fix-001_pDc1OG](../tasks/csb_sdlc_fix_haiku_20260228_230722--mcp-remote-direct--mcp_flipt-trace-sampling-fix-001_pDc1OG--facfb25b04.html) | `passed` | 0.985 | `True` | `-` | `-` | 0.351 | 77 | traj, tx |
| [mcp_k8s-dra-scheduler-event-fix-001_N4mJNM](../tasks/csb_sdlc_fix_haiku_20260228_230722--mcp-remote-direct--mcp_k8s-dra-scheduler-event-fix-001_N4mJNM--d28e9c82ec.html) | `passed` | 0.750 | `True` | `ir_checklist` | `answer_json_bridge` | 0.900 | 20 | traj, tx |
| [mcp_kafka-producer-bufpool-fix-001_0A2gfy](../tasks/csb_sdlc_fix_haiku_20260228_230722--mcp-remote-direct--mcp_kafka-producer-bufpool-fix-001_0A2gfy--5a2aaaeb88.html) | `passed` | 0.740 | `True` | `ir_checklist` | `answer_json_bridge` | 0.971 | 34 | traj, tx |
| [mcp_openlibrary-solr-boolean-fix-001_lj1SrT](../tasks/csb_sdlc_fix_haiku_20260228_230722--mcp-remote-direct--mcp_openlibrary-solr-boolean-fix-001_lj1SrT--584c4a8ebb.html) | `passed` | 0.667 | `True` | `-` | `-` | - | - | tx |
| [mcp_terraform-plan-null-unknown-fix-001_UwD4w4](../tasks/csb_sdlc_fix_haiku_20260228_230722--mcp-remote-direct--mcp_terraform-plan-null-unknown-fix-001_UwD4w4--94437c0a9c.html) | `passed` | 0.865 | `True` | `diff_similarity` | `answer_json_bridge` | 0.168 | 101 | traj, tx |
