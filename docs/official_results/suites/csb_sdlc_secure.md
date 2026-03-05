# csb_sdlc_secure

## Run/Config Summary

| Run | Config | Valid Tasks | Mean Reward | Pass Rate |
|---|---|---:|---:|---:|
| [csb_sdlc/csb_sdlc_secure](../runs/csb_sdlc-csb_sdlc_secure.md) | `baseline-local-direct` | 12 | 0.668 | 1.000 |
| [csb_sdlc/csb_sdlc_secure](../runs/csb_sdlc-csb_sdlc_secure.md) | `mcp-remote-direct` | 17 | 0.598 | 0.941 |

## Tasks

| Task | Benchmark | Config | Status | Reward | Runs | MCP Ratio |
|---|---|---|---|---:|---:|---:|
| [curl-cve-triage-001](../tasks/csb_sdlc-csb_sdlc_secure--baseline--curl-cve-triage-001--acd70b483e.html) | [source](../../../benchmarks/csb_sdlc_secure/curl-cve-triage-001) | `baseline-local-direct` | `passed` | 0.940 | 1 | 0.000 |
| [sgonly_curl-cve-triage-001](../tasks/csb_sdlc-csb_sdlc_secure--mcp--sgonly_curl-cve-triage-001--dac2e6e373.html) | [source](../../../benchmarks/csb_sdlc_secure/curl-cve-triage-001) | `mcp-remote-direct` | `passed` | 0.940 | 1 | 0.889 |
| [curl-vuln-reachability-001](../tasks/csb_sdlc-csb_sdlc_secure--baseline--curl-vuln-reachability-001--75070f864d.html) | [source](../../../benchmarks/csb_sdlc_secure/curl-vuln-reachability-001) | `baseline-local-direct` | `passed` | 0.850 | 1 | 0.000 |
| [sgonly_curl-vuln-reachability-001](../tasks/csb_sdlc-csb_sdlc_secure--mcp--sgonly_curl-vuln-reachability-001--1cfadbc38b.html) | [source](../../../benchmarks/csb_sdlc_secure/curl-vuln-reachability-001) | `mcp-remote-direct` | `passed` | 0.850 | 1 | 0.960 |
| [django-audit-trail-implement-001](../tasks/csb_sdlc-csb_sdlc_secure--baseline--django-audit-trail-implement-001--50fb4a68e6.html) | [source](../../../benchmarks/csb_sdlc_secure/django-audit-trail-implement-001) | `baseline-local-direct` | `passed` | 0.750 | 2 | 0.000 |
| [mcp_django-audit-trail-implement-001_vnpld0](../tasks/csb_sdlc-csb_sdlc_secure--mcp--mcp_django-audit-trail-implement-001_vnpld0--af0f46f6f4.html) | [source](../../../benchmarks/csb_sdlc_secure/django-audit-trail-implement-001) | `mcp-remote-direct` | `passed` | 0.550 | 2 | 0.236 |
| [sgonly_django-audit-trail-implement-001](../tasks/csb_sdlc-csb_sdlc_secure--mcp--sgonly_django-audit-trail-implement-001--43015f4fbb.html) | [source](../../../benchmarks/csb_sdlc_secure/django-audit-trail-implement-001) | `mcp-remote-direct` | `passed` | 0.550 | 2 | 0.351 |
| [django-cross-team-boundary-001](../tasks/csb_sdlc-csb_sdlc_secure--baseline--django-cross-team-boundary-001--8d891fd048.html) | [source](../../../benchmarks/csb_sdlc_secure/django-cross-team-boundary-001) | `baseline-local-direct` | `passed` | 0.500 | 2 | 0.000 |
| [mcp_django-cross-team-boundary-001_kmm7u4](../tasks/csb_sdlc-csb_sdlc_secure--mcp--mcp_django-cross-team-boundary-001_kmm7u4--50a00db7a1.html) | [source](../../../benchmarks/csb_sdlc_secure/django-cross-team-boundary-001) | `mcp-remote-direct` | `passed` | 0.500 | 2 | 0.153 |
| [sgonly_django-cross-team-boundary-001](../tasks/csb_sdlc-csb_sdlc_secure--mcp--sgonly_django-cross-team-boundary-001--89eb12183f.html) | [source](../../../benchmarks/csb_sdlc_secure/django-cross-team-boundary-001) | `mcp-remote-direct` | `passed` | 0.500 | 2 | 0.232 |
| [django-legacy-dep-vuln-001](../tasks/csb_sdlc-csb_sdlc_secure--baseline--django-legacy-dep-vuln-001--7103dab446.html) | [source](../../../benchmarks/csb_sdlc_secure/django-legacy-dep-vuln-001) | `baseline-local-direct` | `passed` | 1.000 | 2 | 0.000 |
| [mcp_django-legacy-dep-vuln-001_ey2oju](../tasks/csb_sdlc-csb_sdlc_secure--mcp--mcp_django-legacy-dep-vuln-001_ey2oju--7f89c65a0d.html) | [source](../../../benchmarks/csb_sdlc_secure/django-legacy-dep-vuln-001) | `mcp-remote-direct` | `passed` | 1.000 | 2 | 0.170 |
| [sgonly_django-legacy-dep-vuln-001](../tasks/csb_sdlc-csb_sdlc_secure--mcp--sgonly_django-legacy-dep-vuln-001--31ee937e38.html) | [source](../../../benchmarks/csb_sdlc_secure/django-legacy-dep-vuln-001) | `mcp-remote-direct` | `passed` | 0.650 | 2 | 0.227 |
| [django-repo-scoped-access-001](../tasks/csb_sdlc-csb_sdlc_secure--baseline--django-repo-scoped-access-001--4e4d1e8acd.html) | [source](../../../benchmarks/csb_sdlc_secure/django-repo-scoped-access-001) | `baseline-local-direct` | `passed` | 0.700 | 2 | 0.000 |
| [mcp_django-repo-scoped-access-001_ln2iim](../tasks/csb_sdlc-csb_sdlc_secure--mcp--mcp_django-repo-scoped-access-001_ln2iim--99b4d8e0a8.html) | [source](../../../benchmarks/csb_sdlc_secure/django-repo-scoped-access-001) | `mcp-remote-direct` | `passed` | 0.700 | 2 | 0.476 |
| [sgonly_django-repo-scoped-access-001](../tasks/csb_sdlc-csb_sdlc_secure--mcp--sgonly_django-repo-scoped-access-001--74aed605e2.html) | [source](../../../benchmarks/csb_sdlc_secure/django-repo-scoped-access-001) | `mcp-remote-direct` | `passed` | 0.700 | 2 | 0.561 |
| [django-role-based-access-001](../tasks/csb_sdlc-csb_sdlc_secure--baseline--django-role-based-access-001--17558a8eb9.html) | [source](../../../benchmarks/csb_sdlc_secure/django-role-based-access-001) | `baseline-local-direct` | `passed` | 0.200 | 1 | 0.000 |
| [mcp_django-role-based-access-001_2ERzmK](../tasks/csb_sdlc-csb_sdlc_secure--mcp--mcp_django-role-based-access-001_2ERzmK--77b3576281.html) | [source](../../../benchmarks/csb_sdlc_secure/django-role-based-access-001) | `mcp-remote-direct` | `failed` | 0.000 | 1 | 0.452 |
| [django-sensitive-file-exclusion-001](../tasks/csb_sdlc-csb_sdlc_secure--baseline--django-sensitive-file-exclusion-001--3855f5509e.html) | [source](../../../benchmarks/csb_sdlc_secure/django-sensitive-file-exclusion-001) | `baseline-local-direct` | `passed` | 0.800 | 1 | 0.000 |
| [mcp_django-sensitive-file-exclusion-001_I216lD](../tasks/csb_sdlc-csb_sdlc_secure--mcp--mcp_django-sensitive-file-exclusion-001_I216lD--a6d4935fe6.html) | [source](../../../benchmarks/csb_sdlc_secure/django-sensitive-file-exclusion-001) | `mcp-remote-direct` | `passed` | 0.500 | 1 | 0.352 |
| [flipt-degraded-context-fix-001](../tasks/csb_sdlc-csb_sdlc_secure--baseline--flipt-degraded-context-fix-001--7bdc2a2958.html) | [source](../../../benchmarks/csb_sdlc_secure/flipt-degraded-context-fix-001) | `baseline-local-direct` | `passed` | 0.250 | 2 | 0.000 |
| [mcp_flipt-degraded-context-fix-001_glgbpu](../tasks/csb_sdlc-csb_sdlc_secure--mcp--mcp_flipt-degraded-context-fix-001_glgbpu--863f85fe3c.html) | [source](../../../benchmarks/csb_sdlc_secure/flipt-degraded-context-fix-001) | `mcp-remote-direct` | `passed` | 0.450 | 2 | 0.271 |
| [sgonly_flipt-degraded-context-fix-001](../tasks/csb_sdlc-csb_sdlc_secure--mcp--sgonly_flipt-degraded-context-fix-001--ac399aca7a.html) | [source](../../../benchmarks/csb_sdlc_secure/flipt-degraded-context-fix-001) | `mcp-remote-direct` | `passed` | 0.250 | 2 | 0.333 |
| [flipt-repo-scoped-access-001](../tasks/csb_sdlc-csb_sdlc_secure--baseline--flipt-repo-scoped-access-001--02f85ccde7.html) | [source](../../../benchmarks/csb_sdlc_secure/flipt-repo-scoped-access-001) | `baseline-local-direct` | `passed` | 0.600 | 1 | 0.000 |
| [sgonly_flipt-repo-scoped-access-001](../tasks/csb_sdlc-csb_sdlc_secure--mcp--sgonly_flipt-repo-scoped-access-001--582f8d59e7.html) | [source](../../../benchmarks/csb_sdlc_secure/flipt-repo-scoped-access-001) | `mcp-remote-direct` | `passed` | 0.600 | 1 | 0.184 |
| [grpcurl-transitive-vuln-001](../tasks/csb_sdlc-csb_sdlc_secure--baseline--grpcurl-transitive-vuln-001--6126cdfb7a.html) | [source](../../../benchmarks/csb_sdlc_secure/grpcurl-transitive-vuln-001) | `baseline-local-direct` | `passed` | 0.670 | 1 | 0.000 |
| [sgonly_grpcurl-transitive-vuln-001](../tasks/csb_sdlc-csb_sdlc_secure--mcp--sgonly_grpcurl-transitive-vuln-001--0434b02744.html) | [source](../../../benchmarks/csb_sdlc_secure/grpcurl-transitive-vuln-001) | `mcp-remote-direct` | `passed` | 0.670 | 1 | 0.952 |
| [kafka-sasl-auth-audit-001](../tasks/csb_sdlc-csb_sdlc_secure--baseline--kafka-sasl-auth-audit-001--92ce893a9e.html) | [source](../../../benchmarks/csb_sdlc_secure/kafka-sasl-auth-audit-001) | `baseline-local-direct` | `passed` | 0.760 | 1 | 0.000 |
| [sgonly_kafka-sasl-auth-audit-001](../tasks/csb_sdlc-csb_sdlc_secure--mcp--sgonly_kafka-sasl-auth-audit-001--b034f79fc9.html) | [source](../../../benchmarks/csb_sdlc_secure/kafka-sasl-auth-audit-001) | `mcp-remote-direct` | `passed` | 0.760 | 1 | 0.960 |
