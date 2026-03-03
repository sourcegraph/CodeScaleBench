# PostgreSQL Query Execution Pipeline: Parse to Execute

## Files Examined

### Traffic Cop & Query Dispatch
- `src/backend/tcop/postgres.c` — Main entry point with `exec_simple_query()`, `pg_parse_query()`, `pg_analyze_and_rewrite_fixedparams()`, `pg_plan_queries()`
- `src/backend/tcop/pquery.c` — Portal execution (`PortalRun()`, `PortalRunSelect()`, `PortalRunMulti()`)

### Parser (Lexer + Grammar)
- `src/backend/parser/parser.c` — Main parser driver with `raw_parser()` function that invokes the lexer (scan.l) and grammar (gram.y)
- `src/backend/parser/gram.y` — Bison grammar specification for SQL
- `src/backend/parser/scan.l` — Flex lexer specification
- `src/backend/parser/scansup.c` — Scanner support utilities

### Semantic Analyzer
- `src/backend/parser/analyze.c` — Main semantic analyzer with `parse_analyze_fixedparams()` and `parse_analyze_varparams()`
- `src/backend/parser/parse_*.c` (multiple files) — Specific analyzers for expressions, clauses, functions, types, relations, aggregates, etc.

### Query Rewriter
- `src/backend/rewrite/rewriteHandler.c` — Main rewrite engine with `QueryRewrite()` function
- `src/backend/rewrite/` — Other rewrite-related modules (rules, security, etc.)

### Optimizer (Planner + Path Generation)
- `src/backend/optimizer/plan/planner.c` — Main planner entry point with `planner()`, `standard_planner()`, `subquery_planner()`, `grouping_planner()`
- `src/backend/optimizer/plan/planmain.c` — Core join planning with `query_planner()` (Phase 1: path generation)
- `src/backend/optimizer/plan/createplan.c` — Plan creation from paths with `create_plan()` (Phase 2: plan generation)
- `src/backend/optimizer/path/allpaths.c` — Path generation for base relations and joins
- `src/backend/optimizer/path/costsize.c` — Cost estimation for paths
- `src/backend/optimizer/path/joinpath.c` — Join path generation
- `src/backend/optimizer/path/indxpath.c` — Index path generation
- `src/backend/optimizer/util/` — Utility functions (equivalence classes, restrictinfo, etc.)

### Executor (Runtime Execution)
- `src/backend/executor/execMain.c` — Executor main interface with `ExecutorStart()`, `ExecutorRun()`, `standard_ExecutorRun()`, `ExecutePlan()`
- `src/backend/executor/execProcnode.c` — Volcano-style dispatch with `ExecInitNode()`, `ExecProcNode()` (function pointers), `ExecEndNode()`
- `src/backend/executor/exec*.c` (multiple files) — Individual executor node implementations (SeqScan, IndexScan, Hash, HashJoin, NestLoop, Aggregate, Sort, etc.)

### Node Type Definitions
- `src/include/nodes/plannodes.h` — Plan node type definitions (Plan, SeqScan, IndexScan, Hash, Join, etc.)
- `src/include/nodes/pathnodes.h` — Path node types (RelOptInfo, Path, JoinPath, etc.)
- `src/include/optimizer/pathnode.h` — Path construction utilities
- `src/include/nodes/nodes.h` — Base node infrastructure

---

## Dependency Chain

### 1. Entry Point
**Function:** `exec_simple_query()` in `src/backend/tcop/postgres.c`

Flow:
```
exec_simple_query(query_string)
```

### 2. Parsing Phase (String → RawStmt)
**Called From:** exec_simple_query()
**Function:** `pg_parse_query()` in `src/backend/tcop/postgres.c`

```c
parsetree_list = pg_parse_query(query_string);
```

**Internal Flow:**
- `pg_parse_query()` calls `raw_parser(query_string, RAW_PARSE_DEFAULT)` in `src/backend/parser/parser.c`
- `raw_parser()` initializes:
  - Flex scanner via `scanner_init()` from `scan.l`
  - Bison parser via `base_yyparse()` from `gram.y`
- Returns **List of RawStmt** nodes
- RawStmt wraps the raw parse tree (SelectStmt, InsertStmt, etc.)

**Data Structure:** `RawStmt` (minimal wrapper around raw statement, only contains location info)

### 3. Semantic Analysis & Rewrite Phase (RawStmt → Query)
**Called From:** exec_simple_query()
**Function:** `pg_analyze_and_rewrite_fixedparams()` in `src/backend/tcop/postgres.c`

