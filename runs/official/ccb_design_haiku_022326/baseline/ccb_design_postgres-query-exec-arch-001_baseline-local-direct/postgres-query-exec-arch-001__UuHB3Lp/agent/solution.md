# PostgreSQL Query Execution Pipeline Architecture Analysis

## Files Examined

### Traffic Cop (Entry Point)
- `src/backend/tcop/postgres.c` — Main traffic cop; contains `exec_simple_query()` entry point that orchestrates the entire pipeline, dispatching to parser, analyzer/rewriter, and planner
- `src/backend/tcop/pquery.c` — Portal execution layer; `PortalRun()` dispatches to executor via `PortalRunSelect()` and related functions
- `src/backend/tcop/utility.c` — Utility command execution

### Lexer & Parser (Raw Parse Tree → RawStmt)
- `src/backend/parser/parser.c` — Main parser; `raw_parser()` invokes flex/bison-generated parser from `gram.y` and `scan.l` to produce `List<RawStmt>`
- `src/backend/parser/gram.y` — Bison grammar definition (compiled to parser)
- `src/backend/parser/scan.l` — Flex lexer definition (tokenizes input)

### Semantic Analyzer (RawStmt → Query)
- `src/backend/parser/analyze.c` — `parse_analyze_fixedparams()` and `parse_analyze_varparams()` convert `RawStmt` to `Query` by performing semantic validation, type checking, and resolving table/column references
- `src/backend/parser/parse_expr.c` — Expression type coercion and function resolution
- `src/backend/parser/parse_clause.c` — WHERE, FROM, ORDER BY, GROUP BY clause analysis
- `src/backend/parser/parse_relation.c` — Table/relation reference resolution
- `src/backend/parser/parse_collate.c` — Collation determination
- `src/backend/parser/parse_agg.c` — Aggregate function validation

### Query Rewriter (Query → Query)
- `src/backend/rewrite/rewriteHandler.c` — `QueryRewrite()` applies view expansion, rule rewriting, and trigger transformations; can expand one `Query` into multiple queries
- `src/backend/rewrite/rewriteManip.c` — Helper functions for query tree manipulation during rewriting
- `src/backend/rewrite/rewriteSupport.c` — Rewrite rule support functions

### Planner/Optimizer (Query → PlannedStmt)

#### High-Level Orchestration
- `src/backend/optimizer/plan/planner.c` — `planner()` entry point (with hook support) calls `standard_planner()`, which:
  1. Calls `subquery_planner()` to plan the query tree (invokes path generation via allpaths)
  2. Calls `fetch_upper_rel()` and `get_cheapest_fractional_path()` to select best path
  3. Calls `create_plan()` to convert the chosen path to a `PlannedStmt`

#### Phase 1: Path Generation & Cost Estimation
- `src/backend/optimizer/path/allpaths.c` — `make_one_rel()` generates alternative execution paths by considering different join orders and access methods; populates `RelOptInfo` with `Path` nodes containing cost estimates
- `src/backend/optimizer/path/costsize.c` — Cost estimation functions (`cost_seqscan()`, `cost_indexscan()`, etc.)
- `src/backend/optimizer/path/joinpath.c` — Join path generation (nested loop, hash join, merge join)
- `src/backend/optimizer/path/indxpath.c` — Index access path generation
- `src/backend/optimizer/path/joinrels.c` — Join relation generation during path enumeration
- `src/backend/optimizer/path/pathkeys.c` — PathKey structures for ordering and grouping optimization

#### Phase 2: Plan Creation (Path → Plan)
- `src/backend/optimizer/plan/createplan.c` — `create_plan()` converts the selected best `Path` into a `Plan` tree; recursively converts path nodes to plan nodes via dispatch (e.g., `SeqScan` path → `SeqScan` plan node)
- `src/backend/optimizer/plan/planmain.c` — `grouping_planner()` and related functions that structure the planning process
- `src/backend/optimizer/plan/initsplan.c` — Initial plan structure initialization
- `src/backend/optimizer/plan/subselect.c` — Subquery planning
- `src/backend/optimizer/plan/setrefs.c` — Sets var/param references in final plan tree

