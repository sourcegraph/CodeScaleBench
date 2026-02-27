# ccb_fix

| Run | Config | Valid Tasks | Mean Reward | Pass Rate |
|---|---|---:|---:|---:|
| [ccb_fix_haiku_022326](../runs/ccb_fix_haiku_022326.md) | `baseline` | 17 | 0.535 | 0.706 |
| [ccb_fix_haiku_022326](../runs/ccb_fix_haiku_022326.md) | `mcp` | 17 | 0.538 | 0.647 |
| [ccb_fix_haiku_20260224_203138](../runs/ccb_fix_haiku_20260224_203138.md) | `baseline-local-direct` | 1 | 0.710 | 1.000 |
| [ccb_fix_haiku_20260224_203138](../runs/ccb_fix_haiku_20260224_203138.md) | `mcp-remote-direct` | 1 | 0.740 | 1.000 |
| [fix_haiku_20260223_171232](../runs/fix_haiku_20260223_171232.md) | `baseline-local-direct` | 19 | 0.479 | 0.632 |
| [fix_haiku_20260223_171232](../runs/fix_haiku_20260223_171232.md) | `mcp-remote-direct` | 18 | 0.508 | 0.611 |
| [fix_haiku_20260224_011821](../runs/fix_haiku_20260224_011821.md) | `baseline-local-direct` | 2 | 0.000 | 0.000 |
| [fix_haiku_20260224_011821](../runs/fix_haiku_20260224_011821.md) | `mcp-remote-direct` | 3 | 0.260 | 0.333 |
| [fix_haiku_20260226_024454](../runs/fix_haiku_20260226_024454.md) | `baseline-local-direct` | 3 | 0.000 | 0.000 |
| [fix_haiku_20260226_024454](../runs/fix_haiku_20260226_024454.md) | `mcp-remote-direct` | 3 | 0.000 | 0.000 |
| [fix_haiku_20260226_new3tasks](../runs/fix_haiku_20260226_new3tasks.md) | `baseline-local-direct` | 3 | 0.727 | 1.000 |
| [fix_haiku_20260226_new3tasks](../runs/fix_haiku_20260226_new3tasks.md) | `mcp-remote-direct` | 3 | 0.801 | 1.000 |

## Tasks

