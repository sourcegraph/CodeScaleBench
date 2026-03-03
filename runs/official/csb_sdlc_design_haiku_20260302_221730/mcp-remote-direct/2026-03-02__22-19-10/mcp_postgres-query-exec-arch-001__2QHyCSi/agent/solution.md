# PostgreSQL Query Execution Pipeline: Parse to Execute

## Files Examined

### Entry Point and Traffic Cop
- **src/backend/tcop/postgres.c** — Traffic cop managing connections and query processing; contains `exec_simple_query()` entry point, `pg_parse_query()`, `pg_analyze_and_rewrite_fixedparams()`, and `pg_plan_query()` wrapper functions

### Parser Subsystem (Lexer + Grammar)
- **src/backend/parser/parser.c** — High-level parser interface containing `raw_parser()` which initializes the flex scanner and bison grammar, returns list of RawStmt nodes
- **src/backend/parser/scan.l** — Flex lexer (referenced via scanner_init)
- **src/backend/parser/gram.y** — Bison grammar rules for SQL parsing (referenced via base_yyparse)

### Semantic Analyzer
- **src/backend/parser/analyze.c** — Semantic analysis functions: `parse_analyze_fixedparams()`, `parse_analyze_varparams()`, `parse_analyze_withcb()` all call `transformTopLevelStmt()` to convert RawStmt → Query; includes post_parse_analyze_hook support

### Query Rewriter
- **src/backend/rewrite/rewriteHandler.c** — Query rewriting engine; contains `QueryRewrite()` (primary entry point), `RewriteQuery()`, and RIR (Retrieve-Into-Replace) rule application; transforms Query nodes via rule substitution and view expansion

### Planner/Optimizer
- **src/backend/optimizer/plan/planner.c** — Main optimizer entry point: `planner()` (hook point), `standard_planner()` sets up PlannerGlobal/PlannerInfo, calls `subquery_planner()`, invokes `get_cheapest_fractional_path()` to select best Path, and calls `create_plan()` to convert Path to Plan

- **src/backend/optimizer/plan/planmain.c** — Contains `query_planner()` for basic join operation planning (called by subquery_planner)

- **src/backend/optimizer/path/allpaths.c** — Path generation and cost analysis; contains functions like `set_base_rel_sizes()`, `set_rel_pathlist()`, `set_plain_rel_size()` that enumerate possible execution paths for each relation; implements exhaustive search (or GEQO heuristic) for join ordering

- **src/backend/optimizer/plan/createplan.c** — Plan node creation; contains `create_plan()` entry point and `create_plan_recurse()` that converts Path trees into Plan trees recursively; implements type-specific creators for each Path/Plan node type (SeqScan, IndexScan, joins, aggregates, sorts, etc.)

### Executor Subsystem
- **src/backend/executor/execProcnode.c** — Core dispatch mechanism; contains `ExecInitNode()` which recursively initializes plan state tree from Plan tree, and `ExecSetExecProcNode()` which sets up the ExecProcNodeMtd function pointers for Volcano-style dispatch

- **src/backend/executor/execMain.c** — High-level executor coordination: `ExecutorStart()` (hook point), `standard_ExecutorStart()` creates EState and calls ExecInitNode(), `ExecutorRun()` (hook point), `standard_ExecutorRun()` calls ExecutePlan() which drives ExecProcNode() dispatch loop, `ExecutorEnd()` cleanup

- **src/backend/executor/nodeSeqscan.c** (and other node*.c files) — Specific node execution implementations; each implements ExecInit*, Exec*, and ExecEnd* functions following the standard executor protocol

### Node Type Definitions
- **src/include/nodes/parsenodes.h** — Parse tree node definitions: RawStmt, Query, and all statement/expression node types
- **src/include/nodes/plannodes.h** — Plan node definitions: Plan (base), and all specific plan types (SeqScan, IndexScan, NestLoop, HashJoin, Sort, Agg, etc.)
- **src/include/nodes/execnodes.h** — Execution state node definitions: PlanState (base) with ExecProcNode method pointer, and all specific *State types
- **src/include/executor/execdesc.h** — QueryDesc structure bridging parser/planner results with executor

