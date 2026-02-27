# ccb_secure

| Run | Config | Valid Tasks | Mean Reward | Pass Rate |
|---|---|---:|---:|---:|
| [ccb_secure_haiku_022326](../runs/ccb_secure_haiku_022326.md) | `baseline` | 18 | 0.688 | 0.944 |
| [ccb_secure_haiku_022326](../runs/ccb_secure_haiku_022326.md) | `mcp` | 18 | 0.705 | 1.000 |
| [ccb_secure_haiku_20260224_213146](../runs/ccb_secure_haiku_20260224_213146.md) | `baseline-local-direct` | 2 | 0.500 | 1.000 |
| [ccb_secure_haiku_20260224_213146](../runs/ccb_secure_haiku_20260224_213146.md) | `mcp-remote-direct` | 2 | 0.250 | 0.500 |
| [secure_haiku_20260223_232545](../runs/secure_haiku_20260223_232545.md) | `baseline-local-direct` | 18 | 0.688 | 0.944 |
| [secure_haiku_20260223_232545](../runs/secure_haiku_20260223_232545.md) | `mcp-remote-direct` | 18 | 0.705 | 1.000 |
| [secure_haiku_20260224_011825](../runs/secure_haiku_20260224_011825.md) | `mcp-remote-direct` | 2 | 0.500 | 0.500 |

## Tasks

