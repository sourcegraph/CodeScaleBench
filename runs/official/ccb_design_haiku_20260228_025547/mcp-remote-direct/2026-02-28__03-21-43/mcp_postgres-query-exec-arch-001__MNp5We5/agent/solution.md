# PostgreSQL Query Execution Pipeline: Architecture Analysis

## Files Examined

### Traffic Cop (Entry Point)
- **src/backend/tcop/postgres.c** — Implements `exec_simple_query()`, the main entry point for simple query execution from protocol handler. Orchestrates the complete pipeline from parsing through execution.

### Parser Subsystem
- **src/backend/tcop/postgres.c:602** — `pg_parse_query()` — Invokes the lexer/parser and returns a list of `RawStmt` nodes
- **src/backend/parser/parser.c:41** — `raw_parser()` — Entry point to the lexer and YACC-generated parser
- **src/backend/parser/scan.l** — Flex-based lexer that tokenizes SQL text
- **src/backend/parser/gram.y** — YACC grammar rules for SQL syntax, generates parser AST

### Semantic Analyzer
- **src/backend/tcop/postgres.c:665** — `pg_analyze_and_rewrite_fixedparams()` — Orchestrates analysis and rewriting
- **src/backend/parser/analyze.c:104** — `parse_analyze_fixedparams()` — Main semantic analysis entry point; calls `transformTopLevelStmt()` to convert `RawStmt` to `Query`
- **src/backend/parser/parse_agg.c, parse_clause.c, parse_expr.c, etc.** — Semantic analysis functions for specific SQL constructs (aggregates, clauses, expressions, function calls, operators, etc.)

### Query Rewriter
- **src/backend/tcop/postgres.c:798** — `pg_rewrite_query()` — Entry point for query rewriting
- **src/backend/rewrite/rewriteHandler.c:4565** — `QueryRewrite()` — Primary rewriter implementation; applies stored rules (views, instead-of triggers) to transform queries

### Optimizer/Planner Subsystem
- **src/backend/tcop/postgres.c:882** — `pg_plan_query()` — Wraps planner invocation for a single query
- **src/backend/tcop/postgres.c:970** — `pg_plan_queries()` — Plans a list of `Query` nodes; returns list of `PlannedStmt` nodes
- **src/backend/optimizer/plan/planner.c:287** — `planner()` — Hook-aware entry point to the planner
- **src/backend/optimizer/plan/planner.c:303** — `standard_planner()` — Core planner implementation; calls `subquery_planner()` for path generation, then selects best path via `get_cheapest_fractional_path()` and calls `create_plan()`
- **src/backend/optimizer/plan/planmain.c** — `subquery_planner()` — Plans a single SELECT, invokes path generation and upper relation planning via `grouping_planner()`
- **src/backend/optimizer/path/allpaths.c** — Path generation module; builds all possible access paths via `make_rel_from_joinlist()`, `make_join_rel()`, adds scan/join paths
- **src/backend/optimizer/plan/createplan.c** — `create_plan()` — Converts best `Path` to executable `Plan` tree

### Executor Subsystem
- **src/backend/tcop/pquery.c:433** — `PortalStart()` — Initializes portal for execution; calls `ExecutorStart()`
- **src/backend/executor/execMain.c:121** — `ExecutorStart()` — Initializes executor state; calls `ExecInitNode()` to build `PlanState` tree
- **src/backend/tcop/pquery.c** — `PortalRun()` — Executes portal; drives tuple fetch loop by repeatedly calling `ExecutorRun()`
- **src/backend/executor/execMain.c** — `ExecutorRun()` — Main execution loop; calls `ExecutePlan()` which repeatedly invokes `ExecProcNode()` on plan root
- **src/backend/executor/execProcnode.c** — Volcano-style executor dispatch:
  - `ExecInitNode()` — Recursively initializes plan tree into `PlanState` tree (line 141)
  - `ExecProcNode()` — Dispatches node execution via function pointers; each node calls `ExecProcNode()` on children for pull-driven evaluation
  - `ExecEndNode()` — Recursively finalizes nodes