| Run | Config | Task | Status | Reward | MCP Ratio |
|---|---|---|---|---:|---:|
| `ccb_fix_haiku_022326` | `baseline` | [ansible-abc-imports-fix-001](../tasks/ccb_fix_haiku_022326--baseline--ansible-abc-imports-fix-001.md) | `passed` | 0.943 | 0.000 |
| `ccb_fix_haiku_022326` | `baseline` | [ansible-module-respawn-fix-001](../tasks/ccb_fix_haiku_022326--baseline--ansible-module-respawn-fix-001.md) | `passed` | 0.471 | 0.000 |
| `ccb_fix_haiku_022326` | `baseline` | [django-modelchoice-fk-fix-001](../tasks/ccb_fix_haiku_022326--baseline--django-modelchoice-fk-fix-001.md) | `passed` | 0.450 | 0.000 |
| `ccb_fix_haiku_022326` | `baseline` | [django-select-for-update-fix-001](../tasks/ccb_fix_haiku_022326--baseline--django-select-for-update-fix-001.md) | `passed` | 0.670 | 0.000 |
| `ccb_fix_haiku_022326` | `baseline` | [flipt-cockroachdb-backend-fix-001](../tasks/ccb_fix_haiku_022326--baseline--flipt-cockroachdb-backend-fix-001.md) | `passed` | 0.973 | 0.000 |
| `ccb_fix_haiku_022326` | `baseline` | [flipt-ecr-auth-oci-fix-001](../tasks/ccb_fix_haiku_022326--baseline--flipt-ecr-auth-oci-fix-001.md) | `passed` | 0.987 | 0.000 |
| `ccb_fix_haiku_022326` | `baseline` | [flipt-eval-latency-fix-001](../tasks/ccb_fix_haiku_022326--baseline--flipt-eval-latency-fix-001.md) | `passed` | 0.550 | 0.000 |
| `ccb_fix_haiku_022326` | `baseline` | [flipt-otlp-exporter-fix-001](../tasks/ccb_fix_haiku_022326--baseline--flipt-otlp-exporter-fix-001.md) | `passed` | 0.978 | 0.000 |
| `ccb_fix_haiku_022326` | `baseline` | [flipt-trace-sampling-fix-001](../tasks/ccb_fix_haiku_022326--baseline--flipt-trace-sampling-fix-001.md) | `passed` | 0.987 | 0.000 |
| `ccb_fix_haiku_022326` | `baseline` | [k8s-dra-scheduler-event-fix-001](../tasks/ccb_fix_haiku_022326--baseline--k8s-dra-scheduler-event-fix-001.md) | `passed` | 0.680 | 0.000 |
| `ccb_fix_haiku_022326` | `baseline` | [nodebb-notif-dropdown-fix-001](../tasks/ccb_fix_haiku_022326--baseline--nodebb-notif-dropdown-fix-001.md) | `failed` | 0.000 | 0.000 |
| `ccb_fix_haiku_022326` | `baseline` | [openlibrary-fntocli-adapter-fix-001](../tasks/ccb_fix_haiku_022326--baseline--openlibrary-fntocli-adapter-fix-001.md) | `passed` | 0.667 | 0.000 |
| `ccb_fix_haiku_022326` | `baseline` | [pytorch-cudnn-version-fix-001](../tasks/ccb_fix_haiku_022326--baseline--pytorch-cudnn-version-fix-001.md) | `failed` | 0.000 | 0.000 |
| `ccb_fix_haiku_022326` | `baseline` | [pytorch-dynamo-keyerror-fix-001](../tasks/ccb_fix_haiku_022326--baseline--pytorch-dynamo-keyerror-fix-001.md) | `failed` | 0.000 | 0.000 |
| `ccb_fix_haiku_022326` | `baseline` | [pytorch-release-210-fix-001](../tasks/ccb_fix_haiku_022326--baseline--pytorch-release-210-fix-001.md) | `failed` | 0.000 | 0.000 |
| `ccb_fix_haiku_022326` | `baseline` | [pytorch-relu-gelu-fusion-fix-001](../tasks/ccb_fix_haiku_022326--baseline--pytorch-relu-gelu-fusion-fix-001.md) | `passed` | 0.739 | 0.000 |
| `ccb_fix_haiku_022326` | `baseline` | [pytorch-tracer-graph-cleanup-fix-001](../tasks/ccb_fix_haiku_022326--baseline--pytorch-tracer-graph-cleanup-fix-001.md) | `failed` | 0.000 | 0.000 |
| `ccb_fix_haiku_022326` | `mcp` | [sgonly_ansible-abc-imports-fix-001](../tasks/ccb_fix_haiku_022326--mcp--sgonly_ansible-abc-imports-fix-001.md) | `passed` | 1.000 | 0.299 |
| `ccb_fix_haiku_022326` | `mcp` | [sgonly_django-modelchoice-fk-fix-001](../tasks/ccb_fix_haiku_022326--mcp--sgonly_django-modelchoice-fk-fix-001.md) | `passed` | 0.450 | 0.655 |
| `ccb_fix_haiku_022326` | `mcp` | [sgonly_django-select-for-update-fix-001](../tasks/ccb_fix_haiku_022326--mcp--sgonly_django-select-for-update-fix-001.md) | `passed` | 0.780 | 0.711 |
| `ccb_fix_haiku_022326` | `mcp` | [sgonly_flipt-cockroachdb-backend-fix-001](../tasks/ccb_fix_haiku_022326--mcp--sgonly_flipt-cockroachdb-backend-fix-001.md) | `passed` | 0.973 | 0.508 |
| `ccb_fix_haiku_022326` | `mcp` | [sgonly_flipt-ecr-auth-oci-fix-001](../tasks/ccb_fix_haiku_022326--mcp--sgonly_flipt-ecr-auth-oci-fix-001.md) | `passed` | 0.995 | 0.139 |
| `ccb_fix_haiku_022326` | `mcp` | [sgonly_flipt-eval-latency-fix-001](../tasks/ccb_fix_haiku_022326--mcp--sgonly_flipt-eval-latency-fix-001.md) | `failed` | 0.000 | 0.200 |
| `ccb_fix_haiku_022326` | `mcp` | [sgonly_flipt-otlp-exporter-fix-001](../tasks/ccb_fix_haiku_022326--mcp--sgonly_flipt-otlp-exporter-fix-001.md) | `passed` | 0.979 | 0.221 |
| `ccb_fix_haiku_022326` | `mcp` | [sgonly_flipt-trace-sampling-fix-001](../tasks/ccb_fix_haiku_022326--mcp--sgonly_flipt-trace-sampling-fix-001.md) | `passed` | 0.985 | 0.119 |
| `ccb_fix_haiku_022326` | `mcp` | [sgonly_k8s-dra-scheduler-event-fix-001](../tasks/ccb_fix_haiku_022326--mcp--sgonly_k8s-dra-scheduler-event-fix-001.md) | `passed` | 0.750 | 0.810 |
| `ccb_fix_haiku_022326` | `mcp` | [sgonly_nodebb-notif-dropdown-fix-001](../tasks/ccb_fix_haiku_022326--mcp--sgonly_nodebb-notif-dropdown-fix-001.md) | `failed` | 0.000 | 0.446 |
| `ccb_fix_haiku_022326` | `mcp` | [sgonly_openlibrary-fntocli-adapter-fix-001](../tasks/ccb_fix_haiku_022326--mcp--sgonly_openlibrary-fntocli-adapter-fix-001.md) | `passed` | 1.000 | 0.108 |
| `ccb_fix_haiku_022326` | `mcp` | [sgonly_openlibrary-solr-boolean-fix-001](../tasks/ccb_fix_haiku_022326--mcp--sgonly_openlibrary-solr-boolean-fix-001.md) | `passed` | 0.667 | - |
| `ccb_fix_haiku_022326` | `mcp` | [sgonly_pytorch-cudnn-version-fix-001](../tasks/ccb_fix_haiku_022326--mcp--sgonly_pytorch-cudnn-version-fix-001.md) | `failed` | 0.000 | 0.586 |
| `ccb_fix_haiku_022326` | `mcp` | [sgonly_pytorch-dynamo-keyerror-fix-001](../tasks/ccb_fix_haiku_022326--mcp--sgonly_pytorch-dynamo-keyerror-fix-001.md) | `failed` | 0.000 | 0.625 |
| `ccb_fix_haiku_022326` | `mcp` | [sgonly_pytorch-release-210-fix-001](../tasks/ccb_fix_haiku_022326--mcp--sgonly_pytorch-release-210-fix-001.md) | `failed` | 0.000 | 0.241 |
| `ccb_fix_haiku_022326` | `mcp` | [sgonly_pytorch-relu-gelu-fusion-fix-001](../tasks/ccb_fix_haiku_022326--mcp--sgonly_pytorch-relu-gelu-fusion-fix-001.md) | `passed` | 0.561 | 0.370 |
| `ccb_fix_haiku_022326` | `mcp` | [sgonly_pytorch-tracer-graph-cleanup-fix-001](../tasks/ccb_fix_haiku_022326--mcp--sgonly_pytorch-tracer-graph-cleanup-fix-001.md) | `failed` | 0.000 | 0.217 |
| `ccb_fix_haiku_20260224_203138` | `baseline-local-direct` | [kafka-producer-bufpool-fix-001](../tasks/ccb_fix_haiku_20260224_203138--baseline-local-direct--kafka-producer-bufpool-fix-001.md) | `passed` | 0.710 | 0.000 |
| `ccb_fix_haiku_20260224_203138` | `mcp-remote-direct` | [mcp_kafka-producer-bufpool-fix-001_2pvDVv](../tasks/ccb_fix_haiku_20260224_203138--mcp-remote-direct--mcp_kafka-producer-bufpool-fix-001_2pvDVv.md) | `passed` | 0.740 | 0.955 |
| `fix_haiku_20260223_171232` | `baseline-local-direct` | [ansible-abc-imports-fix-001](../tasks/fix_haiku_20260223_171232--baseline-local-direct--ansible-abc-imports-fix-001.md) | `passed` | 0.943 | 0.000 |
| `fix_haiku_20260223_171232` | `baseline-local-direct` | [ansible-module-respawn-fix-001](../tasks/fix_haiku_20260223_171232--baseline-local-direct--ansible-module-respawn-fix-001.md) | `passed` | 0.471 | 0.000 |
| `fix_haiku_20260223_171232` | `baseline-local-direct` | [django-modelchoice-fk-fix-001](../tasks/fix_haiku_20260223_171232--baseline-local-direct--django-modelchoice-fk-fix-001.md) | `passed` | 0.450 | 0.000 |
| `fix_haiku_20260223_171232` | `baseline-local-direct` | [django-select-for-update-fix-001](../tasks/fix_haiku_20260223_171232--baseline-local-direct--django-select-for-update-fix-001.md) | `passed` | 0.670 | 0.000 |
| `fix_haiku_20260223_171232` | `baseline-local-direct` | [flipt-cockroachdb-backend-fix-001](../tasks/fix_haiku_20260223_171232--baseline-local-direct--flipt-cockroachdb-backend-fix-001.md) | `passed` | 0.973 | 0.000 |
| `fix_haiku_20260223_171232` | `baseline-local-direct` | [flipt-ecr-auth-oci-fix-001](../tasks/fix_haiku_20260223_171232--baseline-local-direct--flipt-ecr-auth-oci-fix-001.md) | `passed` | 0.987 | 0.000 |
| `fix_haiku_20260223_171232` | `baseline-local-direct` | [flipt-eval-latency-fix-001](../tasks/fix_haiku_20260223_171232--baseline-local-direct--flipt-eval-latency-fix-001.md) | `passed` | 0.550 | 0.000 |
| `fix_haiku_20260223_171232` | `baseline-local-direct` | [flipt-otlp-exporter-fix-001](../tasks/fix_haiku_20260223_171232--baseline-local-direct--flipt-otlp-exporter-fix-001.md) | `passed` | 0.978 | 0.000 |
| `fix_haiku_20260223_171232` | `baseline-local-direct` | [flipt-trace-sampling-fix-001](../tasks/fix_haiku_20260223_171232--baseline-local-direct--flipt-trace-sampling-fix-001.md) | `passed` | 0.987 | 0.000 |
| `fix_haiku_20260223_171232` | `baseline-local-direct` | [k8s-dra-scheduler-event-fix-001](../tasks/fix_haiku_20260223_171232--baseline-local-direct--k8s-dra-scheduler-event-fix-001.md) | `passed` | 0.680 | 0.000 |
| `fix_haiku_20260223_171232` | `baseline-local-direct` | [nodebb-notif-dropdown-fix-001](../tasks/fix_haiku_20260223_171232--baseline-local-direct--nodebb-notif-dropdown-fix-001.md) | `failed` | 0.000 | 0.000 |
| `fix_haiku_20260223_171232` | `baseline-local-direct` | [openlibrary-fntocli-adapter-fix-001](../tasks/fix_haiku_20260223_171232--baseline-local-direct--openlibrary-fntocli-adapter-fix-001.md) | `passed` | 0.667 | 0.000 |
| `fix_haiku_20260223_171232` | `baseline-local-direct` | [openlibrary-solr-boolean-fix-001](../tasks/fix_haiku_20260223_171232--baseline-local-direct--openlibrary-solr-boolean-fix-001.md) | `failed` | 0.000 | - |
| `fix_haiku_20260223_171232` | `baseline-local-direct` | [protonmail-conv-testhooks-fix-001](../tasks/fix_haiku_20260223_171232--baseline-local-direct--protonmail-conv-testhooks-fix-001.md) | `failed` | 0.000 | - |
| `fix_haiku_20260223_171232` | `baseline-local-direct` | [pytorch-cudnn-version-fix-001](../tasks/fix_haiku_20260223_171232--baseline-local-direct--pytorch-cudnn-version-fix-001.md) | `failed` | 0.000 | 0.000 |
| `fix_haiku_20260223_171232` | `baseline-local-direct` | [pytorch-dynamo-keyerror-fix-001](../tasks/fix_haiku_20260223_171232--baseline-local-direct--pytorch-dynamo-keyerror-fix-001.md) | `failed` | 0.000 | 0.000 |
| `fix_haiku_20260223_171232` | `baseline-local-direct` | [pytorch-release-210-fix-001](../tasks/fix_haiku_20260223_171232--baseline-local-direct--pytorch-release-210-fix-001.md) | `failed` | 0.000 | 0.000 |
| `fix_haiku_20260223_171232` | `baseline-local-direct` | [pytorch-relu-gelu-fusion-fix-001](../tasks/fix_haiku_20260223_171232--baseline-local-direct--pytorch-relu-gelu-fusion-fix-001.md) | `passed` | 0.739 | 0.000 |
| `fix_haiku_20260223_171232` | `baseline-local-direct` | [pytorch-tracer-graph-cleanup-fix-001](../tasks/fix_haiku_20260223_171232--baseline-local-direct--pytorch-tracer-graph-cleanup-fix-001.md) | `failed` | 0.000 | 0.000 |
| `fix_haiku_20260223_171232` | `mcp-remote-direct` | [sgonly_ansible-abc-imports-fix-001](../tasks/fix_haiku_20260223_171232--mcp-remote-direct--sgonly_ansible-abc-imports-fix-001.md) | `passed` | 1.000 | 0.299 |
| `fix_haiku_20260223_171232` | `mcp-remote-direct` | [sgonly_ansible-module-respawn-fix-001](../tasks/fix_haiku_20260223_171232--mcp-remote-direct--sgonly_ansible-module-respawn-fix-001.md) | `failed` | 0.000 | 0.291 |
| `fix_haiku_20260223_171232` | `mcp-remote-direct` | [sgonly_django-modelchoice-fk-fix-001](../tasks/fix_haiku_20260223_171232--mcp-remote-direct--sgonly_django-modelchoice-fk-fix-001.md) | `passed` | 0.450 | 0.655 |
| `fix_haiku_20260223_171232` | `mcp-remote-direct` | [sgonly_django-select-for-update-fix-001](../tasks/fix_haiku_20260223_171232--mcp-remote-direct--sgonly_django-select-for-update-fix-001.md) | `passed` | 0.780 | 0.711 |
| `fix_haiku_20260223_171232` | `mcp-remote-direct` | [sgonly_flipt-cockroachdb-backend-fix-001](../tasks/fix_haiku_20260223_171232--mcp-remote-direct--sgonly_flipt-cockroachdb-backend-fix-001.md) | `passed` | 0.973 | 0.508 |
| `fix_haiku_20260223_171232` | `mcp-remote-direct` | [sgonly_flipt-ecr-auth-oci-fix-001](../tasks/fix_haiku_20260223_171232--mcp-remote-direct--sgonly_flipt-ecr-auth-oci-fix-001.md) | `passed` | 0.995 | 0.139 |
| `fix_haiku_20260223_171232` | `mcp-remote-direct` | [sgonly_flipt-eval-latency-fix-001](../tasks/fix_haiku_20260223_171232--mcp-remote-direct--sgonly_flipt-eval-latency-fix-001.md) | `failed` | 0.000 | 0.200 |
| `fix_haiku_20260223_171232` | `mcp-remote-direct` | [sgonly_flipt-otlp-exporter-fix-001](../tasks/fix_haiku_20260223_171232--mcp-remote-direct--sgonly_flipt-otlp-exporter-fix-001.md) | `passed` | 0.979 | 0.221 |
| `fix_haiku_20260223_171232` | `mcp-remote-direct` | [sgonly_flipt-trace-sampling-fix-001](../tasks/fix_haiku_20260223_171232--mcp-remote-direct--sgonly_flipt-trace-sampling-fix-001.md) | `passed` | 0.985 | 0.119 |
| `fix_haiku_20260223_171232` | `mcp-remote-direct` | [sgonly_k8s-dra-scheduler-event-fix-001](../tasks/fix_haiku_20260223_171232--mcp-remote-direct--sgonly_k8s-dra-scheduler-event-fix-001.md) | `passed` | 0.750 | 0.810 |
| `fix_haiku_20260223_171232` | `mcp-remote-direct` | [sgonly_nodebb-notif-dropdown-fix-001](../tasks/fix_haiku_20260223_171232--mcp-remote-direct--sgonly_nodebb-notif-dropdown-fix-001.md) | `failed` | 0.000 | 0.446 |
| `fix_haiku_20260223_171232` | `mcp-remote-direct` | [sgonly_openlibrary-fntocli-adapter-fix-001](../tasks/fix_haiku_20260223_171232--mcp-remote-direct--sgonly_openlibrary-fntocli-adapter-fix-001.md) | `passed` | 1.000 | 0.108 |
| `fix_haiku_20260223_171232` | `mcp-remote-direct` | [sgonly_openlibrary-solr-boolean-fix-001](../tasks/fix_haiku_20260223_171232--mcp-remote-direct--sgonly_openlibrary-solr-boolean-fix-001.md) | `passed` | 0.667 | - |
| `fix_haiku_20260223_171232` | `mcp-remote-direct` | [sgonly_pytorch-cudnn-version-fix-001](../tasks/fix_haiku_20260223_171232--mcp-remote-direct--sgonly_pytorch-cudnn-version-fix-001.md) | `failed` | 0.000 | 0.586 |
| `fix_haiku_20260223_171232` | `mcp-remote-direct` | [sgonly_pytorch-dynamo-keyerror-fix-001](../tasks/fix_haiku_20260223_171232--mcp-remote-direct--sgonly_pytorch-dynamo-keyerror-fix-001.md) | `failed` | 0.000 | 0.625 |
| `fix_haiku_20260223_171232` | `mcp-remote-direct` | [sgonly_pytorch-release-210-fix-001](../tasks/fix_haiku_20260223_171232--mcp-remote-direct--sgonly_pytorch-release-210-fix-001.md) | `failed` | 0.000 | 0.241 |
| `fix_haiku_20260223_171232` | `mcp-remote-direct` | [sgonly_pytorch-relu-gelu-fusion-fix-001](../tasks/fix_haiku_20260223_171232--mcp-remote-direct--sgonly_pytorch-relu-gelu-fusion-fix-001.md) | `passed` | 0.561 | 0.370 |
| `fix_haiku_20260223_171232` | `mcp-remote-direct` | [sgonly_pytorch-tracer-graph-cleanup-fix-001](../tasks/fix_haiku_20260223_171232--mcp-remote-direct--sgonly_pytorch-tracer-graph-cleanup-fix-001.md) | `failed` | 0.000 | 0.217 |
| `fix_haiku_20260224_011821` | `baseline-local-direct` | [protonmail-dropdown-sizing-fix-001](../tasks/fix_haiku_20260224_011821--baseline-local-direct--protonmail-dropdown-sizing-fix-001.md) | `failed` | 0.000 | - |
| `fix_haiku_20260224_011821` | `baseline-local-direct` | [protonmail-holiday-calendar-fix-001](../tasks/fix_haiku_20260224_011821--baseline-local-direct--protonmail-holiday-calendar-fix-001.md) | `failed` | 0.000 | - |
| `fix_haiku_20260224_011821` | `mcp-remote-direct` | [sgonly_kafka-producer-bufpool-fix-001](../tasks/fix_haiku_20260224_011821--mcp-remote-direct--sgonly_kafka-producer-bufpool-fix-001.md) | `passed` | 0.780 | 0.900 |
| `fix_haiku_20260224_011821` | `mcp-remote-direct` | [sgonly_protonmail-dropdown-sizing-fix-001](../tasks/fix_haiku_20260224_011821--mcp-remote-direct--sgonly_protonmail-dropdown-sizing-fix-001.md) | `failed` | 0.000 | - |
| `fix_haiku_20260224_011821` | `mcp-remote-direct` | [sgonly_protonmail-holiday-calendar-fix-001](../tasks/fix_haiku_20260224_011821--mcp-remote-direct--sgonly_protonmail-holiday-calendar-fix-001.md) | `failed` | 0.000 | - |
| `fix_haiku_20260226_024454` | `baseline-local-direct` | [navidrome-windows-log-fix-001](../tasks/fix_haiku_20260226_024454--baseline-local-direct--navidrome-windows-log-fix-001.md) | `failed` | 0.000 | 0.000 |
| `fix_haiku_20260226_024454` | `baseline-local-direct` | [nodebb-plugin-validate-fix-001](../tasks/fix_haiku_20260226_024454--baseline-local-direct--nodebb-plugin-validate-fix-001.md) | `failed` | 0.000 | 0.000 |
| `fix_haiku_20260226_024454` | `baseline-local-direct` | [openlibrary-search-query-fix-001](../tasks/fix_haiku_20260226_024454--baseline-local-direct--openlibrary-search-query-fix-001.md) | `failed` | 0.000 | 0.000 |
| `fix_haiku_20260226_024454` | `mcp-remote-direct` | [sgonly_navidrome-windows-log-fix-001](../tasks/fix_haiku_20260226_024454--mcp-remote-direct--sgonly_navidrome-windows-log-fix-001.md) | `failed` | 0.000 | 0.286 |
| `fix_haiku_20260226_024454` | `mcp-remote-direct` | [sgonly_nodebb-plugin-validate-fix-001](../tasks/fix_haiku_20260226_024454--mcp-remote-direct--sgonly_nodebb-plugin-validate-fix-001.md) | `failed` | 0.000 | 0.125 |
| `fix_haiku_20260226_024454` | `mcp-remote-direct` | [sgonly_openlibrary-search-query-fix-001](../tasks/fix_haiku_20260226_024454--mcp-remote-direct--sgonly_openlibrary-search-query-fix-001.md) | `failed` | 0.000 | 0.175 |
| `fix_haiku_20260226_new3tasks` | `baseline-local-direct` | [envoy-dfp-host-leak-fix-001](../tasks/fix_haiku_20260226_new3tasks--baseline-local-direct--envoy-dfp-host-leak-fix-001.md) | `passed` | 0.727 | 0.000 |
| `fix_haiku_20260226_new3tasks` | `baseline-local-direct` | [envoy-udp-proxy-cds-fix-001](../tasks/fix_haiku_20260226_new3tasks--baseline-local-direct--envoy-udp-proxy-cds-fix-001.md) | `passed` | 0.755 | 0.000 |
| `fix_haiku_20260226_new3tasks` | `baseline-local-direct` | [terraform-plan-null-unknown-fix-001](../tasks/fix_haiku_20260226_new3tasks--baseline-local-direct--terraform-plan-null-unknown-fix-001.md) | `passed` | 0.699 | 0.000 |
| `fix_haiku_20260226_new3tasks` | `mcp-remote-direct` | [sgonly_envoy-dfp-host-leak-fix-001](../tasks/fix_haiku_20260226_new3tasks--mcp-remote-direct--sgonly_envoy-dfp-host-leak-fix-001.md) | `passed` | 0.665 | 0.345 |
| `fix_haiku_20260226_new3tasks` | `mcp-remote-direct` | [sgonly_envoy-udp-proxy-cds-fix-001](../tasks/fix_haiku_20260226_new3tasks--mcp-remote-direct--sgonly_envoy-udp-proxy-cds-fix-001.md) | `passed` | 0.784 | 0.485 |
| `fix_haiku_20260226_new3tasks` | `mcp-remote-direct` | [sgonly_terraform-plan-null-unknown-fix-001](../tasks/fix_haiku_20260226_new3tasks--mcp-remote-direct--sgonly_terraform-plan-null-unknown-fix-001.md) | `passed` | 0.955 | 0.193 |
