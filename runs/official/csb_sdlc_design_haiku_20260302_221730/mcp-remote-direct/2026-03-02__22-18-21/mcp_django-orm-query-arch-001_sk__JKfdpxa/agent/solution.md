# Django ORM Query Compilation Pipeline Analysis

## Files Examined

### Entry Point & Query Building
- **django/db/models/manager.py** — Entry point for ORM access; Manager.get_queryset() creates QuerySet instances; proxies QuerySet methods via descriptor pattern
- **django/db/models/query.py** — QuerySet class implementing lazy query building; filter()/exclude() methods call _filter_or_exclude_inplace() to add Q objects to query

### Query Object & Compilation
- **django/db/models/sql/query.py** — Query class (BaseExpression subclass) storing query state; get_compiler() dispatches to backend-specific compiler via connection.ops.compiler()
- **django/db/models/sql/where.py** — WhereNode tree structure managing WHERE/HAVING/QUALIFY clauses; as_sql() recursively compiles boolean trees; split_having_qualify() routes predicates to correct clauses
- **django/db/models/sql/datastructures.py** — Join, BaseTable, MultiJoin classes representing table metadata and join semantics

### Compiler & SQL Generation
- **django/db/models/sql/compiler.py** — SQLCompiler class compiling Query to SQL; as_sql() orchestrates SELECT building; compile() method implements vendor dispatch; execute_sql() runs SQL and returns results
- **django/db/backends/base/operations.py** — BaseDatabaseOperations defining compiler_module and backend capabilities; compiler() returns database-specific compiler class
- **django/db/backends/postgresql/compiler.py** — Backend-specific compiler overriding as_sql() for dialect-specific optimization (e.g., UNNEST for bulk insert)
- **django/db/backends/mysql/compiler.py** — MySQL-specific compiler with DELETE/UPDATE variants
- **django/db/backends/sqlite3/compiler.py** — SQLite-specific compiler

### Expression & Lookup System
- **django/db/models/expressions.py** — BaseExpression protocol defining as_sql(compiler, connection) → (sql, params); Expression subclasses implement resolve_expression() for type inference and get_source_expressions() for tree traversal; Combinable mixin provides operator overloading
- **django/db/models/lookups.py** — Lookup class (Expression subclass) composing lhs/rhs into WHERE predicates; BuiltinLookup.as_sql() combines process_lhs(), process_rhs(), get_rhs_op() to generate SQL; vendor-specific lookups via as_{vendor}() methods (e.g., as_oracle())

## Dependency Chain

### 1. Entry Point
**Path:** Manager.get_queryset() in django/db/models/manager.py:150-155

```python
def get_queryset(self):
    return self._queryset_class(model=self.model, using=self._db, hints=self._hints)
```

The Manager creates a fresh QuerySet instance linked to the model, database routing, and hints.

---

### 2. Lazy Query Building
**Path:** QuerySet.filter() → _filter_or_exclude() in django/db/models/query.py:1475-1506

```python
def filter(self, *args, **kwargs):
    return self._filter_or_exclude(False, args, kwargs)

def _filter_or_exclude_inplace(self, negate, args, kwargs):
    if negate:
        self._query.add_q(~Q(*args, **kwargs))
    else:
        self._query.add_q(Q(*args, **kwargs))
```

Filter calls add Q objects to the query's WhereNode. No SQL generation yet; query is lazy until iteration/execution.

---

### 3. Query Object Setup
**Path:** QuerySet.__init__() in django/db/models/query.py:280-294

```python
def __init__(self, model=None, query=None, using=None, hints=None):
    self.model = model
    self._db = using
    self._query = query or sql.Query(self.model)  # ← Creates Query object
```

QuerySet wraps a Query object that stores:
- **alias_map:** JOIN tracking (table alias → Join object)
- **where:** WhereNode tree of predicates
- **select/order_by/group_by:** Projection and sorting
- **annotations:** Named aggregates/subqueries

---

### 4. Compiler Acquisition
**Path:** Query.get_compiler() in django/db/models/sql/query.py:358-365

```python
def get_compiler(self, using=None, connection=None, elide_empty=True):
    if using is None and connection is None:
        raise ValueError("Need either using or connection")
    if using:
        connection = connections[using]
    return connection.ops.compiler(self.compiler)(\
        self, connection, using, elide_empty\
    )
```