## Dependency Chain

### 1. Entry Point and Parsing Stage
**Entry:** `exec_simple_query()` in src/backend/tcop/postgres.c:1011
- Reads query_string from client
- Calls `pg_parse_query(query_string)` → src/backend/tcop/postgres.c:603

**Parsing:** `pg_parse_query()` in src/backend/tcop/postgres.c:603
- Calls `raw_parser(query_string, RAW_PARSE_DEFAULT)` → src/backend/parser/parser.c:42
- Returns: **List<RawStmt>** (raw, unanalyzed parse trees)

**Raw Parser:** `raw_parser()` in src/backend/parser/parser.c:42
- Initializes flex scanner via `scanner_init()`
- Initializes bison parser via `parser_init()`
- Executes `base_yyparse()` grammar rule matching
- Lexer (scan.l) tokenizes input
- Grammar (gram.y) performs syntactic analysis
- Returns: **List<RawStmt>** containing statement nodes from grammar

### 2. Semantic Analysis Stage
**Post-Parse Processing:** Loop through RawStmt list in src/backend/tcop/postgres.c:1094
- For each RawStmt, calls `pg_analyze_and_rewrite_fixedparams()` → src/backend/tcop/postgres.c:665

**Analysis:** `pg_analyze_and_rewrite_fixedparams()` in src/backend/tcop/postgres.c:665
- Calls `parse_analyze_fixedparams(parsetree, query_string, paramTypes, numParams, queryEnv)` → src/backend/parser/analyze.c:105
- Returns: **Query** (first stage only)

**Semantic Analyzer:** `parse_analyze_fixedparams()` in src/backend/parser/analyze.c:105
- Creates ParseState via `make_parsestate()`
- Calls `transformTopLevelStmt(pstate, parseTree)` (in analyze.c or parse_utilcmd.c)
- Optionally calls post_parse_analyze_hook for plugins
- Returns: **Query** (analyzed parse tree with:
  - Table and column references resolved to OIDs
  - Implicit type conversions added
  - Aggregate/group-by semantics checked
  - Window function attributes set)

### 3. Query Rewrite Stage
**Rewrite Entry:** `pg_analyze_and_rewrite_fixedparams()` continues after parse_analyze_fixedparams()
- Calls `pg_rewrite_query(query)` → src/backend/tcop/postgres.c:791

**Rewrite:** `pg_rewrite_query()` in src/backend/tcop/postgres.c:791
- Calls `QueryRewrite(query)` → src/backend/rewrite/rewriteHandler.c:4566
- Returns: **List<Query>** (rule expansion may produce multiple queries)

**Query Rewriter:** `QueryRewrite()` in src/backend/rewrite/rewriteHandler.c:4566
- Calls `RewriteQuery(parsetree, NIL, 0, 0)` for non-SELECT rules
- Applies RIR (Retrieve-Into-Replace) rules on each query
- Returns: **List<Query>** (possibly expanded if rules applied, or single Query if no rules)

### 4. Planning Stage
**Plan Entry:** For each rewritten Query, calls `pg_plan_query(querytree, query_string, cursorOptions, boundParams)` → src/backend/tcop/postgres.c:882

**Planner Wrapper:** `pg_plan_query()` in src/backend/tcop/postgres.c:882
- Calls `planner(querytree, query_string, cursorOptions, boundParams)` → src/backend/optimizer/plan/planner.c:287
- Returns: **PlannedStmt** (complete query execution plan)

**Planner Entry Point:** `planner()` in src/backend/optimizer/plan/planner.c:287
- Checks for planner_hook (plugin override point)
- Otherwise calls `standard_planner()` → src/backend/optimizer/plan/planner.c:303
- Returns: **PlannedStmt** with plan tree

**Standard Planner:** `standard_planner()` in src/backend/optimizer/plan/planner.c:303
- Creates PlannerGlobal structure (global state across all subqueries)
- Calls `subquery_planner(glob, parse, NULL, false, tuple_fraction, NULL)` → src/backend/optimizer/plan/planner.c (in same file, line ~1000)
  - This preprocesses the Query:
    - Processes subqueries recursively
    - Calls `query_planner()` → src/backend/optimizer/plan/planmain.c:53
    - Which calls `set_base_rel_sizes()` and `set_rel_pathlist()` to generate Paths
  - Returns: **PlannerInfo** with RelOptInfo tree containing Paths