```c
querytree_list = pg_analyze_and_rewrite_fixedparams(parsetree, query_string, NULL, 0, NULL);
```

**Subphase 3a: Analysis (RawStmt → Query)**
- Calls `parse_analyze_fixedparams()` in `src/backend/parser/analyze.c`
- Creates ParseState and invokes `transformTopLevelStmt()`
- Traverses raw parse tree and:
  - Validates column references against table schemas
  - Resolves function names and types
  - Builds expression trees with resolved type information
  - Constructs a Query node (cmd_select, CMD_INSERT, etc.)
- Returns **single Query node** with fully resolved expressions

**Subphase 3b: Rewriting (Query → List of Query)**
- Calls `pg_rewrite_query()` in `src/backend/tcop/postgres.c`
- Invokes `QueryRewrite()` in `src/backend/rewrite/rewriteHandler.c` for non-utility statements
- Rewrites based on:
  - Views (INSTEAD rules)
  - RETURNING clauses
  - RLS policies
- Returns **List of Query** nodes (typically one, but can be multiple if rules create additional queries)

**Data Structures:** Query (contains parsed and resolved AST with type information, optimization metadata)

### 4. Planning Phase (Query → PlannedStmt)
**Called From:** exec_simple_query()
**Function:** `pg_plan_queries()` in `src/backend/tcop/postgres.c`

```c
plantree_list = pg_plan_queries(querytree_list, query_string, CURSOR_OPT_PARALLEL_OK, NULL);
```

**Flow for each Query:**
- Calls `pg_plan_query()` in `src/backend/tcop/postgres.c`
- Invokes `planner()` in `src/backend/optimizer/plan/planner.c`
  - Dispatches to `standard_planner()` if no planner hook

**Phase 4a: Initialization & Preparation (in standard_planner)**
- Creates `PlannerGlobal` and `PlannerInfo` structures
- Calls `subquery_planner()` in `src/backend/optimizer/plan/planner.c`
  - Preprocesses expressions
  - Handles subqueries, CTEs, views
  - Calls `grouping_planner()` for upper-level operations (GROUP BY, HAVING, ORDER BY, DISTINCT, LIMIT)

**Phase 4b: Path Generation (Query → Path set, in grouping_planner)**
- Calls `query_planner()` in `src/backend/optimizer/plan/planmain.c`
- **Path generation happens in:**
  - `set_base_rel_pathlists()` in `src/backend/optimizer/path/allpaths.c`
  - Generates all possible access paths for each base relation:
    - Sequential scan paths (SeqScanPath)
    - Index scan paths (via `src/backend/optimizer/path/indxpath.c`)
    - Bitmap index scan paths
  - `make_join_rel()` and `rank_final_joins()` in `src/backend/optimizer/path/joinrels.c`
    - Generates all valid join paths using dynamic programming
    - Calls `make_join_paths()` in `src/backend/optimizer/path/joinpath.c` for each join pair
    - Generates NestLoopPath, HashJoinPath, MergeJoinPath
  - Cost estimation via `src/backend/optimizer/path/costsize.c`
- Returns **RelOptInfo** with list of candidate Paths for each relation
- Finds best path for **output ordering requirements** via `get_cheapest_fractional_path()`
- Calls `create_upper_paths()` in `src/backend/optimizer/plan/planner.c` for aggregation, grouping, window functions, sorting
  - Builds additional paths for upper relations

**Data Structures:**
- `RelOptInfo` — Optimization information for relations (base or derived), contains list of Paths
- `Path` — Abstract plan shape with cost estimates
- Subclasses: `SeqScanPath`, `IndexPath`, `BitmapHeapScanPath`, `NestLoopPath`, `HashJoinPath`, `MergeJoinPath`, `AggPath`, `SortPath`, etc.

**Phase 4c: Plan Creation (Path → Plan, in standard_planner)**
- Calls `create_plan()` in `src/backend/optimizer/plan/createplan.c`
- Recursively converts selected best Path tree to Plan tree:
  - `create_plan_recurse()` dispatches to type-specific creators:
    - `create_seqscan_plan()`, `create_indexscan_plan()`
    - `create_nestloop_plan()`, `create_hashjoin_plan()`, `create_mergejoin_plan()`
    - `create_agg_plan()`, `create_sort_plan()`, etc.
  - Each creator builds corresponding Plan node type and attaches child Plans
- Returns **PlannedStmt** node containing:
  - Root Plan node (tree structure)
  - List of subplans
  - Query metadata (resultRelations, setOperations, etc.)