This is the **vendor dispatch point**: connection.ops.compiler() returns the backend-specific compiler class (e.g., PostgreSQL's SQLCompiler). The Query.compiler attribute (default: "SQLCompiler") is passed to get the appropriate class.

---

### 5. Execution Path
**Path:** ModelIterable.__iter__() in django/db/models/query.py:85-91

```python
def __iter__(self):
    queryset = self.queryset
    db = queryset.db
    compiler = queryset.query.get_compiler(using=db)
    results = compiler.execute_sql(
        chunked_fetch=self.chunked_fetch, chunk_size=self.chunk_size
    )
```

When iterating over a QuerySet, it fetches the compiler and calls execute_sql().

---

### 6. SQL Compilation
**Path:** SQLCompiler.execute_sql() in django/db/models/sql/compiler.py:1592-1661

```python
def execute_sql(self, result_type=MULTI, chunked_fetch=False, chunk_size=...):
    try:
        sql, params = self.as_sql()  # ← Compile to SQL
        if not sql:
            raise EmptyResultSet
    except EmptyResultSet:
        # Handle empty results
        return iter([])

    cursor = self.connection.cursor()
    cursor.execute(sql, params)  # ← Execute SQL
    return cursor_iter(...)  # ← Return iterator over rows
```

---

### 7. SQL Generation
**Path:** SQLCompiler.as_sql() in django/db/models/sql/compiler.py:754-976

The as_sql() method orchestrates SQL building:

**a) Pre-SQL Setup (line 765-766):**
```python
extra_select, order_by, group_by = self.pre_sql_setup(with_col_aliases=...)
```
Calls setup_query() → get_select() which:
- Iterates over model fields
- Compiles each via self.compile() (vendor dispatch)
- Returns (expression, (sql, params), alias) tuples

**b) WHERE Clause (line 792-799):**
```python
where, w_params = (
    self.compile(self.where) if self.where is not None else ("", [])
)
```
Compiles the WhereNode tree using the vendor dispatch mechanism.

**c) FROM Clause (line 790):**
```python
from_, f_params = self.get_from_clause()
```
Iterates over query.alias_map and compiles each Join/table expression.

**d) SQL Assembly (line 810-976):**
Builds result list by concatenating:
- SELECT clause (with DISTINCT if needed)
- FROM clause
- WHERE clause
- GROUP BY / HAVING clauses
- ORDER BY clause
- LIMIT/OFFSET

Returns `" ".join(result), tuple(params)`.

---

### 8. Vendor-Specific Dispatch (Compiler.compile)
**Path:** SQLCompiler.compile() in django/db/models/sql/compiler.py:571-577

```python
def compile(self, node):
    vendor_impl = getattr(node, "as_" + self.connection.vendor, None)
    if vendor_impl:
        sql, params = vendor_impl(self, self.connection)
    else:
        sql, params = node.as_sql(self, self.connection)
    return sql, params
```

This is the **critical vendor dispatch mechanism**:
1. Look for as_{vendor}() method (e.g., as_postgresql, as_mysql, as_sqlite, as_oracle)
2. If found, call backend-specific implementation
3. Otherwise, fall back to generic as_sql()

This allows expressions (e.g., Case/When), lookups (e.g., Exact), and clauses (e.g., WhereNode) to provide backend-specific SQL optimizations.

---

### 9. Expression Compilation Protocol
**Path:** Expression.as_sql() in django/db/models/expressions.py:225-251

Every expression (including Lookup, Value, F, Col, CombinedExpression, etc.) implements:

```python
def as_sql(self, compiler, connection):
    """
    Return (sql, params) for this expression.

    Backend-specific implementations use as_{vendor}() method pattern.
    """
    raise NotImplementedError("Subclasses must implement as_sql()")
```

Example: **Value.as_sql()** (literal value):
```python
def as_sql(self, compiler, connection):
    return "%s", [self.value]
```

Example: **Col.as_sql()** (column reference):
```python
def as_sql(self, compiler, connection):
    return f"{compiler.quote_name_unless_alias(self.alias)}.{compiler.quote_name(self.output_field.column)}", []
```

Example: **CombinedExpression.as_sql()** (e.g., F('age') + 5):
```python
def as_sql(self, compiler, connection):
    lhs_sql, lhs_params = compiler.compile(self.lhs)
    rhs_sql, rhs_params = compiler.compile(self.rhs)
    connector = self.connector
    return f"({lhs_sql} {connector} {rhs_sql})", lhs_params + rhs_params
```

---

### 10. Lookup Compilation
**Path:** BuiltinLookup.as_sql() in django/db/models/lookups.py:256-261