- **src/backend/executor/nodeSeqscan.c, nodeIndexscan.c, nodeHashjoin.c, nodeNestloop.c, etc.** — Individual executor node implementations; each implements `ExecInit*()`, `Exec*()`, and `ExecEnd*()` functions

### Node Type Definitions
- **src/include/nodes/parsenodes.h:2081** — `RawStmt` structure; output of parser, contains unparsed statement text + AST node
- **src/include/nodes/parsenodes.h:117** — `Query` structure; output of semantic analyzer; normalized query representation with SELECT/INSERT/UPDATE/DELETE-specific fields
- **src/include/nodes/plannodes.h:46** — `PlannedStmt` structure; output of planner; contains final executable plan tree + metadata
- **src/include/nodes/plannodes.h:158** — `Plan` structure; base class for all plan node types
- **src/include/nodes/pathnodes.h** — `Path` structure hierarchy; used during optimization phase to represent candidate execution paths (SeqScan, IndexScan, HashJoin, etc.)
- **src/include/nodes/execnodes.h** — `PlanState` and related execution state structures; runtime state for each plan node instance

---

## Dependency Chain

### 1. Entry Point
```
exec_simple_query() [postgres.c:1011]
│
├─ Reports query for monitoring (pgstat_report_activity)
├─ Starts transaction (start_xact_command)
│
├─────────────────────────────────────────────────────────────
│  STAGE 1: PARSING
├─────────────────────────────────────────────────────────────
│
└─> pg_parse_query(query_string) [postgres.c:603]
    │
    └─> raw_parser(query_string, RAW_PARSE_DEFAULT) [parser.c:42]
        │
        ├─ Lexical analysis (scan.l) → Tokens
        │
        └─ Syntactic analysis (gram.y) → RawStmt AST
            Returns: List<RawStmt>

    Output: List of RawStmt nodes
    (Each contains unparsed statement text + AST root)
```

### 2. Semantic Analysis & Rewriting (Per RawStmt)
```
For each RawStmt in parsetree_list:
│
├─────────────────────────────────────────────────────────────
│  STAGE 2: SEMANTIC ANALYSIS
├─────────────────────────────────────────────────────────────
│
└─> pg_analyze_and_rewrite_fixedparams(RawStmt, query_string, ...) [postgres.c:665]
    │
    └─> parse_analyze_fixedparams(RawStmt, ...) [analyze.c:105]
        │
        ├─ Create ParseState (pstate) for context
        │
        └─> transformTopLevelStmt(pstate, RawStmt) [parse_node.c]
            │
            ├─> Resolve table/column references
            ├─> Type-check expressions (parse_expr.c)
            ├─> Resolve function calls (parse_func.c)
            ├─> Process aggregates (parse_agg.c)
            ├─> Handle clauses (parse_clause.c)
            ├─> Build final Query structure
            │
            Returns: Query node

    Output: Single Query node

├─────────────────────────────────────────────────────────────
│  STAGE 3: QUERY REWRITING
├─────────────────────────────────────────────────────────────
│
└─> pg_rewrite_query(Query) [postgres.c:798]
    │
    ├─ Check for utility statements → skip rewriting
    │
    └─> QueryRewrite(Query) [rewriteHandler.c:4565]
        │
        ├─ Apply view definitions (expand views in FROM clause)
        ├─ Apply stored rules (CREATE RULE)
        ├─ Apply INSTEAD-OF triggers
        ├─ May expand to multiple Query nodes
        │
        Returns: List<Query>

    Output: List of Query nodes (normalized, rule-rewritten)
```