#### Query Structure Analysis
- `src/backend/optimizer/prep/` — Preprocessing for planning (join order analysis, partitioning prep)

### Executor (PlannedStmt → Result Tuples)

#### Executor Entry & Dispatch
- `src/backend/executor/execMain.c` — `ExecutorStart()`, `ExecutorRun()`, `ExecutorEnd()` lifecycle functions; `InitPlan()` initializes the plan tree
- `src/backend/executor/execProcnode.c` — `ExecInitNode()`, `ExecProcNode()`, `ExecEndNode()` dispatch functions that use Volcano-style switch statement over node type tags to invoke node-specific handlers

#### Executor Node Implementations (scan, join, aggregation)
- `src/backend/executor/nodeSeqscan.c` — Sequential scan execution
- `src/backend/executor/nodeIndexscan.c` — Index scan execution
- `src/backend/executor/nodeNestloop.c` — Nested loop join
- `src/backend/executor/nodeHashjoin.c` — Hash join
- `src/backend/executor/nodeMergejoin.c` — Merge join
- `src/backend/executor/nodeAgg.c` — Aggregate computation
- `src/backend/executor/nodeSort.c` — Sorting
- `src/backend/executor/nodeModifyTable.c` — INSERT/UPDATE/DELETE execution
- `src/backend/executor/nodeAppend.c` — UNION/APPEND execution

#### Supporting Executor Functions
- `src/backend/executor/execQual.c` — Expression evaluation
- `src/backend/executor/execScan.c` — Base scan infrastructure
- `src/backend/executor/execExpr.c` — Expression evaluation machinery

### Node Type Definitions
- `src/include/nodes/parsenodes.h` — `RawStmt`, `Query`, `Node` base structures
- `src/include/nodes/plannodes.h` — `Plan`, `PlannedStmt`, and plan node types
- `src/include/nodes/relation.h` — `RelOptInfo`, `Path`, `PathList`, and planner internal structures
- `src/include/executor/executor.h` — `PlanState`, `EState`, and executor state structures

---

## Dependency Chain

### 1. Entry Point: Traffic Cop
**Location:** `src/backend/tcop/postgres.c:1011` (`exec_simple_query()`)

```
exec_simple_query(const char *query_string)
  ├─ Initiates transaction context
  ├─ Parses SQL string
  ├─ Performs analysis/rewriting
  ├─ Creates plan
  └─ Executes plan via portal
```

### 2. Parsing Phase: Raw SQL String → RawStmt List

**Location:** `src/backend/tcop/postgres.c:603` (`pg_parse_query()`)

```
pg_parse_query(query_string: const char *)
  ↓ Calls
raw_parser(query_string, RAW_PARSE_DEFAULT)
  [src/backend/parser/parser.c:612]
  ↓ Invokes Bison/Flex generated parser
  ↓ (from gram.y and scan.l)
  Returns: List<RawStmt>
```

**Data Structure Transformation:**
```
Raw SQL String
    ↓
[Lexer: scan.l tokenizes]
    ↓
[Parser: gram.y builds parse tree]
    ↓
RawStmt {
    Node    stmt;      /* actual parse tree */
    int     stmt_location;
    int     stmt_len;
}
```

### 3. Semantic Analysis & Query Rewriting: RawStmt → Query List

**Location:** `src/backend/tcop/postgres.c:665` (`pg_analyze_and_rewrite_fixedparams()`)

#### Phase 3a: Semantic Analysis (RawStmt → Query)
```
pg_analyze_and_rewrite_fixedparams(RawStmt *parsetree, ...)
  ↓ Calls (line 682)
parse_analyze_fixedparams(parsetree, query_string, paramTypes, numParams, queryEnv)
  [src/backend/parser/analyze.c:xxxx]
  ├─ Validates table/column references
  ├─ Resolves function names and parameter types
  ├─ Type checking and coercion
  ├─ Semantic validation (aggregate placement, subquery validity, etc.)
  └─ Returns: Query
```