- Calls `fetch_upper_rel(root, UPPERREL_FINAL, NULL)` to get final output relation
- Calls `get_cheapest_fractional_path(final_rel, tuple_fraction)` to select **best Path**
- Calls `create_plan(root, best_path)` → src/backend/optimizer/plan/createplan.c:337

### 5. Two-Phase Optimization

**Phase 1: Path Generation (allpaths.c)**
- `set_base_rel_pathlists()` calls `set_rel_pathlist()` for each base relation
- `set_rel_pathlist()` calls:
  - `create_plain_partial_paths()` for sequential scans
  - Index path generation via indxpath.c
  - Foreign data wrapper paths via fdw APIs
- For joins: `join_search_hook` (default standard_join_search in joinpath.c) generates:
  - NestLoop paths
  - MergeJoin paths
  - HashJoin paths
- Each path has associated **Cost** estimate (startup_cost, total_cost)
- Returns: **RelOptInfo** with list of Paths for each relation/join combination

**Phase 2: Plan Generation (createplan.c)**
- `create_plan(root, best_path)` → src/backend/optimizer/plan/createplan.c:337
- Calls `create_plan_recurse(root, best_path, CP_EXACT_TLIST)` → src/backend/optimizer/plan/createplan.c (line ~400)
- Recursively processes path tree, converting each Path to corresponding Plan:
  - `create_scan_plan()` for leaf paths (SeqScan, IndexScan, etc.)
  - `create_join_plan()` for join paths, calling type-specific creators:
    - `create_nestloop_plan()` for NestLoop
    - `create_mergejoin_plan()` for MergeJoin
    - `create_hashjoin_plan()` for HashJoin
  - Upper-level path creators for aggregates, sorts, window functions, etc.
- Returns: **Plan tree** (root is typically PlannedStmt.planTree, a Plan node)
- Remaining planner.c code wraps plan in PlannedStmt and performs setrefs.c variable fix-up

### 6. Execution Setup
**Executor Entry:** `ExecutorStart(queryDesc, eflags)` → src/backend/executor/execMain.c:122

**Executor Wrapper:** `ExecutorStart()` in src/backend/executor/execMain.c:122
- Checks ExecutorStart_hook (plugin override point)
- Otherwise calls `standard_ExecutorStart()` → src/backend/executor/execMain.c:141
- Returns: QueryDesc with populated estate and planstate

**Standard Executor Start:** `standard_ExecutorStart()` in src/backend/executor/execMain.c:141
- Creates **EState** (execution state) via `CreateExecutorState()`
- Calls `InitPlan()` (in execMain.c) which calls:
  - `ExecInitNode(queryDesc->plannedstmt->planTree, estate, eflags)` → src/backend/executor/execProcnode.c:142
- Returns: **PlanState tree** (mirror of Plan tree with runtime state)

**Node Initialization Dispatch:** `ExecInitNode()` in src/backend/executor/execProcnode.c:142
- Examines Plan node type via switch statement
- Calls corresponding init function:
  - `ExecInitSeqScan()` → src/backend/executor/nodeSeqscan.c
  - `ExecInitIndexScan()` → src/backend/executor/nodeIndexscan.c
  - `ExecInitNestLoop()` → src/backend/executor/nodeNestloop.c
  - etc. (one for each node type)
- Each init function:
  - Creates corresponding PlanState node (e.g., SeqScanState)
  - Recursively calls ExecInitNode() on child plans
  - Initializes node-specific state (scan descriptors, hash tables, etc.)
  - Sets ExecProcNode function pointer to correct executor function
- Returns: **PlanState** (node-specific, e.g., SeqScanState)

### 7. Execution Loop (Volcano-Style Dispatch)
**Executor Run:** `ExecutorRun(queryDesc, direction, count)` → src/backend/executor/execMain.c:297

