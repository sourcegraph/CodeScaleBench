# IMPORTANT: Source Code Access

**Local source files are not present.** Your workspace does not contain source code. You **MUST** use Sourcegraph MCP tools to discover, read, and understand code before making any changes.

**Target Repository:** `github.com/sg-evals/istio--44d0e58e`
- Use `repo:^github.com/sg-evals/istio--44d0e58e$` filter in keyword_search
- Use `github.com/sg-evals/istio--44d0e58e` as the `repo` parameter for go_to_definition/find_references/read_file


## Required Workflow

1. **Search first** — Use MCP tools to find relevant files and understand existing patterns
2. **Read remotely** — Use `sg_read_file` to read full file contents from Sourcegraph
3. **Edit locally** — Use Edit, Write, and Bash to create or modify files in your working directory
4. **Verify locally** — Run tests with Bash to check your changes

## Tool Selection

| Goal | Tool |
|------|------|
| Exact symbol/string | `sg_keyword_search` |
| Concepts/semantic search | `sg_nls_search` |
| Trace usage/callers | `sg_find_references` |
| See implementation | `sg_go_to_definition` |
| Read full file | `sg_read_file` |
| Browse structure | `sg_list_files` |
| Find repos | `sg_list_repos` |
| Search commits | `sg_commit_search` |
| Track changes | `sg_diff_search` |
| Compare versions | `sg_compare_revisions` |

**Decision logic:**
1. Know the exact symbol? → `sg_keyword_search`
2. Know the concept, not the name? → `sg_nls_search`
3. Need definition of a symbol? → `sg_go_to_definition`
4. Need all callers/references? → `sg_find_references`
5. Need full file content? → `sg_read_file`

## Scoping (Always Do This)

```
repo:^github.com/ORG/REPO$           # Exact repo (preferred)
repo:github.com/ORG/                 # All repos in org
file:.*\.ts$                         # TypeScript only
file:src/api/                        # Specific directory
```

Start narrow. Expand only if results are empty.

## Efficiency Rules

- Chain searches logically: search → read → references → definition
- Don't re-search for the same pattern; use results from prior calls
- Prefer `sg_keyword_search` over `sg_nls_search` when you have exact terms
- Read 2-3 related files before synthesising, rather than one at a time
- Don't read 20+ remote files without writing code — once you understand the pattern, start implementing

## If Stuck

If MCP search returns no results:
1. Broaden the search query (synonyms, partial identifiers)
2. Try `sg_nls_search` for semantic matching
3. Use `sg_list_files` to browse the directory structure
4. Use `sg_list_repos` to verify the repository name

---

# Architecture Q&A: Istio Pilot xDS Serving

**Repository:** github.com/sg-evals/istio--44d0e58e (mirror of istio/istio)
**Task Type:** Architecture Q&A (investigation only — no code changes)

## Background

Istio's Pilot component is the control plane that translates high-level Kubernetes resources (VirtualService, DestinationRule, ServiceEntry, Gateway) into low-level Envoy xDS configuration. Understanding how Pilot watches Kubernetes resources, builds an internal service model, and serves xDS responses to Envoy proxies is essential for working with the Istio codebase.

## Questions

Answer ALL of the following questions about Istio Pilot's xDS serving architecture:

### Q1: Config Ingestion Pipeline

How does Pilot watch and ingest Kubernetes custom resources (VirtualService, DestinationRule, ServiceEntry)?
- What component watches CRDs and how does it implement the `ConfigStoreController` interface?
- How are config change events queued and delivered to the xDS serving layer?
- What role does the aggregate service registry play in merging multiple service sources?

### Q2: Internal Service Model

How does Pilot translate platform-specific resources into its internal model?
- What are the key internal model types that represent services and endpoints?
- How does a Kubernetes Service get converted to the internal model, and how does a ServiceEntry differ?
- What is `PushContext` and what configuration indexes does it maintain?

### Q3: xDS Generation and Dispatch

When a configuration change occurs, how does Pilot generate and deliver xDS responses to connected Envoy proxies?
- How does `DiscoveryServer` receive config updates and debounce rapid changes?
- What is the generator architecture — how are CDS, EDS, LDS, and RDS generators registered and dispatched?
- How does `pushXds` select the correct generator for each resource type?

### Q4: Resource Translation

How do specific Istio resources map to Envoy xDS resource types?
- How does a DestinationRule's traffic policy translate into Envoy Cluster settings (CDS)?
- How does a VirtualService translate into Envoy route configuration (RDS)?
- What component builds the `ClusterLoadAssignment` for endpoint discovery (EDS)?

## Output Requirements

Write your answer to `/logs/agent/investigation.md` with the following structure:

```
# Istio Pilot xDS Serving Architecture

## Q1: Config Ingestion Pipeline
<answer with specific file paths, type names, and function references>

## Q2: Internal Service Model
<answer with specific file paths, type names, and function references>

## Q3: xDS Generation and Dispatch
<answer with specific file paths, type names, and function references>

## Q4: Resource Translation
<answer with specific file paths, type names, and function references>

## Evidence
<consolidated list of supporting file paths and line references>
```

## Constraints

- Do NOT modify any source files
- Cite specific files, types, and functions — avoid vague or speculative answers
- Focus on the `pilot/pkg/xds/`, `pilot/pkg/model/`, `pilot/pkg/config/`, and `pilot/pkg/networking/` directories