**Key Analysis Steps:**
- `transformSelectStmt()` → transforms SELECT statement structure
- `transformFromClause()` → resolves table references via `parse_relation.c`
- `transformWhereClause()` → analyzes WHERE conditions
- `transformTargetList()` → validates SELECT list expressions
- Type coercion via `parse_coerce.c`

**Data Structure at Query:**
```
Query {
    CmdType     commandType;    /* SELECT, INSERT, UPDATE, DELETE, ... */
    List       *rtable;         /* table references */
    List       *targetList;     /* SELECT list */
    Node       *whereClause;    /* WHERE clause */
    List       *groupClause;    /* GROUP BY */
    Node       *havingClause;   /* HAVING */
    ... [other fields]
}
```

#### Phase 3b: Query Rewriting (Query → Query List)
```
pg_analyze_and_rewrite_fixedparams()
  ↓ Calls (line 691)
pg_rewrite_query(query)
  [src/backend/tcop/postgres.c:798]
  ↓ Calls (line 817)
QueryRewrite(query)
  [src/backend/rewrite/rewriteHandler.c]
  ├─ View expansion
  ├─ Rule application
  ├─ Trigger transformation
  └─ Returns: List<Query>
     (one query can expand to multiple)
```

### 4. Planner/Optimizer: Query → PlannedStmt

**Location:** `src/backend/tcop/postgres.c:970` (`pg_plan_queries()`)

```
pg_plan_queries(List<Query> querytrees, ...)
  └─ For each Query:
     ↓ Calls (line 994)
     pg_plan_query(query, ...)
       [src/backend/tcop/postgres.c:882]
       ↓ Calls (line 900)
       planner(query, query_string, cursorOptions, boundParams)
         [src/backend/optimizer/plan/planner.c:287]
         ↓ Calls (line 295 unless hook overrides)
         standard_planner(query, ...)
           [src/backend/optimizer/plan/planner.c:303]
```

#### Standard Planner Flow:
```
standard_planner()
  ├─ Initialize PlannerGlobal and PlannerInfo
  ├─ Calls (line 435)
  │  subquery_planner(glob, parse, NULL, false, tuple_fraction, NULL)
  │    [src/backend/optimizer/plan/planner.c:651]
  │    ├─ Preprocessing via prep_simple_rel_list(), etc.
  │    ├─ Calls (recursively for subqueries)
  │    │  grouping_planner(root, tuple_fraction, ...)
  │    │    [src/backend/optimizer/plan/planmain.c]
  │    │    ├─ PHASE 1: Path Generation
  │    │    │  Calls (line ~500)
  │    │    │  make_one_rel(root, joinlist)
  │    │    │    [src/backend/optimizer/path/allpaths.c:171]
  │    │    │    ├─ For each base relation: set_rel_pathlist()
  │    │    │    │  ├─ SeqScan path
  │    │    │    │  └─ Index access paths
  │    │    │    └─ For each join: consider different join orders
  │    │    │       ├─ add_paths_to_joinrel() (nestloop, hashjoin, mergejoin)
  │    │    │       └─ Cost all paths via costsize.c
  │    │    │
  │    │    └─ Returns: RelOptInfo with populated .pathlist
  │    │
  │    └─ Returns: PlannerInfo root with RelOptInfo tree
  │
  ├─ PHASE 2: Best Path Selection
  ├─ Calls (line 438)
  │  fetch_upper_rel(root, UPPERREL_FINAL, NULL)
  │    Returns: RelOptInfo for final relation
  │
  ├─ Calls (line 439)
  │  get_cheapest_fractional_path(final_rel, tuple_fraction)
  │    Returns: Path *best_path (lowest cost)
  │
  ├─ PHASE 3: Path → Plan Conversion
  ├─ Calls (line 441)
  │  create_plan(root, best_path)
  │    [src/backend/optimizer/plan/createplan.c:~157]
  │    ├─ Dispatches on path node type
  │    ├─ SeqScan path → create_seqscan_plan()
  │    ├─ IndexScan path → create_indexscan_plan()
  │    ├─ NestLoop path → create_nestloop_plan()
  │    │  ├─ Recursively calls create_plan() on left/right subpaths
  │    │  └─ Returns: NestLoop plan node
  │    └─ Returns: Plan tree root
  │
  └─ Returns: PlannedStmt
```

