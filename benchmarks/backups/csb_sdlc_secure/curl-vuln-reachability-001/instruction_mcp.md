# IMPORTANT: Source Code Access

**Local source files are not present.** Your workspace does not contain source code. You **MUST** use Sourcegraph MCP tools to discover, read, and understand code before making any changes.

**Target Repository:** `github.com/sg-evals/curl--09e25b9d`
- Use `repo:^github.com/sg-evals/curl--09e25b9d$` filter in keyword_search
- Use `github.com/sg-evals/curl--09e25b9d` as the `repo` parameter for go_to_definition/find_references/read_file


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

**Sourcegraph Repository:** `github.com/sg-evals/curl--09e25b9d`

# Security Reachability Analysis: curl SOCKS5 Proxy Handler

## Background

You are performing security reachability analysis on the curl codebase. A potential vulnerability has been identified in the function `do_SOCKS5()` implemented in `lib/socks.c`. This function handles SOCKS5 proxy handshake operations.

## Your Task

Determine whether the `do_SOCKS5()` function is reachable from external HTTP/HTTPS input in curl's normal operation. Specifically:

1. **Trace the complete call path** from curl's main HTTP handler (the entry point when a user runs `curl https://example.com --proxy socks5://proxy:1080`) to the `do_SOCKS5()` function
2. **Identify all intermediate functions** in the call chain
3. **Assess exploitability**: Is this function reachable from external attacker-controlled input when using a SOCKS5 proxy?
4. **Identify the attack vector**: What user action or network condition would trigger execution of `do_SOCKS5()`?

## Expected Output

Write your analysis to `/logs/agent/triage.md` with the following sections:

### 1. Summary
- Brief description of the reachability analysis
- Your conclusion: REACHABLE or UNREACHABLE from external input

### 2. Affected Code
- List the function `do_SOCKS5()` and its source file
- Describe what this function does

### 3. Attack Path
- **Complete call chain** from the entry point to `do_SOCKS5()` (format: `main() → function_a() → function_b() → do_SOCKS5()`)
- For each function in the chain, explain its role
- Identify which function accepts external input (from the network or command-line)

### 4. Severity Assessment
- **Reachability**: Can an attacker trigger this function? Under what conditions?
- **Attack vector**: What configuration or user action is required? (e.g., "User must specify a SOCKS5 proxy via --proxy flag")
- **External input**: What data from the attacker reaches this function? (e.g., proxy server responses, hostname lengths)

### 5. Remediation
- If reachable: What input validation or bounds checking should be added?
- If unreachable: What existing check or condition prevents exploitation?

## Constraints

- DO NOT modify any code — this is analysis only
- Focus on the SOCKS5 proxy code path, not other proxy types (HTTP CONNECT, etc.)
- The analysis must be based on the actual source code in `/workspace/curl/`, not external documentation

## Evaluation

Your review will be evaluated on detection accuracy and fix quality.
