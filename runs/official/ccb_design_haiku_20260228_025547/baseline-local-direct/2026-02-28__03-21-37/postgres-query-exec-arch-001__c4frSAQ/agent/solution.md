# PostgreSQL Query Execution Pipeline: From Parse to Execute

## Files Examined

### Traffic Cop (Query Entry Point)
- **src/backend/tcop/postgres.c** — Entry point for simple query processing; implements `exec_simple_query()` which orchestrates the entire pipeline from parsing through execution

### Parser (Lexer + Grammar)
- **src/backend/parser/parser.c** — Implements `raw_parser()` which initializes lexer (via `scanner_init()`) and Bison parser (via `base_yyparse()`) to produce `RawStmt` nodes
- **src/backend/parser/gram.y** — Bison grammar definition for SQL syntax (compiled to gram.c)
- **src/backend/parser/scan.l** — Flex lexer definition for tokenization (compiled to scan.c)

### Semantic Analysis
- **src/backend/parser/analyze.c** — Implements semantic analysis layer: `parse_analyze_fixedparams()`, `parse_analyze_varparams()`, `parse_analyze_withcb()` all call `transformTopLevelStmt()` to convert `RawStmt` → `Query`

### Query Rewriter
- **src/backend/rewrite/rewriteMain.c** — Main rewrite dispatcher
- **src/backend/rewrite/rewriteSupport.c** — Support functions for rewriting
- **src/backend/rewrite/locks.c** — Lock information handling
- Called via `pg_rewrite_query()` in postgres.c which invokes `QueryRewrite()` to apply view expansion, rule rewriting, and trigger handling on `Query` nodes

### Optimizer/Planner
- **src/backend/optimizer/plan/planner.c** — Main planner entry point
  - `planner()` — dispatcher that calls `standard_planner()`
  - `standard_planner()` — orchestrates the two-phase optimization:
    1. Phase 1: Calls `subquery_planner()` then `grouping_planner()` for path generation
    2. Phase 2: Calls `create_plan()` to convert selected path to `PlannedStmt`
  - `subquery_planner()` — recursively processes Query with preprocessing (subquery pullup, flattening, expression preprocessing)
  - `grouping_planner()` — handles grouping, aggregation, window functions, and calls `query_planner()`

- **src/backend/optimizer/plan/planmain.c** — Core join planning
  - `query_planner()` — generates `RelOptInfo` with multiple paths for basic SELECT/FROM/WHERE/JOIN

- **src/backend/optimizer/plan/createplan.c** — Phase 2: Path → Plan conversion
  - `create_plan()` — converts best `Path` tree to `Plan` tree (e.g., SeqScanPath → SeqScan, NestLoopPath → NestLoop)
  - Node-specific functions: `create_seqscan_plan()`, `create_nestloop_plan()`, etc.

- **src/backend/optimizer/path/allpaths.c** — Phase 1: Path generation for joins
  - `make_one_rel()` — generates all possible access paths:
    - `set_base_rel_pathlists()` — generates paths for individual tables (SeqScan, IndexScan, etc.)
    - `make_rel_from_joinlist()` — generates join paths using dynamic programming

- **src/backend/optimizer/path/pathnode.c** — Path node allocation and manipulation
- **src/backend/optimizer/path/costfuncs.c** — Cost estimation for different paths

### Node Definitions
- **src/include/nodes/plannodes.h** — Plan node type definitions: `Plan`, `SeqScan`, `IndexScan`, `NestLoop`, `HashJoin`, `Aggregate`, `Sort`, `PlannedStmt`, etc.
- **src/include/nodes/parsenodes.h** — Parse tree node definitions: `Query`, `RawStmt`, `SelectStmt`, `FromClause`, `Expr`, etc.
- **src/include/nodes/execnodes.h** — Executor state node definitions: `PlanState`, `ScanState`, `JoinState`, `TupleTableSlot`, etc.
- **src/include/nodes/nodes.h** — Node type enumeration and macros

### Executor (Tuple-by-Tuple Processing)
- **src/backend/executor/execMain.c** — Main executor entry points
  - `ExecutorStart()` — initializes executor state and plan tree
  - `ExecutorRun()` — drives execution with repeated calls to `ExecProcNode()`
  - `ExecutorEnd()` — cleanup

