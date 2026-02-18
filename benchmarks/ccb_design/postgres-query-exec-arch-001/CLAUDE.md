# big-code-pg-arch-001: PostgreSQL Query Execution Pipeline

This repository is large (~1.5M LOC). Use comprehensive search strategies for broad architectural queries rather than narrow, single-directory scopes.

## Task Type: Architectural Understanding

Your goal is to analyze and explain the PostgreSQL query execution pipeline. Focus on:

1. **Component identification**: Find all major stages (parser, analyzer, rewriter, planner, executor) and their entry points
2. **Dependency mapping**: Trace the data transformations: SQL string -> RawStmt -> Query -> PlannedStmt -> tuples
3. **Design pattern recognition**: Pipeline architecture, Volcano-style pull-based executor, two-phase optimization (Paths then Plans)
4. **Interface boundaries**: Node type definitions in src/include/nodes/, hook points for extensions

## Output Format

Write your analysis to `/logs/agent/solution.md` with these required sections:

```markdown
## Files Examined
- path/to/file.ext — role in the architecture

## Dependency Chain
1. path/to/core.ext (foundational types/interfaces)
2. path/to/impl.ext (implementation layer)
3. path/to/integration.ext (integration/wiring layer)

## Analysis
[Your architectural analysis]
```

## Search Strategy

- Start with `src/backend/tcop/postgres.c` (traffic cop, orchestrates the full pipeline)
- Explore `src/backend/parser/` for lexer (scan.l), grammar (gram.y), and analyzer (analyze.c)
- Check `src/backend/optimizer/plan/planner.c` and `src/backend/optimizer/path/allpaths.c` for the planner
- Examine `src/backend/executor/execMain.c` and `src/backend/executor/execProcnode.c` for the executor
- Use `find_references` to trace function calls between pipeline stages