**Two-Phase Optimization Detailed:**

**Phase 1: Path Generation (allpaths.c)**
- **Input:** `RelOptInfo` per relation with table metadata
- **Process:**
  - `set_rel_pathlist()`: For each base table, generate alternative access paths
    - Sequential scan
    - Index scans (for applicable indexes)
    - Cost each path via `cost_seqscan()`, `cost_indexscan()`, etc.
  - For joins: `add_paths_to_joinrel()` considers:
    - Nested loop join
    - Hash join (if applicable)
    - Merge join (if applicable)
  - All possible join orders explored (via GEQO for large joins)
- **Output:** `RelOptInfo` list with `.pathlist` populated with alternative `Path` nodes
- **Each Path node contains:**
  ```
  Path {
    NodeTag type;           /* path type tag */
    RelOptInfo *parent;
    Cost    startup_cost;   /* cost before first tuple */
    Cost    total_cost;     /* cost for all tuples */
    List   *pathkeys;       /* sort order info */
  }
  ```

**Phase 2: Plan Creation (createplan.c)**
- **Input:** Selected best `Path` node with lowest cost
- **Process:**
  - Recursively converts `Path` nodes to `Plan` nodes
  - `create_plan_recurse()` dispatches on path type:
    ```
    SeqScan Path → SeqScan Plan
    IndexScan Path → IndexScan Plan
    NestLoop Path → NestLoop Plan
    HashJoin Path → HashJoin Plan
    ...
    ```
  - Sets up qualifications, target lists, and parameter references
  - Calls `setrefs.c` to finalize variable/parameter references
- **Output:** `PlannedStmt` with complete executable plan tree

**Data Structure at Plan:**
```
PlannedStmt {
    CmdType         commandType;
    uint64          queryId;
    Plan           *planTree;      /* tree of Plan nodes */
    List           *rtable;        /* relation table */
    List           *resultRelations;
    List           *appendRelations;
    List           *targetList;
    List           *initPlan;      /* init plans for subqueries */
    List           *nonleafPlans;  /* non-leaf plan nodes */
    int             nInitPlans;
    ... [other metadata]
}
```

### 5. Portal Creation & Execution Setup

**Location:** `src/backend/tcop/postgres.c:1224` (`PortalDefineQuery()`)

```
PortalDefineQuery(portal, NULL, query_string, commandTag, plantree_list, NULL)
  └─ Stores PlannedStmt list in Portal structure
```

### 6. Executor: PlannedStmt → Result Tuples

**Location:** `src/backend/tcop/pquery.c:685` (`PortalRun()`)

```
PortalRun(portal, FETCH_ALL, true, receiver, receiver, &qc)
  └─ Dispatches based on portal strategy (PORTAL_ONE_SELECT, etc.)
     ├─ FillPortalStore(portal, isTopLevel)  [if needed]
     │  └─ ExecutorStart/ExecutorRun/ExecutorEnd cycle
     └─ PortalRunSelect() [for SELECT queries]
        └─ Calls (line ~250)
           ExecutorStart(queryDesc, EXECUTOR_FLAG_xxx)
             [src/backend/executor/execMain.c]
             ├─ InitPlan(queryDesc, eflags)
             │  └─ ExecInitNode(plan, estate, eflags)
             │     [src/backend/executor/execProcnode.c:142]
             │     └─ VOLCANO-STYLE DISPATCH via switch(nodeTag(plan)):
             │        ├─ T_SeqScan → ExecInitSeqScan()
             │        │  └─ Returns: SeqScanState with .ExecProcNode fn ptr
             │        ├─ T_IndexScan → ExecInitIndexScan()
             │        ├─ T_NestLoop → ExecInitNestLoop()
             │        │  ├─ ExecInitNode() on left child
             │        │  └─ ExecInitNode() on right child
             │        └─ [~50+ plan node types]
             │
             └─ Builds PlanState tree parallel to Plan tree
                [Each PlanState has function pointer to execution routine]

           ExecutorRun(queryDesc, FETCH_ALL, estate->es_processed)
             └─ ExecutePlan(estate, planstate, ..., receiver)
                └─ Loop: while (!done)
                   └─ ExecProcNode(planstate)
                      [src/backend/executor/execProcnode.c:474]
                      └─ Calls via function pointer:
                         planstate->ExecProcNode(planstate)
                         ├─ For SeqScan: ExecSeqScan()
                         │  └─ Scans heap, applies qual, returns TupleTableSlot
                         ├─ For NestLoop: ExecNestLoop()
                         │  ├─ ExecProcNode(left_child)
                         │  └─ For each outer tuple:
                         │     └─ ExecProcNode(right_child)
                         └─ [node-specific execution logic]

           ExecutorEnd(queryDesc)
             └─ ExecEndNode(planstate)
                └─ Recursive cleanup via switch(nodeTag(planstate))
                   └─ Node-specific cleanup (close scans, free memory)
```