- **src/backend/executor/execProcnode.c** — Volcano-style dispatch mechanism
  - `ExecInitNode()` — Dispatch: Plan node type → node-specific init function (ExecInitSeqScan, ExecInitNestLoop, etc.)
  - `ExecProcNode()` — Dispatch: PlanState node type → node-specific tuple-fetching function (ExecSeqScan, ExecNestLoop, etc.)
  - `ExecEndNode()` — Dispatch: PlanState node type → node-specific cleanup function
  - `MultiExecProcNode()` — Dispatch for nodes returning complex structures (Hash, Bitmap, etc.)

- **src/backend/executor/nodeSeqscan.c** — Sequential scan node executor
- **src/backend/executor/nodeIndexscan.c** — Index scan node executor
- **src/backend/executor/nodeNestloop.c** — Nested loop join executor
- **src/backend/executor/nodeHashjoin.c** — Hash join executor
- **src/backend/executor/nodeBitmapHeapscan.c** — Bitmap heap scan executor
- **src/backend/executor/nodeAgg.c** — Aggregation executor
- **src/backend/executor/nodeSort.c** — Sort executor
- **src/backend/executor/nodeLimit.c** — Limit/Offset executor
- **src/backend/executor/nodeHash.c** — Hash table construction executor

### Portal & Query Descriptor
- **src/backend/utils/mmgr/portalmem.c** — Portal memory context and definition
- **src/backend/tcop/pquery.c** — Implements `PortalStart()` which calls `ExecutorStart()`; `PortalRun()` which calls `ExecutorRun()`

---

## Dependency Chain

### 1. Entry Point: `exec_simple_query()` (postgres.c:1011)
```
exec_simple_query(query_string)
```
**Role**: Traffic cop function that receives raw SQL string and orchestrates entire pipeline

### 2. Parsing Stage: `pg_parse_query()` (postgres.c:603)
```
exec_simple_query()
  ↓
pg_parse_query(query_string)           [postgres.c:603]
  ↓
raw_parser(query_string, mode)         [parser/parser.c:42]
  ├→ scanner_init() [calls flex lexer, scan.l]
  ├→ parser_init()
  ├→ base_yyparse() [calls bison parser, gram.y]
  └→ scanner_finish()

Returns: List<RawStmt>
```
**Data transformation**: SQL string → List of `RawStmt` nodes (untyped, minimal semantic checking)
**Design pattern**: Two-pass lexing/parsing via Flex/Bison

### 3. Semantic Analysis + Rewriting: `pg_analyze_and_rewrite_fixedparams()` (postgres.c:665)
```
For each RawStmt:
  ↓
pg_analyze_and_rewrite_fixedparams(RawStmt, ...)     [postgres.c:665]
  ├→ parse_analyze_fixedparams(RawStmt, ...)         [parser/analyze.c:105]
  │   ├→ make_parsestate()
  │   ├→ transformTopLevelStmt(pstate, RawStmt)     [analyzer: validate types, names, references]
  │   └→ free_parsestate()
  │
  └→ pg_rewrite_query(Query)                         [postgres.c:798]
      └→ QueryRewrite(Query)                         [rewrite/rewriteMain.c]
          [Apply rules, view expansion, trigger handling]

Returns: List<Query> (typically one Query per RawStmt, but rules may expand)
```
**Data transformation**: `RawStmt` → `Query` (typed, semantic info attached: table/column references, expression types, quals, targetlist)
**Design pattern**: Single-pass semantic analysis followed by rewrite rules

