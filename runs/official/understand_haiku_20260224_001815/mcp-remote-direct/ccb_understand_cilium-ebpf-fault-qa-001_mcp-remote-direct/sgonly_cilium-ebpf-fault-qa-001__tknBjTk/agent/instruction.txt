# IMPORTANT: Source Code Access

**Local source files are not present.** Your workspace does not contain source code. You **MUST** use Sourcegraph MCP tools to discover, read, and understand code before making any changes.

**Target Repository:** `github.com/sg-evals/cilium--a2f97aa8`
- Use `repo:^github.com/sg-evals/cilium--a2f97aa8$` filter in keyword_search
- Use `github.com/sg-evals/cilium--a2f97aa8` as the `repo` parameter for go_to_definition/find_references/read_file


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

# Debug Q&A: Cilium eBPF Fault Isolation

**Repository:** github.com/sg-evals/cilium--a2f97aa8 (mirror of cilium/cilium)
**Task Type:** Debug Q&A (investigation only — no code changes)

## Background

Cilium is a Kubernetes CNI (Container Network Interface) plugin that uses eBPF (Extended Berkeley Packet Filter) programs to enforce network policies and route traffic. In a multi-node Kubernetes cluster, each node runs its own Cilium agent which compiles, loads, and attaches eBPF programs to enforce policies.

## Behavior Observation

**What happens:** When an eBPF program fails to compile or load on one Kubernetes node (e.g., due to a kernel verifier rejection, compilation error, or incompatible kernel features), the other nodes in the cluster continue to enforce their network policies normally. The failing node may log errors or degrade to a fallback mode, but the failure doesn't propagate cluster-wide.

**Why is this notable?** Many distributed systems that rely on shared state or centralized configuration can fail cluster-wide when one node encounters a problem. Cilium's architecture ensures that eBPF datapath failures are isolated to the affected node.

## Questions

Answer ALL of the following questions to explain this behavior:

### Q1: Per-Node eBPF Lifecycle

How are eBPF programs compiled, loaded, and attached on each node independently?
- What component is responsible for compiling eBPF programs on each node?
- How does node-specific configuration (kernel version, enabled features, etc.) affect compilation?
- At what point in the lifecycle does the eBPF program become node-local vs. cluster-wide?

### Q2: Deployment Architecture

How does Cilium's deployment model ensure per-node isolation?
- How is the Cilium agent deployed across the cluster (DaemonSet, static pods, etc.)?
- What happens when one node's Cilium agent fails to initialize its eBPF programs?
- How does the control plane vs. data plane split contribute to isolation?

### Q3: Policy Distribution vs. Enforcement

Cilium network policies are cluster-wide resources (CRDs), but enforcement is per-node. How does this work?
- How are CiliumNetworkPolicy resources distributed to each node?
- What component on each node translates policies into eBPF bytecode?
- Why doesn't a compilation failure on one node block policy distribution to other nodes?

### Q4: eBPF Map Scoping and State Isolation

eBPF programs use maps (hash tables, arrays) to store state. How is map state isolated across nodes?
- Are eBPF maps node-local or cluster-wide?
- What mechanisms (BPF filesystem pinning, namespaces) ensure map isolation?
- If a node fails to create or update a map, how does that affect other nodes' packet processing?

## Output Requirements

Write your answer to `/logs/agent/investigation.md` with the following structure:

```
# Cilium eBPF Fault Isolation

## Q1: Per-Node eBPF Lifecycle
<answer with specific file paths, class names, and function references>

## Q2: Deployment Architecture
<answer with specific file paths, class names, and function references>

## Q3: Policy Distribution vs. Enforcement
<answer with specific file paths, class names, and function references>

## Q4: eBPF Map Scoping and State Isolation
<answer with specific file paths, class names, and function references>

## Evidence
<consolidated list of supporting file paths and line references>
```

## Constraints

- Do NOT modify any source files
- Cite specific files, classes, and functions — avoid vague or speculative answers
- Focus on the `pkg/datapath/loader/`, `pkg/policy/`, `pkg/maps/`, and `pkg/endpoint/` directories
