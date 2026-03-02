# ccb_secure

## Run/Config Summary

| Run | Config | Valid Tasks | Mean Reward | Pass Rate |
|---|---|---:|---:|---:|
| [ccb_secure_haiku_20260224_213146](../runs/ccb_secure_haiku_20260224_213146.md) | `mcp-remote-direct` | 2 | 0.250 | 0.500 |
| [ccb_secure_haiku_20260228_124521](../runs/ccb_secure_haiku_20260228_124521.md) | `mcp-remote-direct` | 2 | 0.555 | 1.000 |
| [secure_haiku_20260301_071231](../runs/secure_haiku_20260301_071231.md) | `baseline-local-direct` | 20 | 0.712 | 1.000 |
| [secure_haiku_20260301_071231](../runs/secure_haiku_20260301_071231.md) | `mcp-remote-direct` | 20 | 0.767 | 1.000 |

## Tasks

| Task | Benchmark | Config | Status | Reward | Runs | MCP Ratio |
|---|---|---|---|---:|---:|---:|
| [curl-cve-triage-001](../tasks/secure_haiku_20260301_071231--baseline-local-direct--curl-cve-triage-001.html) | [source](../../../benchmarks/ccb_secure/curl-cve-triage-001) | `baseline-local-direct` | `passed` | 0.940 | 4 | 0.000 |
| [sgonly_curl-cve-triage-001](../tasks/secure_haiku_20260301_071231--mcp-remote-direct--sgonly_curl-cve-triage-001.html) | [source](../../../benchmarks/ccb_secure/curl-cve-triage-001) | `mcp-remote-direct` | `passed` | 0.940 | 4 | 0.750 |
| [curl-vuln-reachability-001](../tasks/secure_haiku_20260301_071231--baseline-local-direct--curl-vuln-reachability-001.html) | [source](../../../benchmarks/ccb_secure/curl-vuln-reachability-001) | `baseline-local-direct` | `passed` | 0.850 | 4 | 0.000 |
| [sgonly_curl-vuln-reachability-001](../tasks/secure_haiku_20260301_071231--mcp-remote-direct--sgonly_curl-vuln-reachability-001.html) | [source](../../../benchmarks/ccb_secure/curl-vuln-reachability-001) | `mcp-remote-direct` | `passed` | 0.760 | 4 | 0.962 |
| [django-audit-trail-implement-001](../tasks/secure_haiku_20260301_071231--baseline-local-direct--django-audit-trail-implement-001.html) | [source](../../../benchmarks/ccb_secure/django-audit-trail-implement-001) | `baseline-local-direct` | `passed` | 0.550 | 4 | 0.000 |
| [sgonly_django-audit-trail-implement-001](../tasks/secure_haiku_20260301_071231--mcp-remote-direct--sgonly_django-audit-trail-implement-001.html) | [source](../../../benchmarks/ccb_secure/django-audit-trail-implement-001) | `mcp-remote-direct` | `passed` | 0.550 | 4 | 0.358 |
| [django-cross-team-boundary-001](../tasks/secure_haiku_20260301_071231--baseline-local-direct--django-cross-team-boundary-001.html) | [source](../../../benchmarks/ccb_secure/django-cross-team-boundary-001) | `baseline-local-direct` | `passed` | 0.300 | 4 | 0.000 |
| [sgonly_django-cross-team-boundary-001](../tasks/secure_haiku_20260301_071231--mcp-remote-direct--sgonly_django-cross-team-boundary-001.html) | [source](../../../benchmarks/ccb_secure/django-cross-team-boundary-001) | `mcp-remote-direct` | `passed` | 0.300 | 4 | 0.361 |
| [django-csrf-session-audit-001](../tasks/secure_haiku_20260301_071231--baseline-local-direct--django-csrf-session-audit-001.html) | — | `baseline-local-direct` | `passed` | 0.800 | 4 | 0.000 |
| [sgonly_django-csrf-session-audit-001](../tasks/secure_haiku_20260301_071231--mcp-remote-direct--sgonly_django-csrf-session-audit-001.html) | — | `mcp-remote-direct` | `passed` | 0.810 | 4 | 0.957 |
| [django-legacy-dep-vuln-001](../tasks/secure_haiku_20260301_071231--baseline-local-direct--django-legacy-dep-vuln-001.html) | [source](../../../benchmarks/ccb_secure/django-legacy-dep-vuln-001) | `baseline-local-direct` | `passed` | 1.000 | 4 | 0.000 |
| [sgonly_django-legacy-dep-vuln-001](../tasks/secure_haiku_20260301_071231--mcp-remote-direct--sgonly_django-legacy-dep-vuln-001.html) | [source](../../../benchmarks/ccb_secure/django-legacy-dep-vuln-001) | `mcp-remote-direct` | `passed` | 1.000 | 4 | 0.279 |
| [django-policy-enforcement-001](../tasks/secure_haiku_20260301_071231--baseline-local-direct--django-policy-enforcement-001.html) | — | `baseline-local-direct` | `passed` | 0.850 | 4 | 0.000 |
| [sgonly_django-policy-enforcement-001](../tasks/secure_haiku_20260301_071231--mcp-remote-direct--sgonly_django-policy-enforcement-001.html) | — | `mcp-remote-direct` | `passed` | 0.900 | 4 | 0.169 |
| [django-repo-scoped-access-001](../tasks/secure_haiku_20260301_071231--baseline-local-direct--django-repo-scoped-access-001.html) | [source](../../../benchmarks/ccb_secure/django-repo-scoped-access-001) | `baseline-local-direct` | `passed` | 1.000 | 4 | 0.000 |
| [sgonly_django-repo-scoped-access-001](../tasks/secure_haiku_20260301_071231--mcp-remote-direct--sgonly_django-repo-scoped-access-001.html) | [source](../../../benchmarks/ccb_secure/django-repo-scoped-access-001) | `mcp-remote-direct` | `passed` | 1.000 | 4 | 0.570 |
| [django-role-based-access-001](../tasks/secure_haiku_20260301_071231--baseline-local-direct--django-role-based-access-001.html) | [source](../../../benchmarks/ccb_secure/django-role-based-access-001) | `baseline-local-direct` | `passed` | 0.800 | 4 | 0.000 |
| [mcp_django-role-based-access-001_2ERzmK](../tasks/ccb_secure_haiku_20260224_213146--mcp-remote-direct--mcp_django-role-based-access-001_2ERzmK.html) | [source](../../../benchmarks/ccb_secure/django-role-based-access-001) | `mcp-remote-direct` | `failed` | 0.000 | 4 | 0.452 |
| [sgonly_django-role-based-access-001](../tasks/secure_haiku_20260301_071231--mcp-remote-direct--sgonly_django-role-based-access-001.html) | [source](../../../benchmarks/ccb_secure/django-role-based-access-001) | `mcp-remote-direct` | `passed` | 0.700 | 4 | 0.364 |
| [django-sensitive-file-exclusion-001](../tasks/secure_haiku_20260301_071231--baseline-local-direct--django-sensitive-file-exclusion-001.html) | [source](../../../benchmarks/ccb_secure/django-sensitive-file-exclusion-001) | `baseline-local-direct` | `passed` | 1.000 | 4 | 0.000 |
| [mcp_django-sensitive-file-exclusion-001_I216lD](../tasks/ccb_secure_haiku_20260224_213146--mcp-remote-direct--mcp_django-sensitive-file-exclusion-001_I216lD.html) | [source](../../../benchmarks/ccb_secure/django-sensitive-file-exclusion-001) | `mcp-remote-direct` | `passed` | 0.500 | 4 | 0.352 |
| [sgonly_django-sensitive-file-exclusion-001](../tasks/secure_haiku_20260301_071231--mcp-remote-direct--sgonly_django-sensitive-file-exclusion-001.html) | [source](../../../benchmarks/ccb_secure/django-sensitive-file-exclusion-001) | `mcp-remote-direct` | `passed` | 1.000 | 4 | 0.254 |
| [envoy-cve-triage-001](../tasks/secure_haiku_20260301_071231--baseline-local-direct--envoy-cve-triage-001.html) | — | `baseline-local-direct` | `passed` | 0.900 | 4 | 0.000 |
| [sgonly_envoy-cve-triage-001](../tasks/secure_haiku_20260301_071231--mcp-remote-direct--sgonly_envoy-cve-triage-001.html) | — | `mcp-remote-direct` | `passed` | 0.940 | 4 | 0.913 |
| [envoy-vuln-reachability-001](../tasks/secure_haiku_20260301_071231--baseline-local-direct--envoy-vuln-reachability-001.html) | — | `baseline-local-direct` | `passed` | 0.500 | 4 | 0.000 |
| [mcp_envoy-vuln-reachability-001_xNDUVv](../tasks/ccb_secure_haiku_20260228_124521--mcp-remote-direct--mcp_envoy-vuln-reachability-001_xNDUVv.html) | — | `mcp-remote-direct` | `passed` | 0.660 | 5 | 0.944 |
| [sgonly_envoy-vuln-reachability-001](../tasks/secure_haiku_20260301_071231--mcp-remote-direct--sgonly_envoy-vuln-reachability-001.html) | — | `mcp-remote-direct` | `passed` | 0.660 | 5 | 0.889 |
| [flipt-degraded-context-fix-001](../tasks/secure_haiku_20260301_071231--baseline-local-direct--flipt-degraded-context-fix-001.html) | [source](../../../benchmarks/ccb_secure/flipt-degraded-context-fix-001) | `baseline-local-direct` | `passed` | 0.250 | 4 | 0.000 |
| [mcp_flipt-degraded-context-fix-001_glgbpu](../tasks/ccb_secure_haiku_20260228_124521--mcp-remote-direct--mcp_flipt-degraded-context-fix-001_glgbpu.html) | [source](../../../benchmarks/ccb_secure/flipt-degraded-context-fix-001) | `mcp-remote-direct` | `passed` | 0.450 | 5 | 0.271 |
| [sgonly_flipt-degraded-context-fix-001](../tasks/secure_haiku_20260301_071231--mcp-remote-direct--sgonly_flipt-degraded-context-fix-001.html) | [source](../../../benchmarks/ccb_secure/flipt-degraded-context-fix-001) | `mcp-remote-direct` | `passed` | 0.600 | 5 | 0.468 |
| [flipt-repo-scoped-access-001](../tasks/secure_haiku_20260301_071231--baseline-local-direct--flipt-repo-scoped-access-001.html) | [source](../../../benchmarks/ccb_secure/flipt-repo-scoped-access-001) | `baseline-local-direct` | `passed` | 0.250 | 4 | 0.000 |
| [sgonly_flipt-repo-scoped-access-001](../tasks/secure_haiku_20260301_071231--mcp-remote-direct--sgonly_flipt-repo-scoped-access-001.html) | [source](../../../benchmarks/ccb_secure/flipt-repo-scoped-access-001) | `mcp-remote-direct` | `passed` | 0.500 | 4 | 0.118 |
| [golang-net-cve-triage-001](../tasks/secure_haiku_20260301_071231--baseline-local-direct--golang-net-cve-triage-001.html) | — | `baseline-local-direct` | `passed` | 0.800 | 4 | 0.000 |
| [sgonly_golang-net-cve-triage-001](../tasks/secure_haiku_20260301_071231--mcp-remote-direct--sgonly_golang-net-cve-triage-001.html) | — | `mcp-remote-direct` | `passed` | 0.800 | 4 | 0.917 |
| [grpcurl-transitive-vuln-001](../tasks/secure_haiku_20260301_071231--baseline-local-direct--grpcurl-transitive-vuln-001.html) | [source](../../../benchmarks/ccb_secure/grpcurl-transitive-vuln-001) | `baseline-local-direct` | `passed` | 0.670 | 4 | 0.000 |
| [sgonly_grpcurl-transitive-vuln-001](../tasks/secure_haiku_20260301_071231--mcp-remote-direct--sgonly_grpcurl-transitive-vuln-001.html) | [source](../../../benchmarks/ccb_secure/grpcurl-transitive-vuln-001) | `mcp-remote-direct` | `passed` | 0.670 | 4 | 0.889 |
| [kafka-sasl-auth-audit-001](../tasks/secure_haiku_20260301_071231--baseline-local-direct--kafka-sasl-auth-audit-001.html) | [source](../../../benchmarks/ccb_secure/kafka-sasl-auth-audit-001) | `baseline-local-direct` | `passed` | 0.400 | 4 | 0.000 |
| [sgonly_kafka-sasl-auth-audit-001](../tasks/secure_haiku_20260301_071231--mcp-remote-direct--sgonly_kafka-sasl-auth-audit-001.html) | [source](../../../benchmarks/ccb_secure/kafka-sasl-auth-audit-001) | `mcp-remote-direct` | `passed` | 0.860 | 4 | 0.960 |
| [kafka-vuln-reachability-001](../tasks/secure_haiku_20260301_071231--baseline-local-direct--kafka-vuln-reachability-001.html) | — | `baseline-local-direct` | `passed` | 0.880 | 4 | 0.000 |
| [sgonly_kafka-vuln-reachability-001](../tasks/secure_haiku_20260301_071231--mcp-remote-direct--sgonly_kafka-vuln-reachability-001.html) | — | `mcp-remote-direct` | `passed` | 0.900 | 4 | 0.955 |
| [postgres-client-auth-audit-001](../tasks/secure_haiku_20260301_071231--baseline-local-direct--postgres-client-auth-audit-001.html) | — | `baseline-local-direct` | `passed` | 0.730 | 4 | 0.000 |
| [sgonly_postgres-client-auth-audit-001](../tasks/secure_haiku_20260301_071231--mcp-remote-direct--sgonly_postgres-client-auth-audit-001.html) | — | `mcp-remote-direct` | `passed` | 0.790 | 4 | 0.925 |
| [wish-transitive-vuln-001](../tasks/secure_haiku_20260301_071231--baseline-local-direct--wish-transitive-vuln-001.html) | — | `baseline-local-direct` | `passed` | 0.760 | 4 | 0.000 |
| [sgonly_wish-transitive-vuln-001](../tasks/secure_haiku_20260301_071231--mcp-remote-direct--sgonly_wish-transitive-vuln-001.html) | — | `mcp-remote-direct` | `passed` | 0.670 | 4 | 0.923 |