### 4. Planning Stage Part 1 - Path Generation: `pg_plan_queries()` (postgres.c:970)
```
For each Query:
  ↓
pg_plan_queries(List<Query>, ...)                    [postgres.c:970]
  └→ For each Query:
      ├→ [If CMD_UTILITY: wrap in PlannedStmt]
      └→ pg_plan_query(Query, ...)                   [postgres.c:882]
          └→ planner(Query, ...)                     [optimizer/plan/planner.c:287]
              └→ standard_planner(Query, ...)        [optimizer/plan/planner.c:303]
                  ├→ [Initialize planner state: PlannerGlobal, PlannerInfo]
                  ├→ subquery_planner(glob, Query, ...)  [optimizer/plan/planner.c:651]
                  │   ├→ [Preprocessing: subquery pullup, expression simplification]
                  │   ├→ grouping_planner(root, ...)    [optimizer/plan/planner.c:1434]
                  │   │   ├→ [For regular SELECT]:
                  │   │   ├→ query_planner(root, callback, extra)  [optimizer/plan/planmain.c:54]
                  │   │   │   ├→ setup_simple_rel_arrays(root)
                  │   │   │   ├→ add_base_rels_to_query(root, jointree)
                  │   │   │   ├→ build_base_rel_tlists(root, targetlist)
                  │   │   │   ├→ deconstruct_jointree(root) → joinlist
                  │   │   │   ├→ make_one_rel(root, joinlist)  [optimizer/path/allpaths.c:171]
                  │   │   │   │   ├→ set_base_rel_sizes(root)      [compute size estimates]
                  │   │   │   │   ├→ set_base_rel_pathlists(root)   [generate paths for base relations]
                  │   │   │   │   │   └→ For each base rel:
                  │   │   │   │   │       ├→ create_seqscan_path()
                  │   │   │   │   │       ├→ create_index_paths()
                  │   │   │   │   │       └→ ... other access methods
                  │   │   │   │   └→ make_rel_from_joinlist(root, joinlist)  [dynamic programming join planning]
                  │   │   │   │       └→ For each join level:
                  │   │   │   │           ├→ try_nestloop_path()
                  │   │   │   │           ├→ try_hashjoin_path()
                  │   │   │   │           ├→ try_mergejoin_path()
                  │   │   │   │           └→ add_path(rel, path)  [keep cheapest paths via cost model]
                  │   │   │   └→ Returns: RelOptInfo with cheapest_total_path, etc.
                  │   │   │
                  │   │   ├→ [Grouping/Aggregate planning]
                  │   │   ├→ [Window function planning]
                  │   │   └→ [Sorting planning]
                  │   │
                  │   └→ Returns: RelOptInfo (represents final path set)
                  │
                  ├→ fetch_upper_rel(root, UPPERREL_FINAL, NULL)  → final_rel with all paths
                  ├→ get_cheapest_fractional_path(final_rel, tuple_fraction)  → best_path
                  │   [Cost-based selection: chooses cheapest Path]
                  │
                  └─→ PHASE 2 BEGINS HERE:
                      create_plan(root, best_path)  [optimizer/plan/createplan.c]
                          ├→ switch (pathtype):
                          │   ├→ T_SeqScanPath → create_seqscan_plan(root, path)
                          │   ├→ T_IndexPath → create_indexscan_plan(root, path)
                          │   ├→ T_NestPath → create_nestloop_plan(root, path)
                          │   ├→ T_HashPath → create_hashjoin_plan(root, path)
                          │   └→ ... [recursive call for subpaths]
                          └→ Returns: Plan tree (SeqScan, IndexScan, NestLoop, HashJoin, etc.)

Returns: PlannedStmt (contains top Plan node, rtable, param info, etc.)
```
**Data transformation**: `Query` → `RelOptInfo` (Phase 1) → `PlannedStmt` (Phase 2)
**Design pattern**:
- Two-phase optimization: Path generation (explores alternatives), then Plan selection (converts best path)
- Cost-based optimization: Path selection via `cost_seqscan()`, `cost_index()`, `cost_nestloop()`, etc.
- Dynamic programming for join planning: `make_rel_from_joinlist()` systematically explores join orders