**Data Structures:**
- `Plan` — Abstract plan node (cost estimates, parallel info, target list)
- Subclasses: `SeqScan`, `IndexScan`, `HashJoin`, `NestLoop`, `Aggregate`, `Sort`, `Limit`, etc.
- `PlannedStmt` — Complete executable plan with metadata

### 5. Execution Phase (PlannedStmt → Result Tuples)
**Called From:** exec_simple_query()
**Portal Creation & Execution:**
```c
portal = CreatePortal("", true, true);
PortalDefineQuery(portal, NULL, query_string, commandTag, plantree_list, NULL);
PortalStart(portal, NULL, 0, InvalidSnapshot);
PortalRun(portal, FETCH_ALL, true, receiver, receiver, &qc);
```

**Flow in PortalRun() (src/backend/tcop/pquery.c):**
- Dispatches based on portal strategy (PORTAL_ONE_SELECT, etc.)
- Calls `ExecutorRun()` in `src/backend/executor/execMain.c`

**Flow in ExecutorRun():**
1. Invokes `standard_ExecutorRun()`
2. Calls `ExecutePlan()` in `src/backend/executor/execMain.c`

**Volcano-Style Iterator Dispatch in ExecutePlan():**
```c
for (;;) {
    slot = ExecProcNode(planstate);  // Dispatch to node type
    if (TupIsNull(slot)) break;
    if (sendTuples) dest->receiveSlot(slot, dest);
}
```

**ExecProcNode Architecture (src/backend/executor/execProcnode.c):**
- **Initialization Phase:** `ExecInitNode()` recursively initializes Plan tree
  - Dispatches via switch on Plan node type:
    - `ExecInitSeqScan()`, `ExecInitIndexScan()`, etc.
  - Each initializer creates corresponding PlanState node
  - Attaches function pointer to `PlanState->ExecProcNode` (e.g., `ExecSeqScan`)
  - Recursively initializes child plans

- **Execution Phase:** `ExecProcNode()` is function pointer to node-specific implementation
  - Called repeatedly during ExecutePlan loop
  - Each node type implements:
    - Tuple fetching (scan, join, aggregate, etc.)
    - Filter application
    - Expression evaluation
    - Child node invocation (for joins/scans with child plans)
  - Examples:
    - `ExecSeqScan()` in `src/backend/executor/nodeSeqscan.c` — fetch from heap table
    - `ExecHashJoin()` in `src/backend/executor/nodeHashjoin.c` — probe hash table, call child plans
    - `ExecAgg()` in `src/backend/executor/nodeAgg.c` — accumulate and return aggregates
    - `ExecSort()` in `src/backend/executor/nodeSort.c` — sort tuples from child plan
  - Returns **TupleTableSlot** (one tuple at a time)

- **Cleanup Phase:** `ExecEndNode()` recursively closes Plan tree
  - Releases resources (file handles, memory, etc.)

**Data Structures:**
- `PlanState` — Runtime state for a Plan node (child states, buffer state, etc.)
- `TupleTableSlot` — Single tuple holding column values
- `EState` — Execution state shared across entire plan (snapshots, relations, output context)

---

## Analysis

### Design Patterns Identified

#### 1. **Two-Phase Optimization**
PostgreSQL optimizer uses a sophisticated two-phase approach:

**Phase 1: Path Generation (allpaths.c)**
- Explores all possible execution strategies independently
- Generates candidate paths for base relations and join pairs
- Evaluates costs but does NOT commit to specific node types
- Benefits: Can compare very different strategies (index vs sequential scan, nested loop vs hash join)
- Complexity: Exponential in number of relations (addressed via GEQO for >12 tables)

**Phase 2: Plan Creation (createplan.c)**
- Selects best path based on cost
- Converts abstract Path to concrete Plan node
- Constructs executable tree with operators, expressions, and resources
- Benefits: Clean separation allows plugging in different cost models or path search strategies

#### 2. **Volcano-Style Iterator Execution Model**
The executor implements the classic Volcano architecture:
- Each plan node type implements an execution iterator: `ExecXxx()` → next tuple
- Parent nodes pull tuples from children (top-down data flow)
- Enables pipelined execution without materializing intermediate results
- Function pointers in PlanState allow dynamic dispatch based on node type
- Compare: Alternative would be push-based (bottom-up) or materialization

#### 3. **Separation of Concerns**
- **Traffic Cop (tcop/)** — Query reception, statement classification
- **Parser** — Syntactic analysis only (no semantic checks)
- **Analyzer** — Semantic validation, type resolution, building Query tree
- **Rewriter** — Rule application (views, RLS)
- **Optimizer** — Path generation and cost-based selection
- **Executor** — Runtime tuple production
- Each stage handles distinct concerns and can be tested/extended independently

