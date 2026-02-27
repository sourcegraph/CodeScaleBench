# IMPORTANT: Source Code Access

**Local source files are not present.** Your workspace does not contain source code. You **MUST** use Sourcegraph MCP tools to discover, read, and understand code before making any changes.

**Target Repository:** `github.com/sg-evals/terraform--v1.9.0`
- Use `repo:^github.com/sg-evals/terraform--v1.9.0$` filter in keyword_search
- Use `github.com/sg-evals/terraform--v1.9.0` as the `repo` parameter for go_to_definition/find_references/read_file


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

**Sourcegraph Repository:** `github.com/sg-evals/terraform--v1.9.0`

# Team Handoff: Terraform State Backend Subsystem

## Scenario

You are taking over ownership of Terraform's state backend subsystem from a departing team member. The state backend is responsible for storing and managing Terraform state files, which contain the mapping between configured resources and real-world infrastructure.

Your team member has left limited documentation. Your task is to explore the codebase and produce a comprehensive handoff document that will help you and future team members understand, maintain, and extend the state backend system.

## Your Task

Explore the hashicorp/terraform codebase and create a structured handoff document covering the state backend subsystem. Your document should address the following sections:

### 1. Purpose
- What problem does the state backend subsystem solve?
- Why do we need different backend types (local, S3, remote, etc.)?
- What are the key responsibilities of a backend?

### 2. Dependencies
- What other Terraform subsystems does the backend interact with?
- What are the upstream dependencies (what calls into backends)?
- What are the downstream dependencies (what do backends call)?
- How does the backend system integrate with the broader Terraform architecture?

### 3. Relevant Components
- What are the main source files and directories for the backend subsystem?
- What modules/interfaces define the Backend interface?
- Where are concrete backend implementations located?
- What modules/interfaces define the state locking mechanism?
- What files are critical for understanding how backends work?

### 4. Failure Modes
- What can go wrong with state backends?
- How does the system handle state locking failures (stale locks, timeouts)?
- What happens when storage is unavailable?
- How are state corruption scenarios handled?
- What are common configuration errors and how are they detected?

### 5. Testing
- How are backends tested?
- What test patterns are used for backend implementations?
- Where are the backend tests located?
- How do you test state locking behavior?
- What integration tests exist for backends?

### 6. Debugging
- How do you troubleshoot state lock issues?
- How do you verify state consistency?
- What logs or diagnostics are available for debugging backend problems?
- How do you investigate stale locks or lock contention?

### 7. Adding a New Backend
- If you needed to add a new backend type (e.g., for a new cloud provider), what would be the step-by-step process?
- What interfaces need to be implemented?
- What files need to be created or modified?
- How is a new backend registered with the system?

## Deliverable

Create your handoff document as a markdown file at `/logs/agent/onboarding.md`.

Deliver a clear, well-structured document that covers all requested sections. Include:
- Specific file paths and directory names
- Key function/type names
- Code flow descriptions
- Concrete examples where helpful

## Evaluation

Your handoff document will be evaluated on:
- **Completeness**: All 7 sections addressed with substantive content
- **Accuracy**: Correct identification of relevant components, interfaces, and architectural patterns
- **Specificity**: Concrete file paths, type names, and code references (not generic descriptions)
- **Understanding**: Demonstrates comprehension of how the subsystem works, not just surface-level file listing

Good luck with your exploration!