### 5. Portal Creation & Execution Initialization: `PortalStart()` (pquery.c)
```
exec_simple_query()
  ├→ CreatePortal()
  ├→ PortalDefineQuery(portal, ..., plantree_list, ...)
  └→ PortalStart(portal, params, cursorOptions, snapshot)
      └→ ExecutorStart(queryDesc, eflags)  [executor/execMain.c:122]
          └→ InitPlan(queryDesc)
              └→ ExecInitNode(Plan, estate, eflags)  [executor/execProcnode.c:142]
                  ├→ switch (nodeTag(plan)):
                  │   ├→ T_SeqScan → ExecInitSeqScan(SeqScan, estate, eflags)
                  │   ├→ T_IndexScan → ExecInitIndexScan(IndexScan, estate, eflags)
                  │   ├→ T_NestLoop → ExecInitNestLoop(NestLoop, estate, eflags)
                  │   └→ ... [recursive call to initialize subplans]
                  └→ Returns: PlanState tree (SeqScanState, IndexScanState, NestLoopState, etc.)

PlanState tree structure mirrors Plan tree structure; includes runtime state (current tuple buffer, index cursors, join state, etc.)
```
**Data transformation**: `PlannedStmt` → `PlanState` tree (runtime execution state)
**Design pattern**: Volcano iterator model initialization; each Plan node has corresponding PlanState

### 6. Tuple-by-Tuple Execution: `PortalRun()` (pquery.c)
```
PortalRun(portal, rows, direction, dest)
  └→ ExecutorRun(queryDesc, direction, rows)  [executor/execMain.c:297]
      └→ ExecutePlan(estate, planstate, direction, rows, ...)
          └→ while (!tuplestorestate_is_empty()):
              └→ ExecProcNode(planstate)  [executor/execProcnode.c]
                  ├→ First call: ExecProcNodeFirst(node)
                  │   ├→ check_stack_depth()
                  │   ├→ if (instrumentation):
                  │   │   node->ExecProcNode = ExecProcNodeInstr
                  │   └→ else:
                  │       node->ExecProcNode = node->ExecProcNodeReal
                  │   └→ return node->ExecProcNode(node)
                  │
                  └→ Subsequent calls: node->ExecProcNode(node)  [points to ExecProcNodeReal or ExecProcNodeInstr]
                      ├→ switch (nodeTag(planstate)):
                      │   ├→ T_SeqScanState → ExecSeqScan(SeqScanState)
                      │   ├→ T_IndexScanState → ExecIndexScan(IndexScanState)
                      │   ├→ T_NestLoopState → ExecNestLoop(NestLoopState)
                      │   │   └→ while (more tuples from outer):
                      │   │       └→ ExecProcNode(inner_planstate)  [recursive call to child]
                      │   └→ ... [all node types]
                      │
                      └→ Returns: TupleTableSlot (current tuple or NULL when done)

For all tuples:
  └→ Send to destination (client, file, tuplestore, etc.)
```
**Data transformation**: `PlanState` (runtime state) → `TupleTableSlot` (individual tuples) → destination
**Design pattern**: Volcano-style pull-based iterator model; recursive dispatch based on node type

### 7. Executor Cleanup: `ExecutorEnd()` (execMain.c)
```
After execution completes:
  └→ ExecutorEnd(queryDesc)
      └→ ExecEndNode(planstate)  [executor/execProcnode.c]
          ├→ switch (nodeTag(planstate)):
          │   ├→ T_SeqScanState → ExecEndSeqScan(SeqScanState)
          │   ├→ T_NestLoopState → ExecEndNestLoop(NestLoopState)
          │   │   └→ ExecEndNode(inner_planstate)  [recursive cleanup]
          │   └→ ... [all node types]
          └→ [Free resources, close file handles, etc.]
```

---

## Analysis

### Design Patterns Identified

#### 1. **Dispatcher Pattern**
Multiple dispatcher functions route control flow to node-specific implementations:
- **`ExecInitNode(Plan → Plan code)`** — dispatches to `ExecInit<NodeType>()`
  - `T_SeqScan` → `ExecInitSeqScan()`, `T_IndexScan` → `ExecInitIndexScan()`, etc.
  - **Responsibility**: Convert Plan into PlanState, allocate runtime structures

- **`ExecProcNode(PlanState → tuple code)`** — dispatches to node-specific execution function
  - Points to either `ExecSeqScan()`, `ExecNestLoop()`, `ExecHashJoin()`, etc.
  - **Responsibility**: Fetch next tuple from this node
  - **Optimization**: First call sets up dispatcher to avoid overhead on subsequent calls

