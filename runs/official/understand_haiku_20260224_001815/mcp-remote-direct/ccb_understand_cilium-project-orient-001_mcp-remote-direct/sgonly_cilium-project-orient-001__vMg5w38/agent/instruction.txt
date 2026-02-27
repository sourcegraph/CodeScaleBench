# IMPORTANT: Source Code Access

**Local source files are not present.** Your workspace does not contain source code. You **MUST** use Sourcegraph MCP tools to discover, read, and understand code before making any changes.

**Target Repository:** `github.com/sg-evals/cilium--v1.16.5`
- Use `repo:^github.com/sg-evals/cilium--v1.16.5$` filter in keyword_search
- Use `github.com/sg-evals/cilium--v1.16.5` as the `repo` parameter for go_to_definition/find_references/read_file


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

# Onboarding: Cilium Codebase Orientation

**Repository:** github.com/sg-evals/cilium--v1.16.5 (mirror of cilium/cilium)
**Task Type:** Codebase Orientation (analysis only — no code changes)

## Scenario

You are a new engineer joining a team that works on Cilium, a cloud-native networking, observability, and security platform that uses eBPF. Your manager has asked you to spend your first day exploring the codebase and answering key orientation questions so you can hit the ground running.

## Your Task

Explore the Cilium codebase and answer the following questions. Write your answers to `/logs/agent/onboarding.md`.

### Questions

1. **Main Entry Point**: Where does the cilium-agent binary start execution? Identify the main function, how the CLI is initialized, and what dependency injection framework is used to wire components together.

2. **Core Packages**: Identify at least 5 core packages under `pkg/` and describe what each one is responsible for. Focus on the packages that handle networking policy, the datapath, Kubernetes integration, endpoint management, and eBPF maps.

3. **Configuration Loading**: How does the agent load its configuration? Describe the configuration pipeline: what config formats are supported, what library is used for config binding, and What modules/interfaces define the main config struct?

4. **Test Structure**: How are tests organized in this project? Describe at least 3 different testing approaches used (e.g., unit tests, integration tests, privileged tests, BPF tests). Where do end-to-end tests live?

5. **Network Policy Pipeline**: Trace the path of a CiliumNetworkPolicy from CRD definition to eBPF enforcement. Identify at least 4 stages in this pipeline and name the relevant components or packages involved at each stage (e.g., CRD types, K8s watcher, policy repository, endpoint regeneration, BPF map sync).

6. **Adding a New Network Policy Type**: If you needed to add a new type of network policy rule (e.g., a new L7 protocol filter), which packages and files would you need to modify? Describe the sequence of changes required.

## Output Requirements

Write your answers to `/logs/agent/onboarding.md` with this structure:

```
# Cilium Codebase Orientation

## 1. Main Entry Point
<Your answer>

## 2. Core Packages
<Your answer>

## 3. Configuration Loading
<Your answer>

## 4. Test Structure
<Your answer>

## 5. Network Policy Pipeline
<Your answer>

## 6. Adding a New Network Policy Type
<Your answer>
```

## Constraints

- Do NOT modify any source files
- Do NOT write any code changes
- Your job is exploration and documentation only
- Be specific — include file paths, package names, function names, and struct names where relevant