**Standard Executor Run:** `standard_ExecutorRun()` in src/backend/executor/execMain.c:307
- Calls `ExecutePlan()` (in execMain.c) which loops calling:
  - `ExecProcNode(queryDesc->planstate)` → dispatched via function pointer

**Volcano-Style Dispatch:** Each PlanState.ExecProcNode() points to executor function
- For SeqScanState: calls `ExecSeqScan()` → fetches next tuple from heap
- For NestLoopState: calls `ExecNestLoop()` → calls ExecProcNode() on children, joins results
- For AggState: calls `ExecAgg()` → aggregates input tuples
- For SortState: calls `ExecSort()` → sorts tuples from child node
- Pattern: Inner nodes repeatedly call ExecProcNode() on their children
- Returns: **TupleTableSlot** (containing tuple data or NULL if exhausted)

**Execution Dispatch Setup:** `ExecSetExecProcNode()` in src/backend/executor/execProcnode.c:430
- Wraps the actual executor function with:
  - `ExecProcNodeFirst()` on first call (one-time setup)
  - `ExecProcNodeInstr()` if instrumentation enabled (timing/row counts)
  - Direct executor function for normal operation
- Allows dynamic function pointer switching without overhead

### 8. Execution Cleanup
**Executor End:** `ExecutorEnd(queryDesc)` → src/backend/executor/execMain.c:325
- Calls `ExecEndNode()` recursively through plan state tree
- Each node's ExecEnd* function releases resources (file descriptors, temp tables, etc.)
- Destroys per-query memory context

## Analysis

### Design Patterns Identified

**1. Visitor Pattern (Compilation Stage)**
- The parser (raw_parser → raw_parsetree) and semantic analyzer (transformTopLevelStmt) use recursive descent to traverse the AST and transform nodes

**2. Compiler Pipeline Pattern**
- Multiple distinct passes (parse → analyze → rewrite → plan) with clear intermediate data structures (RawStmt → Query → Query → Plan)
- Each stage can be independently overridden via hooks (post_parse_analyze_hook, planner_hook, ExecutorStart_hook)
- Separation allows query cache at different levels (raw SQL → RawStmt, or pre-analyzed Query)

**3. Cost-Based Search (Path Selection)**
- **allpaths.c** generates all feasible execution paths with cost estimates
- `get_cheapest_fractional_path()` applies a simple greedy selection: pick the lowest-cost path
- For larger join orders, GEQO (genetic query optimizer) heuristic replaces exhaustive search

**4. Volcano/Iterator Model (Execution)**
- **execProcnode.c** implements the classic Volcano (push-based) execution model
- Each plan node type has three functions:
  - ExecInit*: Initialize node and child nodes
  - Exec*: Return next tuple (or NULL if exhausted)
  - ExecEnd*: Clean up
- Composition: parent nodes call ExecProcNode() on children to pull tuples

**5. Method Dispatch (Dynamic Function Pointers)**
- `PlanState.ExecProcNode` is a function pointer set by `ExecSetExecProcNode()`
- Avoids large switch statements in hot loop; enables runtime specialization
- ExecProcNodeFirst() wrapper provides one-time initialization without overhead

**6. Query Rewriting (Macro Expansion)**
- QueryRewrite applies stored rules: substituting view definitions, rule actions, etc.
- Expands one input Query into zero or more output Queries
- Preserves queryId for statistics tracking across rewrites

### Component Responsibilities

**Parser (parser.c, scan.l, gram.y)**
- Responsibility: Lexical and syntactic analysis
- Input: SQL string
- Output: List<RawStmt> with no semantic interpretation
- Handles: Tokenization, grammar rules, syntax error reporting

**Semantic Analyzer (analyze.c)**
- Responsibility: Semantic validation and annotated tree construction
- Input: RawStmt
- Output: Query with:
  - OID resolution for tables, columns, functions
  - Type coercion and implicit cast insertion
  - Subquery identification and correlation analysis
  - Aggregate and window function validation
  - Access privilege checking
- Handles: Name resolution, type checking, semantic errors