- **`ExecEndNode(PlanState → cleanup code)`** — dispatches to `ExecEnd<NodeType>()`
  - **Responsibility**: Free node-specific resources

#### 2. **Pull-Based Iterator (Volcano Model)**
- **Each PlanState is an iterator** that fetches one tuple at a time via `ExecProcNode()`
- **Parent calls child**: NestLoop calls SeqScan to get next outer tuple, then calls inner join to find matches
- **Lazy evaluation**: Tuples flow upward only when demanded by parent node
- **Stateful execution**: Each PlanState maintains: current tuple buffer, scan position, join state, filter expressions

#### 3. **Two-Phase Optimization**
- **Phase 1 - Path Generation** (`allpaths.c`): Explores multiple execution strategies
  - `set_base_rel_pathlists()` — SeqScan, IndexScan, BitmapScan alternatives for each table
  - `make_rel_from_joinlist()` — all valid join orders and join methods (NestLoop, HashJoin, MergeJoin)
  - **Result**: RelOptInfo with multiple Paths, each with estimated cost

- **Phase 2 - Plan Selection & Conversion** (`createplan.c`): Picks best path and converts to executable plan
  - `get_cheapest_fractional_path()` — selects minimum-cost path using cost model
  - `create_plan()` — transforms chosen Path into executable Plan tree
  - **Result**: Single, optimized Plan tree ready for executor

#### 4. **Extensibility via Hooks**
- `planner_hook` — allows custom planner implementation
- `ExecutorStart_hook`, `ExecutorRun_hook`, `ExecutorEnd_hook` — allow custom executor behavior
- `post_parse_analyze_hook` — allows plugins to inspect/modify Query after analysis

#### 5. **Memory Management via Contexts**
- **MessageContext** — temporary storage for parsing/planning (reset after each query)
- **PlannerContext** — planner-specific allocations
- **ExecutorContext** — per-tuple allocations (reset for each tuple to avoid bloat)
- Per-parsetree contexts allow freeing intermediate results early

### Component Responsibilities

#### Traffic Cop (postgres.c)
- **Responsibility**: Orchestrate pipeline; enforce transaction semantics; handle errors/logging
- **Inputs**: Raw SQL string, protocol parameters
- **Outputs**: Query results sent to client
- **Key functions**:
  - `exec_simple_query()` — handles simple "Q" protocol messages
  - `exec_parse_message()`, `exec_bind_message()`, `exec_execute_message()` — handle extended protocol

#### Parser (parser.c, scan.l, gram.y)
- **Responsibility**: Tokenize SQL string; parse according to SQL grammar; produce untyped AST
- **Input**: SQL string
- **Output**: List of RawStmt nodes (no validation)
- **Separation of concerns**: Lexer (scan.l) handles tokenization, Bison grammar (gram.y) handles syntax

#### Analyzer (analyze.c)
- **Responsibility**: Semantic analysis; validate identifiers; infer types; resolve ambiguities
- **Input**: RawStmt (from parser)
- **Output**: Query with semantic info attached (table/column references, expression types, estimated cost hints)
- **Key transformations**:
  - Name resolution: `a.x` → resolved to TableAlias.Column
  - Type inference: literal `1` inferred as INT4
  - Reference tracking: which tables/columns are actually used

#### Rewriter (rewriteMain.c)
- **Responsibility**: Apply stored rules; expand views; handle INSTEAD rules
- **Input**: Query
- **Output**: Modified Query (often expanded to multiple Query nodes)
- **Example**: `SELECT * FROM my_view` → expanded to underlying table query with view WHERE clauses

#### Optimizer (planner.c, planmain.c, allpaths.c, createplan.c)
- **Phase 1 Responsibility**: Generate alternative execution paths; estimate costs
  - `make_one_rel()` calls `set_base_rel_pathlists()` (access method alternatives) + `make_rel_from_joinlist()` (join order alternatives)
  - Cost estimation: `cost_seqscan()`, `cost_index()`, `cost_nestloop()`, etc. compute startup cost + total cost
  - Result: RelOptInfo with multiple Paths, each with cost estimates

