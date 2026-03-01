# IMPORTANT: Source Code Access

**Local source files are not present.** Your workspace does not contain source code. You **MUST** use Sourcegraph MCP tools to discover, read, and understand code before making any changes.

**Target Repository:** `github.com/sg-evals/QuantLib--dbdcc14e`
- Use `repo:^github.com/sg-evals/QuantLib--dbdcc14e$` filter in keyword_search
- Use `github.com/sg-evals/QuantLib--dbdcc14e` as the `repo` parameter for go_to_definition/find_references/read_file


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

# big-code-quantlib-arch-001: QuantLib Barrier Option Pricing Chain

## Task

Trace the QuantLib pricing chain for a barrier option: instrument→pricing engine→term structure→stochastic process→path generator. Map how a call to BarrierOption.NPV() propagates through the Instrument/LazyObject calculate() mechanism, into the pricing engine (analytic or Monte Carlo), through the term structure queries, stochastic process evolution, and path generation.

## Context

- **Repository**: github.com/sg-evals/QuantLib--dbdcc14e (mirror of lballabio/QuantLib) (C++, ~450K LOC)
- **Category**: Architectural Understanding
- **Difficulty**: hard
- **Subsystem Focus**: ql/instruments/, ql/pricingengines/barrier/, ql/processes/, ql/termstructures/, ql/methods/montecarlo/

## Requirements

1. Identify all relevant components in the pricing chain from BarrierOption through to PathGenerator
2. Trace the dependency chain from NPV() through LazyObject.calculate() → Instrument.performCalculations() → engine.calculate()
3. Document how the McSimulation framework connects MonteCarloModel, PathGenerator, and PathPricer
4. Explain the term structure hierarchy (YieldTermStructure, BlackVolTermStructure) and how the stochastic process (GeneralizedBlackScholesProcess) uses them

## Expected Output

Write your analysis to `/logs/agent/solution.md` with the following structure:

```
## Files Examined
- path/to/file1.ext — role in architecture
- path/to/file2.ext — role in architecture
...

## Dependency Chain
1. Entry point: path/to/entry.ext
2. Calls: path/to/next.ext (via function/method name)
3. Delegates to: path/to/impl.ext
...

## Analysis
[Detailed architectural analysis including:
- Design patterns identified
- Component responsibilities
- Data flow description
- Interface contracts between components]

## Summary
[Concise 2-3 sentence summary answering the task question]
```

## Evaluation Criteria

- File recall: Did you find the correct set of architecturally relevant files?
- Dependency accuracy: Did you trace the correct dependency/call chain?
- Architectural coherence: Did you correctly identify the design patterns and component relationships?