### 3. Planning & Optimization (Per Query)
```
For each Query in querytree_list:
│
├─────────────────────────────────────────────────────────────
│  STAGE 4A: PLAN GENERATION & PATH ENUMERATION
├─────────────────────────────────────────────────────────────
│
└─> pg_plan_queries(List<Query>, ...) [postgres.c:970]
    │
    └─> For each Query → pg_plan_query(Query, ...) [postgres.c:882]
        │
        └─> planner(Query, query_string, cursorOptions, boundParams) [planner.c:287]
            │
            └─> standard_planner(Query, ...) [planner.c:303]
                │
                ├─ Initialize PlannerGlobal (glob)
                ├─ Assess parallel query feasibility
                │
                └─> subquery_planner(glob, Query, ..., tuple_fraction, ...) [planmain.c]
                    │
                    ├─ Preprocess query expressions
                    ├─ Process CTEs (WITH clauses)
                    ├─ Handle subqueries
                    │
                    └─> grouping_planner(root, tuple_fraction, setops) [planner.c]
                        │
                        ├─ Plan base relations (FROM clause)
                        │
                        ├─> [PATH GENERATION: allpaths.c]
                        │   │
                        │   ├─> set_base_rel_pathlist() for each table
                        │   │   ├─ add_seq_scan_path() → SeqScan paths
                        │   │   ├─ add_index_scan_paths() → Index scan paths
                        │   │   ├─ add_bitmap_scan_paths() → Bitmap index paths
                        │   │
                        │   ├─> add_join_paths() for join combinations
                        │   │   ├─ Nested loop joins
                        │   │   ├─ Hash joins
                        │   │   ├─ Merge joins
                        │   │   ├─ Foreign table access paths (via FDW)
                        │   │
                        │   Output: Path tree with cost estimates
                        │
                        ├─ Process GROUP BY, aggregates, HAVING
                        ├─ Process ORDER BY, DISTINCT
                        ├─ Process LIMIT
                        │
                        └─ Create upper relations (set operations, grouping levels)

                ├─ fetch_upper_rel(root, UPPERREL_FINAL, NULL) [pathnode.c]
                │   → Gets final RelOptInfo with all paths
                │
                └─────────────────────────────────────────────────────────────
                    STAGE 4B: PATH-TO-PLAN CONVERSION
                ─────────────────────────────────────────────────────────────
                │
                ├─> get_cheapest_fractional_path(final_rel, tuple_fraction) [pathnode.c]
                │   → Selects best Path (lowest cost for given tuple fraction)
                │
                └─> create_plan(root, best_path) [createplan.c]
                    │
                    ├─ Recursively convert Path tree to Plan tree
                    ├─ Dispatch based on Path node type
                    │   ├─> create_seqscan_plan() → SeqScan plan node
                    │   ├─> create_indexscan_plan() → IndexScan plan node
                    │   ├─> create_hashjoin_plan() → HashJoin plan node
                    │   ├─> create_nestloop_plan() → NestLoop plan node
                    │   ├─> create_sort_plan() → Sort plan node
                    │   ├─> create_agg_plan() → Aggregate plan node
                    │   ├─> etc. (all node types)
                    │
                    └─ Tree of Plan nodes (executable representation)

                Returns: PlannedStmt (contains plan tree + metadata)

    Output: List of PlannedStmt nodes
```

