# big-code-pg-arch-001: PostgreSQL Query Execution Pipeline

## Task

Trace the PostgreSQL query execution pipeline from parse to execute. Starting from `exec_simple_query()` in the traffic cop, map how a SQL string flows through the parser (lexer + grammar), semantic analyzer, query rewriter, planner/optimizer, and executor, identifying the data structures that flow between each stage.

## Context

- **Repository**: postgres/postgres (C, ~1.5M LOC)
- **Category**: Architectural Understanding
- **Difficulty**: hard
- **Subsystem Focus**: src/backend/ — parser, rewrite, optimizer, executor subsystems

## Requirements

1. Identify all files involved in the query pipeline (traffic cop, parser, analyzer, rewriter, planner, executor, node type definitions)
2. Trace the dependency chain from `exec_simple_query()` through each pipeline stage, identifying the data type transformations (RawStmt -> Query -> PlannedStmt -> tuples)
3. Document the two-phase optimization (Path generation via allpaths.c, then Plan creation via createplan.c)
4. Explain the Volcano-style executor dispatch in execProcnode.c

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