| Run | Config | Task | Status | Reward | MCP Ratio |
|---|---|---|---|---:|---:|
| `ccb_secure_haiku_022326` | `baseline` | [curl-cve-triage-001](../tasks/ccb_secure_haiku_022326--baseline--curl-cve-triage-001.md) | `passed` | 0.940 | 0.000 |
| `ccb_secure_haiku_022326` | `baseline` | [curl-vuln-reachability-001](../tasks/ccb_secure_haiku_022326--baseline--curl-vuln-reachability-001.md) | `passed` | 0.910 | 0.000 |
| `ccb_secure_haiku_022326` | `baseline` | [django-audit-trail-implement-001](../tasks/ccb_secure_haiku_022326--baseline--django-audit-trail-implement-001.md) | `passed` | 0.550 | 0.000 |
| `ccb_secure_haiku_022326` | `baseline` | [django-cross-team-boundary-001](../tasks/ccb_secure_haiku_022326--baseline--django-cross-team-boundary-001.md) | `passed` | 0.300 | 0.000 |
| `ccb_secure_haiku_022326` | `baseline` | [django-csrf-session-audit-001](../tasks/ccb_secure_haiku_022326--baseline--django-csrf-session-audit-001.md) | `passed` | 0.800 | 0.000 |
| `ccb_secure_haiku_022326` | `baseline` | [django-legacy-dep-vuln-001](../tasks/ccb_secure_haiku_022326--baseline--django-legacy-dep-vuln-001.md) | `passed` | 0.900 | 0.000 |
| `ccb_secure_haiku_022326` | `baseline` | [django-policy-enforcement-001](../tasks/ccb_secure_haiku_022326--baseline--django-policy-enforcement-001.md) | `passed` | 0.750 | 0.000 |
| `ccb_secure_haiku_022326` | `baseline` | [django-repo-scoped-access-001](../tasks/ccb_secure_haiku_022326--baseline--django-repo-scoped-access-001.md) | `passed` | 0.500 | 0.000 |
| `ccb_secure_haiku_022326` | `baseline` | [envoy-cve-triage-001](../tasks/ccb_secure_haiku_022326--baseline--envoy-cve-triage-001.md) | `passed` | 0.900 | 0.000 |
| `ccb_secure_haiku_022326` | `baseline` | [envoy-vuln-reachability-001](../tasks/ccb_secure_haiku_022326--baseline--envoy-vuln-reachability-001.md) | `passed` | 0.620 | 0.000 |
| `ccb_secure_haiku_022326` | `baseline` | [flipt-degraded-context-fix-001](../tasks/ccb_secure_haiku_022326--baseline--flipt-degraded-context-fix-001.md) | `passed` | 0.600 | 0.000 |
| `ccb_secure_haiku_022326` | `baseline` | [flipt-repo-scoped-access-001](../tasks/ccb_secure_haiku_022326--baseline--flipt-repo-scoped-access-001.md) | `passed` | 0.600 | 0.000 |
| `ccb_secure_haiku_022326` | `baseline` | [golang-net-cve-triage-001](../tasks/ccb_secure_haiku_022326--baseline--golang-net-cve-triage-001.md) | `passed` | 0.800 | 0.000 |
| `ccb_secure_haiku_022326` | `baseline` | [grpcurl-transitive-vuln-001](../tasks/ccb_secure_haiku_022326--baseline--grpcurl-transitive-vuln-001.md) | `failed` | 0.000 | 0.000 |
| `ccb_secure_haiku_022326` | `baseline` | [kafka-sasl-auth-audit-001](../tasks/ccb_secure_haiku_022326--baseline--kafka-sasl-auth-audit-001.md) | `passed` | 0.860 | 0.000 |
| `ccb_secure_haiku_022326` | `baseline` | [kafka-vuln-reachability-001](../tasks/ccb_secure_haiku_022326--baseline--kafka-vuln-reachability-001.md) | `passed` | 0.860 | 0.000 |
| `ccb_secure_haiku_022326` | `baseline` | [postgres-client-auth-audit-001](../tasks/ccb_secure_haiku_022326--baseline--postgres-client-auth-audit-001.md) | `passed` | 0.740 | 0.000 |
| `ccb_secure_haiku_022326` | `baseline` | [wish-transitive-vuln-001](../tasks/ccb_secure_haiku_022326--baseline--wish-transitive-vuln-001.md) | `passed` | 0.760 | 0.000 |
| `ccb_secure_haiku_022326` | `mcp` | [sgonly_curl-cve-triage-001](../tasks/ccb_secure_haiku_022326--mcp--sgonly_curl-cve-triage-001.md) | `passed` | 0.940 | 0.889 |
| `ccb_secure_haiku_022326` | `mcp` | [sgonly_curl-vuln-reachability-001](../tasks/ccb_secure_haiku_022326--mcp--sgonly_curl-vuln-reachability-001.md) | `passed` | 0.850 | 0.960 |
| `ccb_secure_haiku_022326` | `mcp` | [sgonly_django-audit-trail-implement-001](../tasks/ccb_secure_haiku_022326--mcp--sgonly_django-audit-trail-implement-001.md) | `passed` | 0.550 | 0.351 |
| `ccb_secure_haiku_022326` | `mcp` | [sgonly_django-cross-team-boundary-001](../tasks/ccb_secure_haiku_022326--mcp--sgonly_django-cross-team-boundary-001.md) | `passed` | 0.500 | 0.232 |
| `ccb_secure_haiku_022326` | `mcp` | [sgonly_django-csrf-session-audit-001](../tasks/ccb_secure_haiku_022326--mcp--sgonly_django-csrf-session-audit-001.md) | `passed` | 0.760 | 0.947 |
| `ccb_secure_haiku_022326` | `mcp` | [sgonly_django-legacy-dep-vuln-001](../tasks/ccb_secure_haiku_022326--mcp--sgonly_django-legacy-dep-vuln-001.md) | `passed` | 0.650 | 0.227 |
| `ccb_secure_haiku_022326` | `mcp` | [sgonly_django-policy-enforcement-001](../tasks/ccb_secure_haiku_022326--mcp--sgonly_django-policy-enforcement-001.md) | `passed` | 0.750 | 0.206 |
| `ccb_secure_haiku_022326` | `mcp` | [sgonly_django-repo-scoped-access-001](../tasks/ccb_secure_haiku_022326--mcp--sgonly_django-repo-scoped-access-001.md) | `passed` | 0.700 | 0.561 |
| `ccb_secure_haiku_022326` | `mcp` | [sgonly_envoy-cve-triage-001](../tasks/ccb_secure_haiku_022326--mcp--sgonly_envoy-cve-triage-001.md) | `passed` | 1.000 | 0.963 |
| `ccb_secure_haiku_022326` | `mcp` | [sgonly_envoy-vuln-reachability-001](../tasks/ccb_secure_haiku_022326--mcp--sgonly_envoy-vuln-reachability-001.md) | `passed` | 0.560 | 0.923 |
| `ccb_secure_haiku_022326` | `mcp` | [sgonly_flipt-degraded-context-fix-001](../tasks/ccb_secure_haiku_022326--mcp--sgonly_flipt-degraded-context-fix-001.md) | `passed` | 0.250 | 0.333 |
| `ccb_secure_haiku_022326` | `mcp` | [sgonly_flipt-repo-scoped-access-001](../tasks/ccb_secure_haiku_022326--mcp--sgonly_flipt-repo-scoped-access-001.md) | `passed` | 0.600 | 0.184 |
| `ccb_secure_haiku_022326` | `mcp` | [sgonly_golang-net-cve-triage-001](../tasks/ccb_secure_haiku_022326--mcp--sgonly_golang-net-cve-triage-001.md) | `passed` | 0.800 | 0.852 |
| `ccb_secure_haiku_022326` | `mcp` | [sgonly_grpcurl-transitive-vuln-001](../tasks/ccb_secure_haiku_022326--mcp--sgonly_grpcurl-transitive-vuln-001.md) | `passed` | 0.670 | 0.952 |
| `ccb_secure_haiku_022326` | `mcp` | [sgonly_kafka-sasl-auth-audit-001](../tasks/ccb_secure_haiku_022326--mcp--sgonly_kafka-sasl-auth-audit-001.md) | `passed` | 0.760 | 0.960 |
| `ccb_secure_haiku_022326` | `mcp` | [sgonly_kafka-vuln-reachability-001](../tasks/ccb_secure_haiku_022326--mcp--sgonly_kafka-vuln-reachability-001.md) | `passed` | 0.920 | 0.667 |
| `ccb_secure_haiku_022326` | `mcp` | [sgonly_postgres-client-auth-audit-001](../tasks/ccb_secure_haiku_022326--mcp--sgonly_postgres-client-auth-audit-001.md) | `passed` | 0.770 | 0.974 |
| `ccb_secure_haiku_022326` | `mcp` | [sgonly_wish-transitive-vuln-001](../tasks/ccb_secure_haiku_022326--mcp--sgonly_wish-transitive-vuln-001.md) | `passed` | 0.660 | 0.938 |
| `ccb_secure_haiku_20260224_213146` | `baseline-local-direct` | [django-role-based-access-001](../tasks/ccb_secure_haiku_20260224_213146--baseline-local-direct--django-role-based-access-001.md) | `passed` | 0.200 | 0.000 |
| `ccb_secure_haiku_20260224_213146` | `baseline-local-direct` | [django-sensitive-file-exclusion-001](../tasks/ccb_secure_haiku_20260224_213146--baseline-local-direct--django-sensitive-file-exclusion-001.md) | `passed` | 0.800 | 0.000 |
| `ccb_secure_haiku_20260224_213146` | `mcp-remote-direct` | [mcp_django-role-based-access-001_2ERzmK](../tasks/ccb_secure_haiku_20260224_213146--mcp-remote-direct--mcp_django-role-based-access-001_2ERzmK.md) | `failed` | 0.000 | 0.452 |
| `ccb_secure_haiku_20260224_213146` | `mcp-remote-direct` | [mcp_django-sensitive-file-exclusion-001_I216lD](../tasks/ccb_secure_haiku_20260224_213146--mcp-remote-direct--mcp_django-sensitive-file-exclusion-001_I216lD.md) | `passed` | 0.500 | 0.352 |
| `secure_haiku_20260223_232545` | `baseline-local-direct` | [curl-cve-triage-001](../tasks/secure_haiku_20260223_232545--baseline-local-direct--curl-cve-triage-001.md) | `passed` | 0.940 | 0.000 |
| `secure_haiku_20260223_232545` | `baseline-local-direct` | [curl-vuln-reachability-001](../tasks/secure_haiku_20260223_232545--baseline-local-direct--curl-vuln-reachability-001.md) | `passed` | 0.910 | 0.000 |
| `secure_haiku_20260223_232545` | `baseline-local-direct` | [django-audit-trail-implement-001](../tasks/secure_haiku_20260223_232545--baseline-local-direct--django-audit-trail-implement-001.md) | `passed` | 0.550 | 0.000 |
| `secure_haiku_20260223_232545` | `baseline-local-direct` | [django-cross-team-boundary-001](../tasks/secure_haiku_20260223_232545--baseline-local-direct--django-cross-team-boundary-001.md) | `passed` | 0.300 | 0.000 |
| `secure_haiku_20260223_232545` | `baseline-local-direct` | [django-csrf-session-audit-001](../tasks/secure_haiku_20260223_232545--baseline-local-direct--django-csrf-session-audit-001.md) | `passed` | 0.800 | 0.000 |
| `secure_haiku_20260223_232545` | `baseline-local-direct` | [django-legacy-dep-vuln-001](../tasks/secure_haiku_20260223_232545--baseline-local-direct--django-legacy-dep-vuln-001.md) | `passed` | 0.900 | 0.000 |
| `secure_haiku_20260223_232545` | `baseline-local-direct` | [django-policy-enforcement-001](../tasks/secure_haiku_20260223_232545--baseline-local-direct--django-policy-enforcement-001.md) | `passed` | 0.750 | 0.000 |
| `secure_haiku_20260223_232545` | `baseline-local-direct` | [django-repo-scoped-access-001](../tasks/secure_haiku_20260223_232545--baseline-local-direct--django-repo-scoped-access-001.md) | `passed` | 0.500 | 0.000 |
| `secure_haiku_20260223_232545` | `baseline-local-direct` | [envoy-cve-triage-001](../tasks/secure_haiku_20260223_232545--baseline-local-direct--envoy-cve-triage-001.md) | `passed` | 0.900 | 0.000 |
| `secure_haiku_20260223_232545` | `baseline-local-direct` | [envoy-vuln-reachability-001](../tasks/secure_haiku_20260223_232545--baseline-local-direct--envoy-vuln-reachability-001.md) | `passed` | 0.620 | 0.000 |
| `secure_haiku_20260223_232545` | `baseline-local-direct` | [flipt-degraded-context-fix-001](../tasks/secure_haiku_20260223_232545--baseline-local-direct--flipt-degraded-context-fix-001.md) | `passed` | 0.600 | 0.000 |
| `secure_haiku_20260223_232545` | `baseline-local-direct` | [flipt-repo-scoped-access-001](../tasks/secure_haiku_20260223_232545--baseline-local-direct--flipt-repo-scoped-access-001.md) | `passed` | 0.600 | 0.000 |
| `secure_haiku_20260223_232545` | `baseline-local-direct` | [golang-net-cve-triage-001](../tasks/secure_haiku_20260223_232545--baseline-local-direct--golang-net-cve-triage-001.md) | `passed` | 0.800 | 0.000 |
| `secure_haiku_20260223_232545` | `baseline-local-direct` | [grpcurl-transitive-vuln-001](../tasks/secure_haiku_20260223_232545--baseline-local-direct--grpcurl-transitive-vuln-001.md) | `failed` | 0.000 | 0.000 |
| `secure_haiku_20260223_232545` | `baseline-local-direct` | [kafka-sasl-auth-audit-001](../tasks/secure_haiku_20260223_232545--baseline-local-direct--kafka-sasl-auth-audit-001.md) | `passed` | 0.860 | 0.000 |
| `secure_haiku_20260223_232545` | `baseline-local-direct` | [kafka-vuln-reachability-001](../tasks/secure_haiku_20260223_232545--baseline-local-direct--kafka-vuln-reachability-001.md) | `passed` | 0.860 | 0.000 |
| `secure_haiku_20260223_232545` | `baseline-local-direct` | [postgres-client-auth-audit-001](../tasks/secure_haiku_20260223_232545--baseline-local-direct--postgres-client-auth-audit-001.md) | `passed` | 0.740 | 0.000 |
| `secure_haiku_20260223_232545` | `baseline-local-direct` | [wish-transitive-vuln-001](../tasks/secure_haiku_20260223_232545--baseline-local-direct--wish-transitive-vuln-001.md) | `passed` | 0.760 | 0.000 |
| `secure_haiku_20260223_232545` | `mcp-remote-direct` | [sgonly_curl-cve-triage-001](../tasks/secure_haiku_20260223_232545--mcp-remote-direct--sgonly_curl-cve-triage-001.md) | `passed` | 0.940 | 0.889 |
| `secure_haiku_20260223_232545` | `mcp-remote-direct` | [sgonly_curl-vuln-reachability-001](../tasks/secure_haiku_20260223_232545--mcp-remote-direct--sgonly_curl-vuln-reachability-001.md) | `passed` | 0.850 | 0.960 |
| `secure_haiku_20260223_232545` | `mcp-remote-direct` | [sgonly_django-audit-trail-implement-001](../tasks/secure_haiku_20260223_232545--mcp-remote-direct--sgonly_django-audit-trail-implement-001.md) | `passed` | 0.550 | 0.351 |
| `secure_haiku_20260223_232545` | `mcp-remote-direct` | [sgonly_django-cross-team-boundary-001](../tasks/secure_haiku_20260223_232545--mcp-remote-direct--sgonly_django-cross-team-boundary-001.md) | `passed` | 0.500 | 0.232 |
| `secure_haiku_20260223_232545` | `mcp-remote-direct` | [sgonly_django-csrf-session-audit-001](../tasks/secure_haiku_20260223_232545--mcp-remote-direct--sgonly_django-csrf-session-audit-001.md) | `passed` | 0.760 | 0.947 |
| `secure_haiku_20260223_232545` | `mcp-remote-direct` | [sgonly_django-legacy-dep-vuln-001](../tasks/secure_haiku_20260223_232545--mcp-remote-direct--sgonly_django-legacy-dep-vuln-001.md) | `passed` | 0.650 | 0.227 |
| `secure_haiku_20260223_232545` | `mcp-remote-direct` | [sgonly_django-policy-enforcement-001](../tasks/secure_haiku_20260223_232545--mcp-remote-direct--sgonly_django-policy-enforcement-001.md) | `passed` | 0.750 | 0.206 |
| `secure_haiku_20260223_232545` | `mcp-remote-direct` | [sgonly_django-repo-scoped-access-001](../tasks/secure_haiku_20260223_232545--mcp-remote-direct--sgonly_django-repo-scoped-access-001.md) | `passed` | 0.700 | 0.561 |
| `secure_haiku_20260223_232545` | `mcp-remote-direct` | [sgonly_envoy-cve-triage-001](../tasks/secure_haiku_20260223_232545--mcp-remote-direct--sgonly_envoy-cve-triage-001.md) | `passed` | 1.000 | 0.963 |
| `secure_haiku_20260223_232545` | `mcp-remote-direct` | [sgonly_envoy-vuln-reachability-001](../tasks/secure_haiku_20260223_232545--mcp-remote-direct--sgonly_envoy-vuln-reachability-001.md) | `passed` | 0.560 | 0.923 |
| `secure_haiku_20260223_232545` | `mcp-remote-direct` | [sgonly_flipt-degraded-context-fix-001](../tasks/secure_haiku_20260223_232545--mcp-remote-direct--sgonly_flipt-degraded-context-fix-001.md) | `passed` | 0.250 | 0.333 |
| `secure_haiku_20260223_232545` | `mcp-remote-direct` | [sgonly_flipt-repo-scoped-access-001](../tasks/secure_haiku_20260223_232545--mcp-remote-direct--sgonly_flipt-repo-scoped-access-001.md) | `passed` | 0.600 | 0.184 |
| `secure_haiku_20260223_232545` | `mcp-remote-direct` | [sgonly_golang-net-cve-triage-001](../tasks/secure_haiku_20260223_232545--mcp-remote-direct--sgonly_golang-net-cve-triage-001.md) | `passed` | 0.800 | 0.852 |
| `secure_haiku_20260223_232545` | `mcp-remote-direct` | [sgonly_grpcurl-transitive-vuln-001](../tasks/secure_haiku_20260223_232545--mcp-remote-direct--sgonly_grpcurl-transitive-vuln-001.md) | `passed` | 0.670 | 0.952 |
| `secure_haiku_20260223_232545` | `mcp-remote-direct` | [sgonly_kafka-sasl-auth-audit-001](../tasks/secure_haiku_20260223_232545--mcp-remote-direct--sgonly_kafka-sasl-auth-audit-001.md) | `passed` | 0.760 | 0.960 |
| `secure_haiku_20260223_232545` | `mcp-remote-direct` | [sgonly_kafka-vuln-reachability-001](../tasks/secure_haiku_20260223_232545--mcp-remote-direct--sgonly_kafka-vuln-reachability-001.md) | `passed` | 0.920 | 0.667 |
| `secure_haiku_20260223_232545` | `mcp-remote-direct` | [sgonly_postgres-client-auth-audit-001](../tasks/secure_haiku_20260223_232545--mcp-remote-direct--sgonly_postgres-client-auth-audit-001.md) | `passed` | 0.770 | 0.974 |
| `secure_haiku_20260223_232545` | `mcp-remote-direct` | [sgonly_wish-transitive-vuln-001](../tasks/secure_haiku_20260223_232545--mcp-remote-direct--sgonly_wish-transitive-vuln-001.md) | `passed` | 0.660 | 0.938 |
| `secure_haiku_20260224_011825` | `mcp-remote-direct` | [sgonly_django-role-based-access-001](../tasks/secure_haiku_20260224_011825--mcp-remote-direct--sgonly_django-role-based-access-001.md) | `failed` | 0.000 | - |
| `secure_haiku_20260224_011825` | `mcp-remote-direct` | [sgonly_django-sensitive-file-exclusion-001](../tasks/secure_haiku_20260224_011825--mcp-remote-direct--sgonly_django-sensitive-file-exclusion-001.md) | `passed` | 1.000 | 0.368 |