### 4. Portal Definition & Execution
```
exec_simple_query() continuation:
│
├─> CreatePortal("", true, true) [portal creation]
│
├─> PortalDefineQuery(portal, NULL, query_string, plantree_list, NULL) [pquery.c]
│   └─ Associates PlannedStmt with portal
│
├─────────────────────────────────────────────────────────────
│  STAGE 5: EXECUTION INITIALIZATION
├─────────────────────────────────────────────────────────────
│
├─> PortalStart(portal, NULL, 0, InvalidSnapshot) [pquery.c:433]
│   │
│   └─> ExecutorStart(QueryDesc *queryDesc, eflags) [execMain.c:121]
│       │
│       ├─ Allocate EState (execution state)
│       ├─ Initialize memory contexts
│       │
│       └─> ExecInitNode(Plan *node, EState *estate, eflags) [execProcnode.c:141]
│           │
│           ├─ Dispatch on plan node type (switch statement on NodeTag)
│           │   ├─ ExecInitSeqScan() → opens base relation
│           │   ├─ ExecInitIndexScan() → opens index
│           │   ├─ ExecInitHashJoin() → allocates hash table, recursively inits children
│           │   ├─ ExecInitNestLoop() → recursively inits children
│           │   ├─ ExecInitSort() → initializes sort state
│           │   ├─ ExecInitAgg() → initializes aggregation state
│           │   ├─ etc. (each node type)
│           │
│           ├─ Recursively call ExecInitNode() on child plans
│           │
│           └─ Return PlanState tree (mirrors Plan tree structure)
│
├─────────────────────────────────────────────────────────────
│  STAGE 6: EXECUTION (Tuple Fetching Loop)
├─────────────────────────────────────────────────────────────
│
├─> PortalRun(portal, FETCH_ALL, true, receiver, receiver, &qc) [pquery.c]
│   │
│   └─> ExecutorRun(QueryDesc *queryDesc, ScanDirection direction, uint64 count, bool execute_once) [execMain.c]
│       │
│       └─> ExecutePlan(EState *estate, PlanState *planstate, ...) [execMain.c]
│           │
│           └─ Loop: while not end of scan
│               │
│               ├─> ExecProcNode(PlanState *node) [execProcnode.c]
│               │   │
│               │   ├─ [VOLCANO-STYLE DISPATCH]
│               │   ├─ Call node->ExecProcNode function pointer
│               │   ├─ Dispatch to specific node executor
│               │   │   ├─ ExecSeqScan() → Fetches tuple from heap, applies filter
│               │   │   ├─ ExecIndexScan() → Scans index, fetches matching tuples
│               │   │   ├─ ExecHashJoin() → Builds/probes hash table, joins tuples
│               │   │   │   ├─ For build side: calls ExecProcNode(outerPlan)
│               │   │   │   ├─ For probe side: calls ExecProcNode(innerPlan)
│               │   │   ├─ ExecNestLoop() → Nested loop join
│               │   │   │   ├─ Outer loop: ExecProcNode(outerPlan)
│               │   │   │   ├─ Inner loop: ExecProcNode(innerPlan) for each outer tuple
│               │   │   ├─ ExecSort() → Buffers input, sorts, then returns tuples
│               │   │   │   └─ Calls ExecProcNode(subPlan) until EOF
│               │   │   ├─ ExecAgg() → Accumulates aggregates
│               │   │   │   └─ Calls ExecProcNode(subPlan) to fetch input tuples
│               │   │   ├─ etc. (all 60+ executor node types)
│               │   │
│               │   └─ Returns TupleTableSlot (wraps tuple data)
│               │
│               ├─ Process tuple (apply projections, qualifications if needed)
│               ├─ Send to receiver (network, file, etc.)
│               │
│               └─ Repeat until no more tuples
│
├─> ExecutorFinish(QueryDesc *queryDesc) [execMain.c]
│   └─ Flush any pending output (aggregates, etc.)
│
├─> ExecutorEnd(QueryDesc *queryDesc) [execMain.c]
│   │
│   └─> ExecEndNode(PlanState *node) [execProcnode.c]
│       │
│       ├─ Recursively finalize all nodes
│       ├─ Close relations, indexes, temporary files
│       ├─ Free memory
│       │
│       └─ Dispatch to specific node finalizers (ExecEndSeqScan, etc.)
│
└─ PortalDrop(portal, false)
```

---

## Analysis

### 1. Query Parsing Pipeline
The **parser stage** transforms unstructured SQL text into a structured Abstract Syntax Tree (RawStmt). It employs a two-phase approach:
- **Lexical Analysis (scan.l)**: A Flex-generated lexer tokenizes the input stream, identifying keywords, identifiers, operators, and literals.
- **Syntactic Analysis (gram.y)**: A YACC-generated bottom-up parser applies grammar rules to construct a tree of statement nodes. The parser is generic and produces AST nodes without semantic interpretation (no name resolution, type checking, or validation).