Lookups (WHERE predicates) implement as_sql() by composing three parts:

```python
def as_sql(self, compiler, connection):
    lhs_sql, params = self.process_lhs(compiler, connection)
    rhs_sql, rhs_params = self.process_rhs(compiler, connection)
    params.extend(rhs_params)
    rhs_sql = self.get_rhs_op(connection, rhs_sql)  # Apply operator
    return "%s %s" % (lhs_sql, rhs_sql), params
```

**Example:** Exact lookup (WHERE field = value)

- **process_lhs()** compiles left side (Field → Col → "table.column")
- **process_rhs()** compiles right side (Value/F/etc → SQL + params)
- **get_rhs_op()** applies operator from connection.operators dict: `connection.operators['exact'] = '%s = %s'`
- **Result:** `"table.column = %s", [value_param]`

---

### 11. WhereNode Tree Compilation
**Path:** WhereNode.as_sql() in django/db/models/sql/where.py:116-200+

WhereNode is a tree of predicates connected with AND/OR/XOR:

```python
def as_sql(self, compiler, connection):
    result = []
    result_params = []

    for child in self.children:
        try:
            child_sql, child_params = compiler.compile(child)
        except EmptyResultSet:
            # Handle empty results
            pass
        else:
            result.append(child_sql)
            result_params.extend(child_params)

    # Combine with connector (AND/OR/XOR)
    if self.connector == AND:
        sql = " AND ".join(result)
    elif self.connector == OR:
        sql = " OR ".join(result)
    # ... etc

    # Apply negation
    if self.negated:
        sql = f"NOT ({sql})"

    return sql, result_params
```

**Example tree:**
```
Q(age__gt=18) & Q(name__startswith='A')
↓
WhereNode(
    connector=AND,
    children=[
        Gt(Col('age'), Value(18)),  # age > 18
        StartsWith(Col('name'), Value('A'))  # name LIKE 'A%'
    ]
)
↓
SQL: "(age > %s) AND (name LIKE %s)"
```

---

### 12. Backend-Specific Compilers
**Path:** django/db/backends/{postgresql,mysql,sqlite3}/compiler.py

Backend-specific compilers inherit from SQLCompiler and override methods:

**PostgreSQL example (django/db/backends/postgresql/compiler.py:28-50):**
```python
class SQLInsertCompiler(BaseSQLInsertCompiler):
    def assemble_as_sql(self, fields, value_rows):
        # Optimize bulk insert using UNNEST
        if conditions_for_unnest_optimization:
            return InsertUnnest(...), [params]
        else:
            return super().assemble_as_sql(fields, value_rows)
```

Backends can also override as_sql() on compilers or implement as_{vendor}() on expressions.

---

## Analysis

### Design Patterns

#### 1. **Lazy Evaluation**
QuerySet and Query objects don't execute SQL until forced by iteration, slicing, or explicit calls (.count(), .exists(), etc.). This allows efficient query chaining: `Model.objects.filter(x).filter(y).exclude(z)` makes one SQL query, not three.

#### 2. **Visitor Pattern (Compiler.compile)**
The compile() method acts as a visitor:
- Traverses expression trees (recursively)
- Dispatches each node to its as_sql() method
- Collects SQL strings and parameters

#### 3. **Vendor Dispatch via Method Naming**
```python
vendor_impl = getattr(node, "as_" + self.connection.vendor, None)
```

Each expression, lookup, and clause can provide backend-specific SQL via:
- as_postgresql()
- as_mysql()
- as_sqlite()
- as_oracle()

This decouples core logic (generic as_sql) from dialect-specific optimizations.

#### 4. **Expression Protocol**
All compilable objects implement:
```python
def as_sql(self, compiler, connection) -> (str, list):
    """Return (sql_string, parameters)"""
```

This unified interface allows arbitrary nesting and composition of expressions:
- F('field') + Value(5) creates CombinedExpression
- CombinedExpression.as_sql() calls compiler.compile() recursively on children
- Results compose into larger SQL fragments

#### 5. **Tree-Based Query Representation**
- **WhereNode:** Boolean tree (AND/OR nodes with Lookup leaves)
- **alias_map:** JOIN tree mapping aliases to Join objects
- **select:** List of Column/Expression tuples
- **annotations:** Dict of named aggregates

The compiler walks these trees, compiling each subtree to SQL, then assembles into final query.

---

### Component Responsibilities

