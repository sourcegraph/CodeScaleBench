# IMPORTANT: Source Code Access

**Local source files are not present.** Your workspace does not contain source code. You **MUST** use Sourcegraph MCP tools to discover, read, and understand code before making any changes.

**Target Repository:** `github.com/sg-evals/envoy--v1.32.1`
- Use `repo:^github.com/sg-evals/envoy--v1.32.1$` filter in keyword_search
- Use `github.com/sg-evals/envoy--v1.32.1` as the `repo` parameter for go_to_definition/find_references/read_file


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

# Onboarding: Envoy Contributor Workflow Discovery

**Repository:** github.com/sg-evals/envoy--v1.32.1 (mirror of envoyproxy/envoy)
**Task Type:** Workflow Discovery (analysis only — no code changes)

## Scenario

You want to contribute a bug fix to Envoy, but you've never worked with Bazel or the Envoy codebase before. Before you can submit a pull request, you need to understand the contributor workflow: how to build the project, run tests, understand the CI pipeline, and navigate the code review process.

## Your Task

Explore the Envoy repository and create a contributor guide covering the essential workflow steps. Write your guide to `/logs/agent/onboarding.md`.

### Questions to Answer

1. **Build Prerequisites**: What tools and dependencies must be installed before you can build Envoy? What versions are required? Where is this documented?

2. **Build System**: What build system does Envoy use? What are the key build commands to:
   - Build the entire project
   - Build a specific component or test
   - Build with different configurations (debug vs release)

3. **Running Tests**: How do you run tests in Envoy? Document:
   - Command to run all tests
   - Command to run a specific test or test suite
   - What test frameworks are used (unit tests, integration tests)
   - Where are test utilities and helpers located?

4. **CI Pipeline**: Describe Envoy's continuous integration system:
   - What CI platform(s) are used?
   - Where are CI configuration files located?
   - What checks run on pull requests (build, test, lint, coverage)?
   - How long does a typical CI run take?

5. **Code Review Process**: What is the code review workflow for Envoy?
   - Where is the contribution guide documented?
   - What are the requirements for submitting a PR (DCO sign-off, tests, docs)?
   - How are reviewers assigned?
   - What coding standards or style guides must be followed?

6. **Developer Workflow Example**: Walk through a concrete example workflow: "I want to fix a bug in the HTTP connection manager filter. What are the exact steps from cloning the repo to getting my PR merged?"

## Output Requirements

Write your contributor guide to `/logs/agent/onboarding.md` with this structure:

```
# Envoy Contributor Guide

## 1. Build Prerequisites
<Your answer>

## 2. Build System
<Your answer>

## 3. Running Tests
<Your answer>

## 4. CI Pipeline
<Your answer>

## 5. Code Review Process
<Your answer>

## 6. Developer Workflow Example
<Your answer>
```

## Constraints

- Do NOT modify any source files
- Do NOT write any code changes
- Your job is exploration and documentation only
- Be specific — include exact commands, file paths, configuration file names, and URLs where relevant
- Focus on practical workflow steps that a real contributor would need