**Key files involved**:
- `src/backend/parser/parser.c` — wrapper function
- `src/backend/parser/scan.l` — lexer
- `src/backend/parser/gram.y` — grammar rules
- Output: `RawStmt` (contains parsed statement node tree)

### 2. Semantic Analysis Phase
The **analyzer stage** transforms the syntactic AST into a logical query tree (Query). It performs:
- **Name Resolution**: Maps table aliases and column references to actual catalog objects (relations, attributes).
- **Type Inference & Coercion**: Determines expression result types, inserts type-casting operations where needed.
- **Function Lookup & Validation**: Resolves function calls to actual functions, validates argument types.
- **Aggregate Processing**: Groups aggregate functions, ensures they appear only in appropriate contexts.
- **Subquery Handling**: Flattens or defers subquery processing based on context.

**Key files involved**:
- `src/backend/parser/analyze.c` — main entry point (`parse_analyze_fixedparams`, `transformTopLevelStmt`)
- `src/backend/parser/parse_*.c` — semantic rules for specific constructs
- Output: `Query` (normalized, semantically validated representation)

### 3. Query Rewriting System
The **rewriter stage** applies user-defined rules and view definitions to transform queries before planning. It:
- **Expands Views**: Replaces view references in FROM clause with the view's definition.
- **Applies Rules**: Substitutes rules defined via `CREATE RULE`, enabling powerful query transformations (e.g., security policies, materialized view maintenance).
- **Applies Triggers**: Processes `INSTEAD OF` triggers on views.
- **May expand to multiple queries**: A single query can be rewritten into multiple queries (e.g., cascading deletes via rules).

**Key files involved**:
- `src/backend/rewrite/rewriteHandler.c` — `QueryRewrite()` function
- Output: `List<Query>` (potentially expanded)

### 4. Two-Phase Optimization (Path Generation & Plan Creation)

The **optimizer stage** is split into two distinct phases:

#### Phase 1: Path Generation (allpaths.c)
The path enumeration phase generates multiple candidate execution paths, each representing a different way to execute the query. For each relation in the FROM clause, it generates:
- **Base scan paths**: SeqScan, IndexScan, BitmapIndexScan (for single-relation access patterns)
- **Multi-relation paths**: Join paths combining different relations (NestedLoop, HashJoin, MergeJoin)
- **Upper-level paths**: For GROUP BY, ORDER BY, aggregates, limits

Each path has a cost model (estimated CPU and I/O cost). The system explores join orders (via dynamic programming in `make_rel_from_joinlist`) and join methods.

**Key files**:
- `src/backend/optimizer/path/allpaths.c` — path generation functions
- `src/backend/optimizer/path/*.c` — join algorithm implementations (costsize.c estimates costs)
- Output: `RelOptInfo` with list of `Path` candidates (each with estimated cost)

#### Phase 2: Plan Creation (createplan.c)
The plan generation phase converts the best `Path` (selected via `get_cheapest_fractional_path`) into an executable `Plan` tree. This involves:
- **Recursive conversion**: Each `Path` is converted to a corresponding `Plan` node type.
- **Compilation of expressions**: Filter conditions and projections are compiled into executable form.
- **Memory management**: Decisions about buffer/materialization strategies.
- **Parallel operator setup**: If applicable, inserts Gather/GatherMerge nodes for parallel execution.

**Key files**:
- `src/backend/optimizer/plan/createplan.c` — `create_plan()` function
- Output: `PlannedStmt` (containing root `Plan` node + metadata)

### 5. Portal-Based Execution Framework
Execution is **portal-based**, providing abstraction for multiple execution models:
- **Simple execution**: Execute to completion.
- **Cursor-like execution**: Fetch tuples incrementally via `FETCH` commands.
- **Prepared statement caching**: Reuse plans across multiple executions.

The portal holds the plan, stores execution state between fetches, and manages result set cursors.