## Multi-Run Variance

Tasks with multiple valid runs (24 task/config pairs).

| Task | Benchmark | Config | Runs | Mean | Std | Individual Rewards |
|---|---|---|---:|---:|---:|---|
| curl-cve-triage-001 | [source](../../../benchmarks/ccb_secure/curl-cve-triage-001) | `baseline-local-direct` | 3 | 0.627 | 0.543 | 0.940, 0.000, 0.940 |
| curl-cve-triage-001 | [source](../../../benchmarks/ccb_secure/curl-cve-triage-001) | `mcp-remote-direct` | 3 | 0.940 | 0.000 | 0.940, 0.940, 0.940 |
| curl-vuln-reachability-001 | [source](../../../benchmarks/ccb_secure/curl-vuln-reachability-001) | `baseline-local-direct` | 3 | 0.870 | 0.035 | 0.910, 0.850, 0.850 |
| curl-vuln-reachability-001 | [source](../../../benchmarks/ccb_secure/curl-vuln-reachability-001) | `mcp-remote-direct` | 3 | 0.740 | 0.121 | 0.850, 0.610, 0.760 |
| django-audit-trail-implement-001 | [source](../../../benchmarks/ccb_secure/django-audit-trail-implement-001) | `baseline-local-direct` | 3 | 0.700 | 0.260 | 0.550, 1.000, 0.550 |
| django-audit-trail-implement-001 | [source](../../../benchmarks/ccb_secure/django-audit-trail-implement-001) | `mcp-remote-direct` | 3 | 0.550 | 0.000 | 0.550, 0.550, 0.550 |
| django-cross-team-boundary-001 | [source](../../../benchmarks/ccb_secure/django-cross-team-boundary-001) | `baseline-local-direct` | 3 | 0.533 | 0.404 | 0.300, 1.000, 0.300 |
| django-cross-team-boundary-001 | [source](../../../benchmarks/ccb_secure/django-cross-team-boundary-001) | `mcp-remote-direct` | 3 | 0.367 | 0.116 | 0.500, 0.300, 0.300 |
| django-legacy-dep-vuln-001 | [source](../../../benchmarks/ccb_secure/django-legacy-dep-vuln-001) | `baseline-local-direct` | 3 | 0.967 | 0.058 | 0.900, 1.000, 1.000 |
| django-legacy-dep-vuln-001 | [source](../../../benchmarks/ccb_secure/django-legacy-dep-vuln-001) | `mcp-remote-direct` | 3 | 0.883 | 0.202 | 0.650, 1.000, 1.000 |
| django-repo-scoped-access-001 | [source](../../../benchmarks/ccb_secure/django-repo-scoped-access-001) | `baseline-local-direct` | 3 | 0.833 | 0.289 | 0.500, 1.000, 1.000 |
| django-repo-scoped-access-001 | [source](../../../benchmarks/ccb_secure/django-repo-scoped-access-001) | `mcp-remote-direct` | 3 | 0.800 | 0.173 | 0.700, 0.700, 1.000 |
| django-role-based-access-001 | [source](../../../benchmarks/ccb_secure/django-role-based-access-001) | `baseline-local-direct` | 4 | 0.425 | 0.287 | 0.200, 0.200, 0.500, 0.800 |
| django-role-based-access-001 | [source](../../../benchmarks/ccb_secure/django-role-based-access-001) | `mcp-remote-direct` | 3 | 0.567 | 0.513 | 0.000, 1.000, 0.700 |
| django-sensitive-file-exclusion-001 | [source](../../../benchmarks/ccb_secure/django-sensitive-file-exclusion-001) | `baseline-local-direct` | 4 | 0.900 | 0.116 | 0.800, 0.800, 1.000, 1.000 |
| django-sensitive-file-exclusion-001 | [source](../../../benchmarks/ccb_secure/django-sensitive-file-exclusion-001) | `mcp-remote-direct` | 4 | 0.750 | 0.289 | 1.000, 0.500, 0.500, 1.000 |
| flipt-degraded-context-fix-001 | [source](../../../benchmarks/ccb_secure/flipt-degraded-context-fix-001) | `baseline-local-direct` | 3 | 0.367 | 0.202 | 0.600, 0.250, 0.250 |
| flipt-degraded-context-fix-001 | [source](../../../benchmarks/ccb_secure/flipt-degraded-context-fix-001) | `mcp-remote-direct` | 4 | 0.438 | 0.144 | 0.250, 0.450, 0.450, 0.600 |
| flipt-repo-scoped-access-001 | [source](../../../benchmarks/ccb_secure/flipt-repo-scoped-access-001) | `baseline-local-direct` | 3 | 0.450 | 0.180 | 0.600, 0.500, 0.250 |
| flipt-repo-scoped-access-001 | [source](../../../benchmarks/ccb_secure/flipt-repo-scoped-access-001) | `mcp-remote-direct` | 3 | 0.567 | 0.058 | 0.600, 0.600, 0.500 |
| grpcurl-transitive-vuln-001 | [source](../../../benchmarks/ccb_secure/grpcurl-transitive-vuln-001) | `baseline-local-direct` | 3 | 0.447 | 0.387 | 0.000, 0.670, 0.670 |
| grpcurl-transitive-vuln-001 | [source](../../../benchmarks/ccb_secure/grpcurl-transitive-vuln-001) | `mcp-remote-direct` | 3 | 0.670 | 0.000 | 0.670, 0.670, 0.670 |
| kafka-sasl-auth-audit-001 | [source](../../../benchmarks/ccb_secure/kafka-sasl-auth-audit-001) | `baseline-local-direct` | 3 | 0.687 | 0.250 | 0.860, 0.800, 0.400 |
| kafka-sasl-auth-audit-001 | [source](../../../benchmarks/ccb_secure/kafka-sasl-auth-audit-001) | `mcp-remote-direct` | 3 | 0.827 | 0.058 | 0.760, 0.860, 0.860 |
