# Taxonomy Rationale: Work Types Over SDLC/Org Split

## Decision

CodeScaleBench organizes its 275 tasks by **developer work type**, not by an SDLC/Org distinction. All tasks represent realistic developer work in large, often multi-repo, enterprise codebases. The benchmark measures where and how improved context retrieval tools change task outcomes across these work types.

## Background

The benchmark was originally built in two phases:
1. **SDLC tasks** (from SWE-bench Pro, DIBench, custom-authored) — single-repo tasks organized by SDLC phase
2. **Org tasks** (from GTM use cases) — multi-repo tasks targeting enterprise scenarios like cross-repo tracing, compliance, incident response

This led to a two-tier framing: "CodeScaleBench-SDLC" vs "CodeScaleBench-Org," with 9 SDLC suites and 11 Org suites. The naming implied that SDLC tasks were *not* org-scale and that Org tasks were somehow outside the SDLC.

## Why the distinction is artificial

Both task families represent developer work in enterprise codebases:
- A developer **fixing a bug** in a monorepo is doing org-scale work
- A developer **tracing an incident** across microservices is also doing SDLC work (debugging)
- A developer **auditing security compliance** across repos is doing the same class of work as one reviewing a CVE in a single repo

The real axes that matter for measuring context retrieval impact are:

1. **Work type** — what the developer is doing (debugging, fixing, refactoring, understanding code, etc.)
2. **Structural complexity** — how many repos/files the task spans (single-repo, dual-repo, multi-repo)
3. **Codebase scale** — repo size, LOC

The SDLC/Org split conflated axis 1 with axis 2. "Debug" and "incident" are both debugging — at different repo scope. "Secure" and "compliance" are both security review at different scope.

## Unified work-type taxonomy

The 275 tasks are organized into 9 work types. Each contains tasks at varying structural complexity levels:

| Work Type | Tasks | Description | Repo Scope |
|-----------|------:|-------------|------------|
| **crossrepo** | 47 | Cross-repo navigation, dependency tracing, org-wide discovery | 18 single, 9 dual, 20 multi |
| **understand** | 44 | Codebase comprehension, architecture, onboarding, domain knowledge | 36 single, 4 dual, 4 multi |
| **refactor** | 43 | Code transformation, migration, dependency updates | 26 single, 2 dual, 15 multi |
| **security** | 39 | Security review, vulnerability remediation, compliance audit | 26 single, 2 dual, 11 multi |
| **feature** | 34 | Feature implementation, org-wide feature work | 24 single, 2 dual, 8 multi |
| **debug** | 26 | Debugging, root cause analysis, incident triage | 15 single, 8 dual, 3 multi |
| **fix** | 19 | Bug repair from issue reports | 19 single |
| **test** | 12 | Test generation, code review, QA | 12 single |
| **document** | 11 | API docs, architecture docs, migration guides | 10 single, 1 dual |

## Legacy directory names

The on-disk directory structure retains the `csb_sdlc_*` and `csb_org_*` prefixes for backward compatibility with existing runs and tooling. The mapping from directories to work types is:

| Work Type | Source Directories |
|-----------|--------------------|
| crossrepo | `csb_org_crossrepo`, `csb_org_crossrepo_tracing`, `csb_org_crossorg`, `csb_org_platform` |
| understand | `csb_sdlc_understand`, `csb_sdlc_design`, `csb_org_domain`, `csb_org_onboarding` |
| refactor | `csb_sdlc_refactor`, `csb_org_migration` |
| security | `csb_sdlc_secure`, `csb_org_security`, `csb_org_compliance` |
| feature | `csb_sdlc_feature`, `csb_org_org` |
| debug | `csb_sdlc_debug`, `csb_org_incident` |
| fix | `csb_sdlc_fix` |
| test | `csb_sdlc_test` |
| document | `csb_sdlc_document` |

## Analysis dimensions

Reports analyze results across three orthogonal dimensions:

1. **Work type** (9 categories above) — primary breakdown
2. **Structural complexity** (single-repo / dual-repo / multi-repo) — secondary breakdown, measures whether context retrieval helps more as scope widens
3. **Codebase scale** (LOC bins) — tertiary breakdown

The benchmark does NOT report "SDLC vs Org" as a meaningful comparison. The aggregate score and per-work-type breakdowns with bootstrap confidence intervals are the primary reporting structure.

## Statistical power

At 275 tasks total, only `crossrepo` (n=47, power=84.6%) achieves 80% power to detect a delta=0.05 MCP effect at alpha=0.05. The remaining work types have 12-66% power at the suite level. The overall benchmark has 99.9% power.

The reporting strategy uses:
- **Overall score** (n=275) for the headline finding
- **Per-work-type effect sizes with 95% bootstrap CIs** for the heatmap of where context retrieval matters most
- **No per-suite significance claims** except for crossrepo — all other suites report directionally with CIs
