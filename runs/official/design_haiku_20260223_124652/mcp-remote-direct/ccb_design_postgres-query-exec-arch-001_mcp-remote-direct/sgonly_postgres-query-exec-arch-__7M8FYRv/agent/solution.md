# PostgreSQL Query Execution Pipeline Analysis

## Files Examined

### Traffic Cop / Entry Point
- **src/backend/tcop/postgres.c** — Main traffic cop handling query protocol messages, containing `exec_simple_query()` which orchestrates the entire pipeline; also contains `pg_parse_query()`, `pg_analyze_and_rewrite_fixedparams()`, and `pg_plan_queries()` wrapper functions
- **src/backend/tcop/pquery.c** — Portal management and query execution driver; implements `CreateQueryDesc()`, `ProcessQuery()`, and `PortalRun()` which bridges planning and execution

### Parser (Lexer & Grammar)
- **src/backend/parser/parser.c** — Main entry point for parsing that calls the lexer/parser machinery
- **src/backend/parser/scan.l** — Lexer (scanner) definition in flex format; tokenizes SQL input
- **src/backend/parser/gram.y** — YACC/Bison grammar definition; parses token stream into RawStmt nodes
- **src/backend/parser/gramparse.h** — Parser header with common definitions
- **src/backend/parser/scansup.c** — Scanner support functions

### Semantic Analyzer
- **src/backend/parser/analyze.c** — Semantic analysis driver; implements `parse_analyze_fixedparams()` which transforms RawStmt into Query nodes; handles statement classification, target list processing, relation scanning, and type checking
- **src/backend/parser/parse_*.c** — Specialized analysis modules:
  - `parse_clause.c` — Processes FROM, WHERE, GROUP BY, HAVING, ORDER BY, LIMIT
  - `parse_expr.c` — Expression analysis (operators, functions, coercions)
  - `parse_agg.c` — Aggregate function analysis
  - `parse_cte.c` — Common table expression (CTE) analysis
  - `parse_relation.c` — Table and relation reference handling
  - `parse_target.c` — Target list processing
  - `parse_func.c` — Function call analysis and resolution

### Query Rewriter
- **src/backend/rewrite/rewriteHandler.c** — Main rewriter implementation; `QueryRewrite()` applies view expansion, security barriers, and rule transformations; produces 0..n Query nodes per input
- **src/backend/rewrite/rewriteManip.c** — Utility functions for query tree manipulation
- **src/backend/rewrite/rewriteSupport.c** — Support functions for rule handling
- **src/backend/rewrite/rowsecurity.c** — Row-level security policy enforcement

### Planner/Optimizer
- **src/backend/optimizer/plan/planner.c** — Main entry point; implements:
  - `planner()` — Hook dispatch
  - `standard_planner()` — Standard planning logic; initializes PlannerGlobal and PlannerInfo; orchestrates path and plan generation
  - `pg_plan_query()` — Wrapper that calls `planner()`