**Volcano-Style Executor Dispatch Pattern:**

The executor implements the Volcano iterator model:
- **Three core operations per node type:**
  1. `ExecInit<NodeType>()` — Initialize and open the node (allocate memory, open tables)
  2. `ExecProcNode()` → `Exec<NodeType>()` — Get next tuple (call via function pointer)
  3. `ExecEnd<NodeType>()` — Cleanup and close the node

- **Key Design Pattern:**
  - Each `PlanState` node has a `.ExecProcNode` function pointer
  - `ExecProcNode()` is called repeatedly in a loop
  - Each call returns `TupleTableSlot *` (a single tuple or NULL for EOF)
  - Parent nodes call `ExecProcNode()` on children to pull tuples

- **Pull-Based Model:**
  - Top node (`ExecutorRun()`) pulls from root
  - Root pulls from children
  - Leaves pull from table storage
  - Results flow upward via tuple slots

**Example: NestLoop Join Execution**
```
ExecutorStart() → ExecInitNestLoop()
  ├─ Create left_plan_state from left child
  ├─ Create right_plan_state from right child
  └─ Set node->ExecProcNode = ExecNestLoop

ExecutorRun() loop:
  ExecProcNode(nestloop_state)
    → ExecNestLoop(nestloop_state)
      ├─ If (need new outer tuple)
      │  └─ outer_tuple ← ExecProcNode(left_child)
      ├─ If (outer_tuple not NULL)
      │  └─ Reset right child
      │     └─ ExecReScan(right_child)
      └─ Loop: while (inner_tuple ← ExecProcNode(right_child))
         ├─ If (join condition matches)
         │  └─ Return tuple
         └─ Continue inner loop

ExecutorEnd() → ExecEndNestLoop()
  ├─ ExecEndNode(left_child)
  └─ ExecEndNode(right_child)
```

---

## Analysis

### Design Patterns Identified

#### 1. **Pipeline Architecture with Staged Data Transformation**
The query execution follows a classic multi-stage compiler pipeline:
```
RawStmt (syntactic) → Query (semantic) → Query (rewritten) → PlannedStmt (optimized) → TupleSlot (result)
```
Each stage has well-defined input/output contracts and uses specialized data structures.

#### 2. **Volcano Iterator Model in Executor**
The executor uses the Volcano (Graefe) iterator pattern:
- **Pull-based evaluation:** Each operator calls `ExecProcNode()` on children
- **Function pointers:** Node type dispatching via function pointers instead of vtables
- **Stateful operators:** Each node maintains state between calls (e.g., join state, sort memory)
- **Tuple-at-a-time processing:** Operators return one tuple per call

#### 3. **Cost-Based Optimization with Path Abstraction**
- **Two-phase optimization:**
  - **Phase 1 (Paths):** Generate alternative execution strategies with cost estimates without allocating plan nodes
  - **Phase 2 (Plans):** Convert selected cheapest path into executable plan tree
- **Advantage:** Allows exploring many paths (exponential in joins) before committing to plan structure
- **Cost model:** Detailed cost functions consider CPU, I/O, and memory

