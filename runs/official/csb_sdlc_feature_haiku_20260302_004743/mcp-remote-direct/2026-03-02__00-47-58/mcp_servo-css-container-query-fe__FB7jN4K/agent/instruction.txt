# IMPORTANT: Source Code Access

**Local source files are not present.** Your workspace does not contain source code. You **MUST** use Sourcegraph MCP tools to discover, read, and understand code before making any changes.

**Target Repositories (version-pinned mirrors):**

- `github.com/sg-evals/servo--be6a2f99` — use `repo:^github.com/sg-evals/servo--be6a2f99$` filter

Scope ALL keyword_search/nls_search queries to these repos.
Use the repo name as the `repo` parameter for read_file/go_to_definition/find_references.


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

**Sourcegraph Repositories:** `github.com/sg-evals/servo--be6a2f99`

# Task: Implement CSS Container Queries Size Evaluation in Servo

## Objective
Add CSS Container Queries support to Servo's style system, implementing the `@container` at-rule with size-based queries (`min-width`, `max-width`, `min-height`, `max-height`, `width`, `height`).

CSS Container Queries (CSS Containment Level 3) allow elements to be styled based on their container's size rather than the viewport. A container is designated via `container-type: size | inline-size` and queried with `@container (min-width: 400px) { ... }`.

## Requirements

1. **Define container type properties** in Servo's style properties:
   - Add `container-type` CSS property (values: `normal`, `size`, `inline-size`)
   - Add `container-name` CSS property (values: `none` or custom ident)
   - These should be defined in `components/style/properties/` following Servo's property definition pattern

2. **Parse @container rules** in the CSS parser:
   - Extend `components/style/stylesheets/` to handle `@container` at-rules
   - Parse container size conditions: `(min-width: Npx)`, `(max-width: Npx)`, `(width > Npx)`, etc.
   - Store parsed container queries in the stylesheet data structures

3. **Implement container query evaluation**:
   - In the style resolution path, evaluate container size queries against the actual container dimensions
   - Walk up the DOM tree to find the nearest container ancestor with matching `container-name`
   - Compare container dimensions against the query conditions

4. **Integrate with style matching**:
   - During rule matching, check if `@container` rules apply given the current container sizes
   - Rules inside a matching `@container` block should be included in the cascade

## Key Reference Files
- `components/style/properties/longhands/` — longhand property definitions (add container-type, container-name here)
- `components/style/stylesheets/rule_parser.rs` — at-rule parsing
- `components/style/stylesheets/container_rule.rs` — may already exist as a stub
- `components/style/matching.rs` — style matching/cascade logic
- `components/style/values/specified/length.rs` — length value parsing
- `components/style/media_queries/` — reference pattern for conditional rules (similar to @media)

## Success Criteria
- `container-type` property definition exists in properties
- `container-name` property definition exists in properties
- Container query parsing structures defined (ContainerCondition or similar)
- @container at-rule parsing integrated into stylesheet parser
- Size query evaluation logic exists (comparing dimensions against conditions)
- Integration point in style matching that checks container queries