| Component | Responsibility |
|-----------|-----------------|
| **Manager** | Entry point; routes to QuerySet |
| **QuerySet** | High-level API (filter, exclude, order_by, etc.); lazy evaluation |
| **Query** | Low-level query state (WHERE, JOINs, SELECT, GROUP BY); no SQL yet |
| **Compiler** | Orchestrates SQL generation; calls as_sql() on sub-components |
| **Expression/Lookup/WhereNode** | Generate SQL fragments; implement as_sql() protocol |
| **Backend Operations** | Dialect-specific SQL generation; quote names; operator SQL |

---

### Data Flow

```
User API:
  Author.objects.filter(age__gt=18).exclude(name='Bob')

         ↓ (calls filter)

QuerySet._filter_or_exclude_inplace():
  self._query.add_q(Q(age__gt=18))
  self._query.add_q(~Q(name='Bob'))

         ↓ (builds Query state)

Query object:
  - alias_map = {'T0': BaseTable('author')}
  - where = WhereNode([
      Gt(Col('age'), Value(18)),
      Not(Exact(Col('name'), Value('Bob')))
    ], connector='AND')
  - select = [Col('id'), Col('age'), Col('name'), ...]

         ↓ (on iteration: __iter__)

ModelIterable.__iter__():
  compiler = query.get_compiler(using=self.db)

         ↓ (get backend-specific compiler)

connection.ops.compiler('SQLCompiler')(query, connection, using)
         → PostgreSQL: <postgresql.compiler.SQLCompiler>
         → MySQL: <mysql.compiler.SQLCompiler>
         → SQLite: <sqlite3.compiler.SQLCompiler>

         ↓ (call execute_sql)

SQLCompiler.execute_sql():
  sql, params = self.as_sql()

         ↓ (orchestrate SQL building)

SQLCompiler.as_sql():
  1. setup_query() → get_select() → compile each column
  2. get_from_clause() → compile FROM
  3. compile(self.where) → compile WHERE tree
  4. Assemble: "SELECT ... FROM ... WHERE ..."

         ↓ (compile each sub-component)

compiler.compile(expression):
  vendor_impl = getattr(expression, 'as_postgresql', None)
  if vendor_impl:
      return vendor_impl(compiler, connection)
  else:
      return expression.as_sql(compiler, connection)

         ↓ (recursively compile expressions)

Expression.as_sql(compiler, connection):
  For each child expression:
      child_sql, params = compiler.compile(child)
  Combine and return (sql_fragment, params)

         ↓ (execute)

cursor.execute(sql, params)
  → Runs: "SELECT ... FROM author WHERE age > %s AND name != %s"
  → With params: [18, 'Bob']

         ↓ (iterate)

cursor.fetchmany(2000)  # Chunked reads
  → (1, 25, 'Alice'), (2, 30, 'Charlie'), ...

         ↓ (hydrate)

model_cls.from_db(db, init_list, row)
  → Author(id=1, age=25, name='Alice')
```

---

### Interface Contracts

#### Expression Protocol
All compilable objects (Expression, Lookup, WhereNode, Col, Value, F, etc.) must implement:

```python
def as_sql(self, compiler, connection):
    """
    Return (sql_string, parameter_list).

    - sql_string: SQL fragment with %s placeholders for parameters
    - parameter_list: Values to substitute (order matters)

    Can call compiler.compile(child_expr) to compile sub-expressions.
    """
```

#### Backend-Specific Override
Objects can provide vendor-specific SQL:

```python
def as_{vendor}(self, compiler, connection):
    """Backend-specific as_sql() implementation."""
    # Usually calls parent as_sql() with slight modifications
    return super().as_sql(compiler, connection)
```

#### Compiler Protocol
Compilers must provide:

```python
def compile(self, node):
    """Dispatch node.as_sql() with vendor fallback."""

def as_sql(self):
    """Generate complete SQL query."""

def execute_sql(self, result_type=MULTI):
    """Execute SQL and return results."""
```

---

## Summary

Django's ORM query compilation pipeline implements **lazy evaluation** via a **tree-based query representation** and **visitor-pattern compilation**. The key insight is the **vendor dispatch mechanism** (`as_{vendor}()` method naming), which allows backend-specific optimizations without branching core logic.

The flow is: **QuerySet API → Query tree → Compiler → Expression.as_sql() → Vendor dispatch → SQL → Cursor.execute()**.

Each layer (QuerySet, Query, Compiler, Expression, Lookup, WhereNode) has clear responsibilities and interacts through well-defined interfaces (**as_sql()** protocol), enabling composable, extensible query building and flexible backend support.