#### 4. **Dynamic Dispatch via Node Type Tags**
Both analyzer and executor use `switch(nodeTag(node))` pattern:
```c
switch (nodeTag(node)) {
    case T_SeqScan:
        result = ExecInitSeqScan(...);
        break;
    case T_IndexScan:
        result = ExecInitIndexScan(...);
        break;
    ...
}
```
Avoids vtables but requires exhaustive case statements for extensibility.

#### 5. **Visitor Pattern for Tree Traversal**
Functions like `ExecInitNode()` and `ExecEndNode()` recursively visit entire plan trees:
```
ExecInitNode(plan) → calls ExecInit<Type>() → which calls ExecInitNode() on children
```

#### 6. **Context Switching for Memory Management**
Uses memory contexts to group allocations:
```
MemoryContextSwitchTo(MessageContext);
/* build query tree */
MemoryContextSwitchTo(TransactionContext);
/* execute query */
```
Entire context can be freed when done, avoiding individual deallocations.

### Component Responsibilities

#### Traffic Cop (`postgres.c`)
- **Responsibility:** High-level request dispatching and transaction orchestration
- **Duties:**
  - Parse incoming SQL string
  - Coordinate analyzer/rewriter/planner
  - Create portal and manage execution
  - Handle transaction boundaries
  - Report completion to client

#### Parser (`parser/`)
- **Responsibility:** Tokenization and syntactic analysis
- **Input:** Raw SQL string
- **Output:** `RawStmt` (syntactic tree)
- **Key Insight:** Grammar-driven by `gram.y` (Bison) and `scan.l` (Flex); minimal semantic validation

#### Semantic Analyzer (`parser/analyze.c`)
- **Responsibility:** Semantic validation and type system enforcement
- **Input:** `RawStmt`
- **Output:** `Query` (typed, resolved)
- **Tasks:**
  - Resolve table/column references
  - Type checking and coercion
  - Function resolution
  - Aggregate/window function validation
  - Subquery analysis
- **Key Insight:** Resolves ambiguities and validates query legality

#### Rewriter (`rewrite/`)
- **Responsibility:** Query transformation via rules and views
- **Input:** `Query`
- **Output:** `List<Query>` (typically expanded)
- **Transformations:**
  - View expansion
  - Rule application (ON INSERT/UPDATE/DELETE rules)
  - Trigger trigger transformation
  - Security barrier view handling
- **Key Insight:** One input query can produce multiple output queries (e.g., view with rules)

#### Planner (`optimizer/plan/planner.c` + `optimizer/path/allpaths.c`, `optimizer/plan/createplan.c`)
- **Responsibility:** Query optimization and plan generation
- **Two Phases:**
  - **Phase 1 (Paths):** `allpaths.c` generates alternative execution strategies with cost estimates
    - Considers different table access methods (seq scan vs. index scans)
    - Explores different join orders and algorithms
    - Estimates cost for each strategy
  - **Phase 2 (Plans):** `createplan.c` converts the cheapest path into an executable plan
    - Allocates plan nodes
    - Sets up expressions and qual lists
    - Fixes variable references
- **Key Insight:** Cost model drives all decisions; more expensive operations explore fewer alternatives

#### Executor (`executor/`)
- **Responsibility:** Query execution via tuple-at-a-time iteration
- **Model:** Volcano iterator
- **Lifecycle:**
  1. `ExecutorStart()` — Initialize plan tree into state tree
  2. `ExecutorRun()` — Call `ExecProcNode()` repeatedly on root
  3. `ExecutorEnd()` — Cleanup and resource release
- **Key Insight:** Push processing to individual operators; supports pipelining and memory efficiency

### Data Flow Description

#### From Parser Through Execution
```
Input: SQL String "SELECT * FROM t WHERE id=1"
  ↓ [raw_parser]
  → RawStmt { stmt: SelectStmt { ... } }

  ↓ [parse_analyze_fixedparams]
  → Query {
      targetList: [...],
      rtable: [RTE { relname: "t" }],
      whereClause: Expr { ... }
    }

  ↓ [QueryRewrite]
  → Query (unchanged if no views/rules)

  ↓ [standard_planner]

    ↓ [subquery_planner → grouping_planner]

    ↓ [Phase 1: allpaths]
    → RelOptInfo {
        .pathlist: [
          SeqScan Path { cost: 10.0 },
          IndexScan Path (on id) { cost: 2.5 }
        ]
      }

    ↓ [Phase 2: createplan]
    → Plan {
        type: T_IndexScan,
        left/right: NULL,
        targetlist: [...],
        qual: [Expr { ... }]
      }

  ↓ [PortalRun]
  → TupleTableSlot* {
      tuple: [id=1, col2="value", ...],
      isnull: [false, false, ...],
      tts_isempty: false
    }
```