**Query Rewriter (rewriteHandler.c)**
- Responsibility: Rule application and view expansion
- Input: Query
- Output: List<Query> (possibly expanded)
- Handles: View materialization, INSTEAD rules, trigger rules
- Does NOT change query shape; only substitutes rule actions

**Planner (planner.c, allpaths.c, createplan.c)**
- Responsibility: Query optimization and plan generation
- Input: Query
- Output: PlannedStmt containing:
  - Plan tree (logical execution tree)
  - rtable (range table mapping)
  - resultRelation indices
  - paramExecTypes
- Two-phase approach:
  - Phase 1 (allpaths): Enumerate candidate paths with cost estimates
  - Phase 2 (createplan): Convert selected best path to executable Plan nodes

**Executor (execProcnode.c, execMain.c, node*.c)**
- Responsibility: Runtime query execution
- Input: PlannedStmt
- Output: Tuples via destination receiver (client, INTO, etc.)
- Initialization: ExecInitNode() builds PlanState tree
- Execution: ExecProcNode() implements Volcano pull-based iteration
- Termination: ExecEndNode() releases resources

### Data Flow Description

```
SQL String
    ↓
raw_parser (flex/bison)
    ↓
List<RawStmt> (syntax trees, no semantics)
    ↓
parse_analyze_* (semantic analysis)
    ↓
Query (typed, resolved, validated)
    ↓
QueryRewrite (rule expansion)
    ↓
List<Query> (possibly expanded)
    ↓
subquery_planner (preprocessing & path generation)
    ↓
set_base_rel_sizes, set_rel_pathlist, standard_join_search
    ↓
RelOptInfo tree with Paths (cost-annotated alternative plans)
    ↓
get_cheapest_fractional_path (select best)
    ↓
create_plan (Path → Plan conversion)
    ↓
PlannedStmt (containing Plan tree)
    ↓
ExecutorStart
    ↓
ExecInitNode (Plan tree → PlanState tree)
    ↓
ExecutorRun (main execution loop)
    ↓
ExecProcNode dispatch (Volcano-style pulling)
    ↓
TupleTableSlot stream
    ↓
ExecutorEnd (cleanup)
    ↓
Tuples returned to client
```

### Interface Contracts Between Components

**Parser ↔ Semantic Analyzer**
- Contract: RawStmt nodes have valid syntactic structure; Analyzer resolves identifiers and validates semantics
- Boundary: src/include/nodes/parsenodes.h defines RawStmt structure
- Error handling: Analyzer rejects semantically invalid queries with ereport(ERROR)

**Analyzer ↔ Rewriter**
- Contract: Query nodes are semantically valid; Rewriter expands rules without breaking semantics
- Boundary: src/include/nodes/parsenodes.h defines Query structure
- Error handling: Rewriter validates rule definitions; cyclic views detected

**Rewriter ↔ Planner**
- Contract: Input Queries are rewritten and ready for optimization
- Boundary: src/include/nodes/parsenodes.h (Query) input, src/include/nodes/plannodes.h (PlannedStmt) output
- Error handling: Planner asserts pre-conditions (e.g., active snapshot for user-defined functions)

**Planner ↔ Executor**
- Contract: PlannedStmt is fully self-contained; describes complete execution on all platforms
- Boundary: src/include/executor/execdesc.h (QueryDesc), src/include/nodes/plannodes.h (Plan tree)
- Error handling: Executor validates plan preconditions; detects corrupted plan nodes

## Summary

PostgreSQL implements a sophisticated four-stage query processing pipeline: **parse** (lex/grammar), **analyze** (semantic validation), **rewrite** (rule expansion), **optimize** (plan generation). The planner uses a two-phase approach: **Phase 1** (allpaths.c) enumerates alternative execution paths with cost estimates; **Phase 2** (createplan.c) converts the lowest-cost path into executable Plan nodes. The executor implements the Volcano/iterator model via method dispatch through function pointers in PlanState nodes, allowing each operator type (SeqScan, NestLoop, Agg, Sort, etc.) to implement its own tuple-pulling logic while composing with children recursively. This modular design enables extensibility at every stage via hooks and allows query optimization to be decoupled from execution semantics.