- **Phase 2 Responsibility**: Select cheapest path; convert to Plan
  - Cost comparison: `get_cheapest_fractional_path()` selects Path with lowest cost
  - Path → Plan conversion: `create_plan()` transforms Path tree to Plan tree
  - Plan optimization: `set_plan_references()` handles Var renumbering, plan flattening
  - Result: Single, optimized Plan ready for execution

#### Executor (execMain.c, execProcnode.c, node*.c)
- **Initialization Responsibility** (ExecStart): Convert Plan → PlanState
  - `ExecInitNode()` recursively initializes plan tree
  - Each node initializes: scan position, expression state, subplan state, etc.

- **Execution Responsibility** (ExecRun): Fetch tuples via pull-based iteration
  - `ExecProcNode()` calls appropriate node-specific function
  - Each node type implements: `ExecSeqScan()`, `ExecNestLoop()`, `ExecHashJoin()`, etc.
  - Nodes implement: table/index scans, joins, aggregation, sorting, etc.

- **Finalization Responsibility** (ExecEnd): Cleanup resources
  - `ExecEndNode()` recursively cleans up resources
  - Close file handles, free hash tables, etc.

### Data Flow Description

```
SQL String
    ↓
[Parser: Lex + Parse]
    ↓
RawStmt (untyped AST)
    ↓
[Analyzer: Semantic validation]
    ↓
Query (typed AST, semantic info)
    ↓
[Rewriter: Rule application]
    ↓
Query (possibly expanded)
    ↓
[Planner Phase 1: Path generation]
    ↓
RelOptInfo (with multiple Paths, cost estimates)
    ↓
[Planner Phase 2: Path selection & conversion]
    ↓
PlannedStmt (optimized Plan tree)
    ↓
[Executor Init: Plan → PlanState]
    ↓
PlanState tree (runtime state)
    ↓
[Executor Run: Pull-based iteration]
    ↓
TupleTableSlot (tuples)
    ↓
[Output: Client/file/tuplestore]
    ↓
Results
```

### Interface Contracts Between Components

#### Parser → Analyzer
- **Input contract**: RawStmt with all fields populated (statement type, name lists, expressions)
- **Output contract**: Query with:
  - `rtable` (RangeTblEntry list) — indexed by table references
  - `targetList` — typed expressions with column info
  - `qual` — type-checked WHERE clause
  - `hasAggs`, `hasGrouping`, `hasWindowFuncs` — flags for planning

#### Analyzer → Rewriter
- **Input contract**: Query with semantic info attached
- **Output contract**: Query (possibly multiple after rule expansion) with same semantic structure

#### Rewriter → Planner
- **Input contract**: Query ready for optimization (no further rewriting)
- **Output contract**: PlannedStmt with:
  - `plan` — executable Plan tree
  - `rtable` — finalized RangeTblEntry list
  - `paramExecTypes` — runtime parameter types

#### Planner → Executor
- **Input contract**: PlannedStmt with all Plan nodes populated
- **Output contract**: Queryable via ExecProcNode calls:
  - Each node produces TupleTableSlot
  - NULL slot indicates end of result set

#### Executor → Output
- **Input contract**: TupleTableSlot objects from ExecProcNode
- **Output contract**: Serialized tuples sent to destination (client, file, tuplestore)

---

## Summary

PostgreSQL's query execution pipeline implements a **classic multi-stage compiler model**: parse (lexer+grammar) → analyze (semantic checking) → rewrite (rule application) → optimize (two-phase: path generation + plan selection) → execute (Volcano-style pull-based iteration).

The **two-phase optimizer** separates exploration (allpaths.c generates alternatives) from exploitation (createplan.c converts best path to plan), enabling cost-based selection without committing to an execution strategy early. The **Volcano executor** implements pull-based iteration where each PlanState node is an independent iterator fetching tuples on demand, allowing natural expression of nested-loop joins, pipelined aggregation, and other streaming operations. **Dispatcher-based dispatch** in ExecInitNode/ExecProcNode/ExecEndNode provides extensibility: new node types require implementing three functions without modifying the dispatchers.