#### Memory Contexts During Execution
```
MessageContext
  ├─ Raw parsetree_list
  ├─ Query objects (querytree_list)
  ├─ PlannedStmt objects (plantree_list)
  └─ Portal structure

TransactionContext
  └─ Temporary data during query execution

PortalContext (within a Portal)
  └─ Tuple buffers, execution state
```

### Interface Contracts Between Stages

#### Parser → Analyzer
- **Contract:** `List<RawStmt>` with all fields populated
- **Guarantee:** Syntactically valid (or error raised)
- **No Guarantee:** Semantic validity, type safety

#### Analyzer → Rewriter
- **Contract:** `List<Query>` with resolved table/column references
- **Guarantee:** Semantic validity within one query
- **No Guarantee:** Rules/views expanded

#### Rewriter → Planner
- **Contract:** `List<Query>` with all rules/views applied
- **Guarantee:** Ready for optimization
- **No Guarantee:** Optimal execution plan

#### Planner → Executor
- **Contract:** `PlannedStmt` with complete executable plan tree
- **Guarantee:** Cost-optimal plan (given current cost model)
- **No Guarantee:** Runtime performance (I/O patterns, memory pressure unknown at plan time)

#### Executor API
**Each node type exports:**
```c
PlanState *ExecInit<NodeType>(Plan *plan, EState *estate, int eflags);
TupleTableSlot *Exec<NodeType>(PlanState *node);
void ExecEnd<NodeType>(PlanState *node);
```

### Cost Model & Optimizer Heuristics

PostgreSQL's cost model (`costsize.c`) estimates cost as:
```
Total Cost = Startup Cost + (Output Rows × Per-Row Cost)
```

**For Sequential Scan:**
```
cost = random_page_cost × (num_pages)
     + cpu_tuple_cost × (num_rows)
```

**For Index Scan:**
```
cost = index_cost
     + random_page_cost × (pages_visited)
     + cpu_tuple_cost × (tuples_retrieved)
```

**Join Cost (NestLoop):**
```
cost = outer_cost
     + (outer_rows × inner_startup_cost)
     + (outer_rows × inner_rows × inner_run_cost)
     + (join_tuple_cost × output_rows)
```

**Join Order Optimization:**
- **Small relations:** Exhaustive enumeration via dynamic programming
- **Large relations (>12 tables):** Genetic algorithm (GEQO) to prune search space

### Extensibility Points

1. **Planner Hook:** `planner_hook` allows custom optimization
2. **Path Hooks:** `set_rel_pathlist_hook` for custom access methods
3. **Executor Hooks:** `ExecutorStart_hook`, `ExecutorRun_hook`, `ExecutorEnd_hook`
4. **Custom Scan Nodes:** Foreign data wrappers and extension nodes

---

## Summary

PostgreSQL's query execution pipeline implements a **classic five-stage compiler architecture** where raw SQL flows through lexing → parsing → semantic analysis → rewriting → optimization → execution. The **two-phase optimizer** separates path generation (exploring alternative strategies with cost estimates) from plan creation (materializing the chosen strategy), allowing the planner to evaluate exponentially many paths without allocating intermediate structures. The **executor uses the Volcano iterator model**, where `ExecProcNode()` is called repeatedly on a tree of stateful operators that pull tuples from children, enabling pipelining and cache-efficient processing. Each stage is independent but tightly coupled through well-defined data structures (`RawStmt` → `Query` → `PlannedStmt` → `TupleTableSlot`), and the pipeline is driven by a sophisticated cost model that estimates per-operator costs including CPU, I/O, and memory to select the lowest-cost execution plan.