- **src/backend/optimizer/plan/planmain.c** — Core planning logic with entry point for query tree processing
- **src/backend/optimizer/plan/subselect.c** — Subquery planning
- **src/backend/optimizer/plan/initsplan.c** — Join clauses and WHERE condition initialization
- **src/backend/optimizer/plan/analyzejoins.c** — Join analysis and simplification
- **src/backend/optimizer/plan/planagg.c** — Aggregate function planning
- **src/backend/optimizer/plan/createplan.c** — **Phase 2**: Converts optimal Path nodes to Plan nodes; implements `create_plan()` which recursively builds executable Plan tree
- **src/backend/optimizer/path/allpaths.c** — **Phase 1**: Path generation; generates all candidate paths for base relations and joins; produces RelOptInfo with alternative Paths
- **src/backend/optimizer/path/joinpath.c** — Join path generation (nested loop, merge join, hash join)
- **src/backend/optimizer/path/joinrels.c** — Join relation construction
- **src/backend/optimizer/path/pathkeys.c** — Ordering information for paths
- **src/backend/optimizer/path/costsize.c** — Cost estimation for paths
- **src/backend/optimizer/path/indxpath.c** — Index access path generation
- **src/backend/optimizer/prep/** — Plan preparation (constraint simplification, aggregate/grouping processing)
- **src/backend/optimizer/util/clauses.c** — Expression and clause utilities

### Executor
- **src/backend/executor/execMain.c** — Executor initialization and main execution loop:
  - `ExecutorStart()` — Initializes execution engine; creates EState, allocates parameters
  - `standard_ExecutorStart()` — Standard startup; calls `InitPlan()` which recursively initializes plan state tree via `ExecInitNode()`
  - `ExecutorRun()` — Main execution loop; calls `ExecutePlan()` to pull tuples
  - `ExecutorEnd()` — Cleanup via `ExecEndNode()`
- **src/backend/executor/execProcnode.c** — **Volcano-style Dispatch**: Core dispatcher implementing the pull-based iterator model:
  - `ExecInitNode()` — Recursively initializes plan nodes; dispatches via switch on node tag to node-specific `ExecInit*()` functions
  - `ExecProcNode()` — Main tuple-pulling dispatch (defined in executor.h as inline); calls `node->ExecProcNode(node)` which is a function pointer set during ExecInitNode()
  - `MultiExecProcNode()` — Alternative dispatch for operations returning sets (bitmap operations)
  - `ExecEndNode()` — Cleanup dispatch
- **src/backend/executor/nodeXXX.c** — 50+ node executor implementations, including:
  - Scan nodes: `nodeSeqscan.c`, `nodeIndexscan.c`, `nodeBitmapHeapscan.c`
  - Join nodes: `nodeNestloop.c`, `nodeMergejoin.c`, `nodeHashjoin.c`
  - Aggregate nodes: `nodeAgg.c`, `nodeGroup.c`, `nodeWindowAgg.c`
  - Sort/Material: `nodeSort.c`, `nodeMaterial.c`
  - Modification: `nodeModifyTable.c`
  - Set operations: `nodeSetOp.c`, `nodeAppend.c`
- **src/backend/executor/execExpr.c** — Expression evaluation engine; `ExecInitExpr()` compiles expressions to flat step array; `ExecExprInterp()` interprets steps
- **src/backend/executor/execScan.c** — Common scan node infrastructure
- **src/backend/executor/execTuples.c** — Tuple slot management
- **src/backend/executor/execUtils.c** — General executor utilities

### Node Type Definitions
- **src/include/nodes/parsenodes.h** — Parse tree node definitions (RawStmt, Expr, etc.)
- **src/include/nodes/plannodes.h** — Plan tree node definitions
- **src/include/nodes/execnodes.h** — Executor state node definitions (PlanState, ScanState, JoinState, etc.)
- **src/include/executor/execdesc.h** — QueryDesc definition
- **src/include/executor/executor.h** — Executor API and inline functions (ExecProcNode, etc.)

---

## Dependency Chain

### Entry: Query Reception to Execution

```
exec_simple_query() [src/backend/tcop/postgres.c:1011]
    ↓
1. PARSING STAGE
    ↓
pg_parse_query() [src/backend/tcop/postgres.c:603]
    ↓
raw_parser() [src/backend/parser/parser.c]
    ↓
Uses scan.l (lexer) + gram.y (grammar)
    ↓
Returns: List of RawStmt nodes

    ↓
2. SEMANTIC ANALYSIS STAGE
    ↓
pg_analyze_and_rewrite_fixedparams() [src/backend/tcop/postgres.c:665]
    ↓
parse_analyze_fixedparams() [src/backend/parser/analyze.c:105]
    ↓
Transforms RawStmt → Query
Uses parse_*.c modules for detailed analysis
Returns: Single Query node

    ↓
3. REWRITING STAGE
    ↓
pg_rewrite_query() [src/backend/tcop/postgres.c:798]
    ↓
QueryRewrite() [src/backend/rewrite/rewriteHandler.c]
    ↓
Applies rules, view expansion, security policies
Returns: List of Query nodes (0..n)

    ↓
4. PLANNING STAGE
    ↓
pg_plan_queries() [src/backend/tcop/postgres.c:970]
    ↓
pg_plan_query() [src/backend/tcop/postgres.c:882]
    ↓
planner() [src/backend/optimizer/plan/planner.c:287]
    ↓
standard_planner() [src/backend/optimizer/plan/planner.c:303]
    ├─ subquery_planner() [src/backend/optimizer/plan/planmain.c]
    │   ├─ PHASE 1: Path Generation via allpaths.c
    │   │   ├─ generate_base_rel_paths() - base relation paths
    │   │   ├─ add_other_rel_paths() - other relation types
    │   │   └─ add_paths_to_joinrel() - join paths
    │   │       └─ Uses joinpath.c (nested loop, merge, hash)
    │   │       └─ Uses costsize.c for cost estimation
    │   ├─ Builds RelOptInfo with alternative Paths
    │   └─ Returns Root (PlannerInfo) with final RelOptInfo
    │
    ├─ fetch_upper_rel() - fetches final RelOptInfo
    ├─ get_cheapest_fractional_path() - selects best Path
    │
    └─ PHASE 2: Plan Creation via createplan.c
        ├─ create_plan() [src/backend/optimizer/plan/createplan.c]
        │   ├─ Recursively converts Path → Plan
        │   ├─ Dispatch via switch on Path type
        │   └─ Populates Plan node fields
        └─ set_plan_references() - adjusts variable references

Returns: PlannedStmt (contains Plan tree + metadata)

    ↓
5. EXECUTION STAGE
    ↓
PortalRun() [src/backend/tcop/pquery.c]
    ↓
ProcessQuery() [src/backend/tcop/pquery.c:137]
    ↓
CreateQueryDesc() [src/backend/tcop/pquery.c:68]
    Returns: QueryDesc = {plannedstmt, sourceText, snapshot, dest, params, ...}
    ↓
ExecutorStart() [src/backend/executor/execMain.c:122]
    ↓
standard_ExecutorStart() [src/backend/executor/execMain.c:141]
    ├─ CreateExecutorState() - creates EState
    └─ InitPlan() [src/backend/executor/execMain.c]
        └─ ExecInitNode(planTree, estate, eflags)
            ├─ VOLCANO DISPATCH: Switch on node tag
            ├─ For each node type, calls ExecInitXxx()
            │   └─ Each ExecInitXxx recursively calls ExecInitNode() on children
            └─ Builds parallel PlanState tree
    ↓
ExecutorRun() [src/backend/executor/execMain.c:297]
    ↓
standard_ExecutorRun() [src/backend/executor/execMain.c:307]
    ├─ Startup dest receiver
    └─ ExecutePlan() [src/backend/executor/execMain.c]
        └─ Loop: ExecProcNode(topNode)
            ├─ VOLCANO PULL: Inline dispatch in executor.h:310
            │   └─ Calls node->ExecProcNode(node)
            ├─ Each node's ExecXxx() function
            │   ├─ Calls ExecProcNode() on children to pull input tuples
            │   ├─ Processes (filter, project, join, aggregate, etc.)
            │   └─ Returns output TupleTableSlot or NULL
            └─ Repeats until ExecProcNode returns NULL (EOF)
    ↓
ExecutorFinish() [src/backend/executor/execMain.c]
    └─ ExecFinishNode() - finalize aggregates, etc.
    ↓
ExecutorEnd() [src/backend/executor/execMain.c]
    └─ ExecEndNode() - cleanup via switch dispatch
```

---

## Analysis

### Design Patterns Identified

#### 1. **Volcano-Style Execution Model (Iterator Model)**
PostgreSQL implements the classic Volcano/Cascades iterator execution model:
- Each plan node acts as an iterator with three main operations:
  - **Init** (`ExecInitNode`, dispatches to `ExecInitXxx`): Initialize state
  - **Next** (`ExecProcNode`, dispatches to node-specific executor function): Pull one tuple
  - **End** (`ExecEndNode`, dispatches to `ExecEndXxx`): Clean up

- **Pull-based pipeline**: Execution flows bottom-up; parent nodes pull tuples from children via `ExecProcNode()` calls
- **Tuple-at-a-time processing**: Each `ExecProcNode()` call returns exactly one tuple (or NULL for EOF)
- **Function pointer dispatch**: During init, each PlanState node gets a function pointer (`ExecProcNode`) pointing to its executor function
- **Recursive composition**: Complex queries are built from simple node types; nodes at all levels follow the same iterator interface

The inline `ExecProcNode()` (executor.h:310) is the performance-critical dispatch mechanism:
```c
static inline TupleTableSlot *
ExecProcNode(PlanState *node) {
    if (node->chgParam != NULL)
        ExecReScan(node);
    return node->ExecProcNode(node);  // Function pointer dispatch
}
```

This design enables:
- **Modularity**: New node types added by implementing Init/Next/End functions
- **Composability**: Complex execution plans from simple, reusable components
- **Memory efficiency**: Streaming tuple processing (no materializing entire result sets)

#### 2. **Two-Phase Optimization**
The planner decomposes optimization into distinct phases:

**Phase 1 – Path Generation (allpaths.c)**
- Generates candidate execution paths for each relation and join combination
- Each Path represents one possible way to access/process data
- Paths include cost information (startup + total cost estimates)
- Examples: SeqScan path, IndexScan path, BitmapIndexScan path
- Joins generate: NestLoopPath, MergeJoinPath, HashJoinPath
- Products: RelOptInfo with list of Paths; winner selected by cost

**Phase 2 – Plan Creation (createplan.c)**
- Converts optimal Path to executable Plan tree
- `create_plan()` recursively traverses Path tree
- Populates Plan nodes with node-specific initialization data
- Example: HashJoinPath → HashJoin plan with hash table building strategy
- Result: Plan tree ready for execution (schema-aware, all properties resolved)

This two-phase separation provides:
- **Search space exploration** without committing to execution representation
- **Cost-based decisions** with flexible path representations
- **Clean interface** between optimization and execution (Path vs Plan)

#### 3. **Read-Only Plan Trees**
- Plan tree (src/include/nodes/plannodes.h) is completely immutable during execution
- All mutable state is in the parallel PlanState tree (execnodes.h)
- Enables safe plan caching and reuse across multiple executions
- Separation of concerns: Planner produces schema; Executor manages state

#### 4. **Expression Compilation to Flat Form**
- Expr trees (parse tree representation) are compiled to flat ExprEvalStep arrays during ExecutorStart
- `ExecInitExpr()` builds ExprState with steps[] array
- Benefits:
  - Reduces tree-walk overhead during evaluation
  - Single-function interpretation of expressions
  - Enables JIT compilation without interpreter overhead
  - Precomputes invariant information

#### 5. **State Tree Mirrors Plan Tree Structure**
- During ExecutorStart, a PlanState tree is built with identical structure to Plan tree
- Each Plan node → corresponding PlanState node type
- Example: `Plan::Append` → `PlanState::AppendState`
- PlanState holds all mutable data needed during execution
- Allows plan reuse across multiple executions

### Component Responsibilities

**Traffic Cop (postgres.c:1011)**
- Receives raw SQL string
- Coordinates entire pipeline
- Manages transaction context
- Handles command completion and result delivery

**Parser (parser.c + scan.l + gram.y)**
- **Responsibilities**: Lexical + syntactic analysis
- **Input**: SQL text string
- **Output**: Parse tree (RawStmt with generic structure)
- **Mechanism**: Flex lexer (scan.l) tokenizes; Bison parser (gram.y) builds tree
- **Key Property**: No semantic validation; purely structural

**Semantic Analyzer (analyze.c + parse_*.c)**
- **Responsibilities**: Semantic validation, type checking, name resolution
- **Input**: RawStmt (untyped parse tree)
- **Output**: Query (semantically valid, type-checked)
- **Process**:
  - Validates table/column names against schema
  - Type-checks expressions and coerces as needed
  - Resolves ambiguous names
  - Processes special clauses (aggregates, window functions, CTEs)
- **Key Property**: Single Query per input RawStmt (usually)

**Query Rewriter (rewriteHandler.c)**
- **Responsibilities**: Rule application, view expansion, security policies
- **Input**: Query (semantic tree)
- **Output**: List of Queries (0..n due to expansion)
- **Examples**:
  - View → subquery in FROM
  - Rule → additional auxiliary queries
  - RLS policies → WHERE clause additions
- **Key Property**: May expand 1 Query into many (SELECT + INSERT rule → 2 queries)

**Planner - Phase 1 (allpaths.c)**
- **Responsibilities**: Generate candidate execution paths
- **Input**: Query (semantic tree)
- **Scope**: Base relations, joins, aggregations, etc.
- **Process**:
  - `generate_base_rel_paths()`: Paths for single tables
  - `add_paths_to_joinrel()`: Join paths via nested loop, merge, hash
  - Cost estimation via `cost_*()` functions
- **Output**: RelOptInfo with alternative Paths (no execution specifics yet)

**Planner - Phase 2 (createplan.c)**
- **Responsibilities**: Convert optimal Path to Plan
- **Input**: Best Path from Phase 1
- **Process**: Recursive `create_plan()` dispatch
  - Path type → Plan type
  - Populates Plan node with execution parameters
  - Example: HashPath → HashJoin with hash function, key columns
- **Output**: Plan tree (execution-ready, immutable)

**Executor - Init (execMain.c + execProcnode.c)**
- **Responsibilities**: Build execution state tree
- **Input**: Plan tree
- **Process**: ExecInitNode recursive dispatch
  - Each Plan node → PlanState node
  - Compile expressions to ExprState
  - Allocate runtime data structures
  - Set up function pointers (ExecProcNode)
- **Output**: PlanState tree with initialized state

**Executor - Run (execMain.c + execProcnode.c + nodeXXX.c)**
- **Responsibilities**: Pull tuples through pipeline
- **Mechanism**: ExecProcNode inline dispatch
  - Calls node function pointers
  - Each node pulls from children
  - Processes (filter, project, join, aggregate)
  - Returns tuples or NULL (EOF)
- **Key Property**: Tuple-at-a-time; streaming; no intermediate materialization (unless Sort, Agg, etc.)

**Executor - End (execProcnode.c)**
- **Responsibilities**: Clean up resources
- **Process**: ExecEndNode recursive dispatch
- **Handles**: Closing scans, freeing buffers, finalizing aggregates

### Data Flow: Type Transformations

```
SQL String
    ↓
    └→ raw_parser() [scan.l + gram.y]
        ↓
        └→ RawStmt (untyped generic structure)
            - Minimal semantic info
            - No type checking
            - No name resolution
            ↓
            └→ parse_analyze() [analyze.c + parse_*.c]
                ↓
                └→ Query (type-checked, name-resolved)
                    - Full semantic information
                    - Expression types resolved
                    - Table/column references validated
                    ↓
                    └→ QueryRewrite() [rewriteHandler.c]
                        ↓
                        └→ Query (possibly expanded)
                            - Rules applied
                            - Views expanded
                            - Security policies injected
                            ↓
                            └→ standard_planner() [planner.c]
                                ├─ Phase 1: allpaths.c
                                │   └→ RelOptInfo (Paths with cost)
                                └─ Phase 2: createplan.c
                                    ↓
                                    └→ PlannedStmt (Plan tree + metadata)
                                        - Executable plan
                                        - All joins, aggregates planned
                                        - Immutable during execution
                                        ↓
                                        └→ ExecutorStart() [execMain.c]
                                            ↓
                                            └→ ExecInitNode() [execProcnode.c]
                                                ↓
                                                └→ PlanState tree
                                                    - Runtime state
                                                    - ExprState compiled
                                                    - Function pointers set
                                                    ↓
                                                    └→ ExecutorRun()
                                                        └→ ExecProcNode() loop
                                                            ↓
                                                            └→ Tuples (result set)
```

### Interface Contracts Between Components

**Parser → Semantic Analyzer**
- **Contract**: RawStmt with untyped expressions
- **Guarantees**: Syntactically valid; may contain name/type errors
- **Properties**: Generic structure (no knowledge of command type)

**Semantic Analyzer → Rewriter**
- **Contract**: Query with resolved types and names
- **Guarantees**: Semantically valid within current schema; expressions typed
- **Properties**: One-to-one mapping (usually) with input

**Rewriter → Planner**
- **Contract**: Query (may be from rewriter expansion)
- **Guarantees**: Fully analyzed; ready for optimization
- **Properties**: Multiple queries possible (parallel independent optimization)

**Planner → Executor**
- **Contract**: PlannedStmt with Plan tree
- **Guarantees**: Optimal execution path selected; all joins/aggregates planned
- **Properties**: Immutable; can be cached and reused

**Executor Init → Executor Run**
- **Contract**: PlanState tree with initialized state
- **Guarantees**: All runtime structures allocated; expressions compiled
- **Properties**: State tree mirrors plan structure; function pointers active

### Volcano-Style Executor Dispatch (execProcnode.c)

The core dispatch mechanism at execution time is the **pull model**:

**ExecProcNode inline dispatch (executor.h:310)**:
```c
static inline TupleTableSlot *
ExecProcNode(PlanState *node) {
    if (node->chgParam != NULL)
        ExecReScan(node);
    return node->ExecProcNode(node);  // Function pointer
}
```

**Dispatch during init** (`ExecInitNode`, execProcnode.c:142):
```
switch (nodeTag(plan)) {
    case T_SeqScan:
        result = (PlanState *)ExecInitSeqScan((SeqScan *)node, ...);
        // This sets: result->ExecProcNode = ExecSeqScan
        break;
    case T_NestLoop:
        result = (PlanState *)ExecInitNestLoop((NestLoop *)node, ...);
        // This sets: result->ExecProcNode = ExecNestLoop
        break;
    ...
}
```

**Execution via function pointers** (nodeXXX.c):
- `ExecSeqScan()` [nodeSeqscan.c]: Fetches tuples from heap sequentially
- `ExecNestLoop()` [nodeNestloop.c]: Pulls from outer, for each outer pulls from inner, returns joined tuples
- `ExecAgg()` [nodeAgg.c]: Accumulates tuples, returns aggregated results
- `ExecSort()` [nodeSort.c]: Collects all input, sorts, returns in order
- Each function:
  1. Calls `ExecProcNode()` on children to get input tuples
  2. Processes the tuple (filtering, projection, joining, aggregating)
  3. Returns result tuple or NULL (EOF)

**Pipeline execution in ExecutePlan()** (execMain.c:~350):
```
while (true) {
    slot = ExecProcNode(topNode);  // Pull from root
    if (TupIsNull(slot)) break;     // EOF
    dest->receiveSlot(slot);         // Send to client
}
```

This creates a **demand-driven pipeline**:
- Tuples flow bottom-up (pulled by parents)
- No global queue/buffer (except for Sort, Agg, etc.)
- Natural backpressure (if parent slow, child waits)
- Scales to large result sets (streaming)

---

## Summary

PostgreSQL implements a **classic multi-stage query execution pipeline** with clear separation of concerns. The **parser** (lexer + grammar) produces untyped parse trees; the **semantic analyzer** validates and types them; the **rewriter** applies rules and view expansion; the **planner** executes two-phase optimization (path generation then plan creation) to find the optimal execution strategy; and the **Volcano-style executor** pulls tuples through a tree of iterator nodes, with each node dispatched via function pointers to its type-specific implementation. This architecture achieves modularity, composability, and efficiency through clean interfaces between pipeline stages and a demand-driven execution model that streams results without materializing intermediate datasets.