**Key functions**:
- `PortalStart()` — Initializes portal execution; calls `ExecutorStart()`
- `PortalRun()` — Drives execution loop; calls `ExecutorRun()` repeatedly
- Output: Tuples sent to receiver (network, file, output format specified)

### 6. Volcano-Style Executor Architecture
The **executor** implements a **pull-based, tuple-at-a-time model** (Volcano/Cascades architecture):

**Three-phase execution per plan node**:
1. **Initialization Phase** (`ExecInitNode`)
   - Allocates node-specific state (e.g., hash table for joins, sort state for sorts).
   - Recursively initializes child plan nodes.
   - Opens base relations and indexes as needed.
   - Returns a `PlanState` tree mirroring the `Plan` tree.

2. **Execution Phase** (`ExecProcNode` → node-specific `Exec*` function)
   - Called repeatedly by parent node to fetch next tuple.
   - **Pull-based semantics**: Child nodes called to fetch input, not pushed by parents.
   - Returns a `TupleTableSlot` wrapping the next result tuple (or NULL if exhausted).
   - **Node-specific logic**:
     - **Scan nodes** (SeqScan, IndexScan): Fetch from storage layer, apply filters.
     - **Join nodes** (HashJoin, NestLoop, MergeJoin): Combine tuples from left/right children.
     - **Aggregate nodes** (Agg, GroupAggregate): Accumulate state, emit group results.
     - **Sort nodes** (Sort, IncrementalSort): Buffer input, sort in-memory or on disk, return sorted stream.
     - **Limit nodes** (Limit): Count output tuples, stop after N.

3. **Finalization Phase** (`ExecEndNode`)
   - Cleans up node-specific state.
   - Closes relations and indexes.
   - Frees memory.
   - Recursively finalizes child nodes.

**Dispatcher mechanism** (execProcnode.c):
- Each `PlanState` holds a function pointer to its executor function.
- `ExecProcNode()` calls this pointer, dispatching to the correct implementation.
- Enables polymorphic node execution without explicit type checks.

**Key files**:
- `src/backend/executor/execProcnode.c` — Dispatcher framework and state initialization
- `src/backend/executor/execMain.c` — Main ExecutorStart/Run/Finish/End loop
- `src/backend/executor/node*.c` — 60+ individual node implementations

### 7. Data Structures & Type Hierarchy

**Core node types used in the pipeline**:
- **RawStmt** (parsenodes.h): Parser output; minimal semantics, unvalidated names/types.
- **Query** (parsenodes.h): Analyzer output; full semantics, catalog-resolved names, type-checked expressions.
- **RelOptInfo / Path** (pathnodes.h): Optimizer internal; represents candidate access plans with cost estimates.
- **Plan / PlanState** (plannodes.h / execnodes.h): Planner output; executable plan tree and runtime state.
- **TupleTableSlot** (execnodes.h): Executor runtime; holds tuple data and attribute information during execution.

**Node type dispatch**:
- `NodeTag` enum field in every node allows polymorphic dispatching.
- `ExecInitNode`, `ExecProcNode`, `ExecEndNode` use switch statements on `NodeTag` to call appropriate handlers.

---

## Summary

PostgreSQL's query execution pipeline follows a **traditional compiler architecture**:
1. **Parser** (scan.l + gram.y) → `RawStmt` (syntactic AST)
2. **Semantic Analyzer** (analyze.c) → `Query` (normalized logical tree)
3. **Rewriter** (rewriteHandler.c) → `Query` (rule-rewritten)
4. **Optimizer** (planner.c + allpaths.c + createplan.c) → `PlannedStmt` (executable plan)
5. **Executor** (execMain.c + execProcnode.c + node*.c) → tuple stream (results)

The optimizer uses a **two-phase approach**: Path enumeration via dynamic programming (exploring join orders and methods) followed by cost-based selection and plan compilation. The executor implements the **Volcano tuple-at-a-time pull-based model**, where each plan node processes input from children on-demand, enabling efficient streaming and late materialization. This architecture provides extensibility (custom nodes, FDWs, parallel execution) while maintaining predictable execution semantics.