#### 4. **Metadata-Driven Node Dispatch**
- Node type stored in `NodeTag` enum (T_SeqScan, T_IndexScan, etc.)
- ExecInitNode uses switch statement on node type to call appropriate initializer
- Result is PlanState with function pointer to execution routine
- Alternative: Virtual methods (C++) or hash table; switch chosen for performance

### Component Responsibilities

| Component | Responsibility |
|-----------|-----------------|
| `exec_simple_query()` | Orchestrates entire pipeline; handles transaction, error recovery |
| `pg_parse_query()` | Invoke lexer/parser; return raw syntax tree |
| `pg_analyze_and_rewrite_fixedparams()` | Semantic validation; rule application; return optimizable Query |
| `pg_plan_queries()` | Invoke planner; return executable PlannedStmt |
| `planner()` / `standard_planner()` | Coordinate optimization phases; manage PlannerGlobal state |
| `subquery_planner()` | Preprocess expressions; handle subqueries; invoke grouping_planner |
| `query_planner()` | Generate all Paths for base relations and joins |
| `grouping_planner()` | Build Paths for upper-level operations (GROUP, ORDER, DISTINCT, etc.) |
| `create_plan()` | Convert selected Path to Plan tree |
| `ExecutorRun()` / `ExecutePlan()` | Loop calling ExecProcNode to fetch tuples |
| `ExecInitNode()` | Build PlanState tree; attach function pointers |
| `ExecProcNode()` | Fetch next tuple from plan node (via function pointer) |
| `ExecEndNode()` | Cleanup plan state |

### Data Flow Description

```
SQL String
    ↓
[Parser: raw_parser()] → RawStmt (syntax tree only)
    ↓
[Analyzer: parse_analyze()] → Query (with type info, semantically valid)
    ↓
[Rewriter: QueryRewrite()] → Query (with rules applied)
    ↓
[Planner Phase 1: query_planner()] → RelOptInfo with Paths (cost estimates)
    ↓
[Path Selection: best_path chosen] → best_path
    ↓
[Planner Phase 2: create_plan()] → PlannedStmt (executable tree)
    ↓
[Executor Init: ExecInitNode()] → PlanState tree (with function pointers)
    ↓
[Executor Run: ExecProcNode() loop] → TupleTableSlot (tuples one at a time)
    ↓
Result to Client
```

### Interface Contracts Between Components

| Stage | Input Type | Output Type | Key Functions |
|-------|-----------|------------|---------------|
| Parser | `const char *query_string` | `List<RawStmt>` | `raw_parser()` |
| Analyzer | `RawStmt` | `Query` | `parse_analyze_fixedparams()` |
| Rewriter | `Query` | `List<Query>` | `QueryRewrite()` |
| Planner Phase 1 | `Query` + PlannerInfo | `RelOptInfo<Path>` | `query_planner()` |
| Planner Phase 2 | `Path` + PlannerInfo | `Plan` | `create_plan()` |
| Planning Output | `List<Query>` | `List<PlannedStmt>` | `pg_plan_queries()` |
| Executor Init | `Plan` + EState | `PlanState` | `ExecInitNode()` |
| Executor Run | `PlanState` | `TupleTableSlot` | `ExecProcNode()` |

### Key Data Structures

1. **RawStmt** — Result of parsing; minimal wrapper (parse tree + location)
2. **Query** — Result of analysis; contains resolved expressions, semantics
3. **Path** — Candidate execution strategy with cost estimates (abstract)
4. **Plan** — Concrete executable node (operator + child plans + expressions)
5. **PlannedStmt** — Complete plan with metadata for execution
6. **PlanState** — Runtime state for a Plan node; contains execution context
7. **TupleTableSlot** — Single row; used for pipeline communication

---

## Summary

PostgreSQL's query execution pipeline is a classic **compiler-like architecture** with clear separation between:
1. **Syntax** (Parser: raw SQL string → RawStmt)
2. **Semantics** (Analyzer: RawStmt → Query; Rewriter: applies rules)
3. **Optimization** (Two-phase: Path generation via allpaths.c, then Plan creation via createplan.c)
4. **Execution** (Volcano-style iterators via ExecProcNode function pointers)

The **two-phase optimization** (Path exploration before Plan commitment) allows sophisticated cost-based decisions, while the **Volcano iterator model** (pull-based, top-down data flow) enables efficient pipelined execution without materializing intermediate results. The architecture is highly modular, allowing extensions (e.g., FDW, custom nodes) at each layer.
