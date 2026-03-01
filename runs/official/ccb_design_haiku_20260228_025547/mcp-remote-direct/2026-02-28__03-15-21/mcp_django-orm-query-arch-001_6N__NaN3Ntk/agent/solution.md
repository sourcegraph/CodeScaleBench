# Django ORM Query Compilation Pipeline Analysis

## Files Examined

### Core Manager and QuerySet
- **django/db/models/manager.py** — Entry point `Manager.get_queryset()` that creates a new QuerySet instance
- **django/db/models/query.py** — Main `QuerySet` class with filter(), iterator(), and query building methods

### Query Representation and Compilation
- **django/db/models/sql/query.py** — `Query` class that represents an abstract query tree; `get_compiler()` method dispatches to appropriate compiler
- **django/db/models/sql/compiler.py** — `SQLCompiler` class that generates SQL; `as_sql()` produces SELECT statements, `execute_sql()` runs the query
- **django/db/models/sql/where.py** — `WhereNode` tree structure for WHERE/HAVING/QUALIFY clauses

### Expression and Lookup System
- **django/db/models/expressions.py** — `BaseExpression`, `Expression`, `Combinable`, `Value`, `F`, `Col` classes with `as_sql()` protocol
- **django/db/models/lookups.py** — `Lookup` base class (e.g., `Exact`, `In`, `LessThan`) with vendor dispatch via `as_sql()` and `as_{vendor}()` methods

### Backend Vendor Dispatch
- **django/db/backends/base/operations.py** — Base `DatabaseOperations` with `compiler()` method that returns vendor-specific compiler classes
- **django/db/backends/postgresql/compiler.py**, **django/db/backends/mysql/compiler.py**, etc. — Vendor-specific compiler subclasses

## Dependency Chain

### 1. Entry Point: Manager and QuerySet Creation
```
Model.objects (Manager instance)
  └─> .filter(pk__gt=1)
      └─> calls QuerySet._filter_or_exclude()
          └─> QuerySet._chain() creates new QuerySet clone
          └─> calls Query.add_q(Q(...))  [Lazy: only builds query tree, doesn't compile]
```

**File**: `django/db/models/manager.py:150-155` (Manager.get_queryset)
```python
def get_queryset(self):
    return self._queryset_class(model=self.model, using=self._db, hints=self._hints)
```

**File**: `django/db/models/query.py:1475-1481` (QuerySet.filter)
```python
def filter(self, *args, **kwargs):
    self._not_support_combined_queries("filter")
    return self._filter_or_exclude(False, args, kwargs)
```

### 2. Query Building (Lazy, No SQL Yet)
```
QuerySet.filter(...).exclude(...).order_by(...)  [All methods return new QuerySet]
  └─> Stores filter conditions in Query object (abstract syntax tree)
  └─> Query object tracks:
      - where: WhereNode tree with Lookup nodes
      - annotations: Named expressions
      - select_related, prefetch_related metadata
      - order_by, group_by, distinct, slicing info
```

**File**: `django/db/models/sql/query.py:1-50` (Query class docstring)
```python
"""
Create SQL statements for QuerySets.

The code in here encapsulates all of the SQL construction so that QuerySets
themselves do not have to (and could be backed by things other than SQL
databases).
"""
```

### 3. Trigger Evaluation (When Iterator/Fetch Needed)
```
for obj in queryset:  # or .first(), .count(), etc.
  └─> Calls QuerySet._fetch_all()
      └─> Calls ModelIterable.__iter__()
          └─> queryset.query.get_compiler(using=db)  [Instantiate compiler]
```

**File**: `django/db/models/query.py:85-93` (ModelIterable.__iter__)
```python
def __iter__(self):
    queryset = self.queryset
    db = queryset.db
    compiler = queryset.query.get_compiler(using=db)
    # Execute the query. This will also fill compiler.select, klass_info,
    # and annotations.
    results = compiler.execute_sql(
        chunked_fetch=self.chunked_fetch, chunk_size=self.chunk_size
    )
```

### 4. Compiler Instantiation (Vendor Dispatch)
```
Query.get_compiler(using='default')
  └─> Gets database connection for 'default'
      └─> Calls connection.ops.compiler('SQLCompiler')
          └─> Vendor-specific compiler class lookup
              ├─> PostgreSQL → django.db.backends.postgresql.compiler.SQLCompiler
              ├─> MySQL → django.db.backends.mysql.compiler.SQLCompiler
              ├─> Oracle → django.db.backends.oracle.compiler.SQLCompiler
              └─> SQLite → django.db.models.sql.compiler.SQLCompiler (base)
          └─> Instantiates: Compiler(query, connection, using, elide_empty)
```

**File**: `django/db/models/sql/query.py:358-365` (Query.get_compiler)
```python
def get_compiler(self, using=None, connection=None, elide_empty=True):
    if using is None and connection is None:
        raise ValueError("Need either using or connection")
    if using:
        connection = connections[using]
    return connection.ops.compiler(self.compiler)(
        self, connection, using, elide_empty
    )
```

### 5. SQL Compilation (as_sql() Protocol)
```
Compiler.as_sql()  [Called once, builds full SQL statement]
  ├─> Calls pre_sql_setup()
  │   ├─> setup_query(): Initializes select list
  │   ├─> get_select(): Resolves expressions, calls compile() on each
  │   ├─> get_order_by(): Processes ORDER BY expressions
  │   └─> WhereNode.split_having_qualify(): Separates WHERE/HAVING/QUALIFY
  │
  ├─> For each expression in SELECT list:
  │   └─> Calls compiler.compile(expression)
  │       └─> Checks for as_{vendor}() method (e.g., as_postgresql)
  │           └─> Falls back to as_sql() if vendor method not found
  │           └─> Expression subclass implements as_sql(compiler, connection)
  │               └─> Recursively compiles sub-expressions
  │
  ├─> Compiles WHERE clause:
  │   └─> Calls compiler.compile(self.where)
  │       └─> WhereNode.as_sql(compiler, connection)
  │           └─> Iterates children (Lookup nodes), compiles each
  │               └─> Lookup.as_sql(compiler, connection)
  │                   ├─> Calls process_lhs() → compiler.compile(lhs)
  │                   └─> Calls process_rhs() → processes RHS value
  │
  ├─> Builds SQL string: "SELECT ... FROM ... WHERE ... ORDER BY ..."
  └─> Returns: (sql_string, params_tuple)
```

**File**: `django/db/models/sql/compiler.py:754-850` (SQLCompiler.as_sql)
```python
def as_sql(self, with_limits=True, with_col_aliases=False):
    """
    Create the SQL for this query. Return the SQL string and list of
    parameters.
    """
    extra_select, order_by, group_by = self.pre_sql_setup(
        with_col_aliases=with_col_aliases or bool(combinator),
    )
    # ... builds SELECT, FROM, WHERE, GROUP BY, HAVING, ORDER BY, LIMIT clauses
    result = ["SELECT"]
    # ... appends distinct, columns, FROM, WHERE, GROUP BY, HAVING, ORDER BY, LIMIT
    return " ".join(result), params
```

### 6. Expression Compilation (Recursive as_sql() Protocol)
```
compiler.compile(expression)
  ├─> Looks up method name: as_{connection.vendor}
  │   ├─ connection.vendor = 'postgresql', 'mysql', 'sqlite', 'oracle'
  │   └─ First tries: expression.as_postgresql(compiler, connection)
  │      Falls back to: expression.as_sql(compiler, connection)
  │
  └─> All expressions implement resolve_expression() and as_sql()
      ├─ F('field_name') → Col(table_alias, 'field_name')
      ├─ Value(42) → '%s', [42]
      ├─ Func('UPPER', F('name')) → 'UPPER(%s)', params
      └─ Lookup (e.g., pk__gt=5) → 'id > %s', [5]
          └─ Q objects combine lookups with AND/OR/XOR
```

**File**: `django/db/models/lookups.py:31-100` (Lookup class)
```python
class Lookup(Expression):
    lookup_name = None
    prepare_rhs = True

    def __init__(self, lhs, rhs):
        self.lhs, self.rhs = lhs, rhs
        self.rhs = self.get_prep_lookup()
        self.lhs = self.get_prep_lhs()
```

### 7. Execution
```
Compiler.execute_sql(result_type=MULTI)
  ├─> Calls as_sql() to get (sql_string, params)
  ├─> Gets database cursor via connection.cursor()
  ├─> Executes: cursor.execute(sql, params)
  ├─> Processes result based on result_type:
  │   ├─ MULTI: Returns iterator via cursor_iter()
  │   ├─ SINGLE: Returns first row via fetchone()
  │   ├─ ROW_COUNT: Returns cursor.rowcount
  │   └─ CURSOR: Returns raw cursor
  └─> Result set is then processed by iterables (ModelIterable, ValuesIterable, etc.)
```

**File**: `django/db/models/sql/compiler.py:1592-1650` (SQLCompiler.execute_sql)
```python
def execute_sql(self, result_type=MULTI, chunked_fetch=False, chunk_size=GET_ITERATOR_CHUNK_SIZE):
    try:
        sql, params = self.as_sql()
        if not sql:
            raise EmptyResultSet
    except EmptyResultSet:
        if result_type == MULTI:
            return iter([])

    cursor = self.connection.cursor()
    try:
        cursor.execute(sql, params)
    except Exception:
        cursor.close()
        raise

    if result_type == ROW_COUNT:
        return cursor.rowcount
    # ... handle other result types
```

## Architecture: Key Design Patterns

### 1. **Lazy Evaluation**
- QuerySet methods (filter, exclude, select_related) don't execute SQL immediately
- They return new QuerySet instances with modified Query objects
- SQL compilation only happens when the result set is accessed (iteration, slicing, count, etc.)
- Allows chaining and optimization before execution

### 2. **Vendor Dispatch Pattern (as_sql() Protocol)**
Expressions use a method resolution strategy to support database-specific SQL:
```python
# In compiler.compile(expression):
vendor = connection.vendor  # 'postgresql', 'mysql', 'sqlite', 'oracle'
method_name = f'as_{vendor}'
try:
    method = getattr(expression, method_name)
    return method(compiler, connection)
except AttributeError:
    return expression.as_sql(compiler, connection)
```

This allows expressions like `Substring()` to have:
- `as_sqlite()` — SQLite-specific syntax
- `as_mysql()` — MySQL-specific syntax
- `as_sql()` — Fallback default implementation

### 3. **Recursive Expression Tree**
- QuerySet filters build a tree of Lookup and Expression objects
- Each Lookup has `lhs` (left-hand side) and `rhs` (right-hand side)
- Expressions can be nested: F('related__field'), Case(When(...), ...),  Func('COALESCE', F('a'), Value(0))
- During SQL compilation, the tree is recursively compiled: parent calls `compiler.compile(child)`

### 4. **WhereNode Tree**
- WHERE/HAVING/QUALIFY clauses are represented as tree nodes
- `WhereNode` is a tree node with children (Lookups, sub-WhereNodes)
- Connector: AND, OR, XOR
- During compilation: `WhereNode.as_sql()` iterates children, compiles each, joins with connector
- Example: `Q(a=1) & Q(b=2) | Q(c=3)` becomes:
  ```
  WhereNode(OR, [
    WhereNode(AND, [Lookup(a=1), Lookup(b=2)]),
    Lookup(c=3)
  ])
  ```

### 5. **Compiler Object as Compilation Context**
- Compiler maintains state: `select`, `klass_info`, `annotation_col_map`
- Compiler has helper methods: `quote_name()`, `compile(expr)`, `get_order_by()`
- All expression compilation methods receive `compiler` and `connection` as parameters
- This allows expressions to access query context and call `compiler.compile()` on sub-expressions

### 6. **Backend Operations Abstraction**
- Each database backend provides `DatabaseOperations` class
- `operations.compiler()` method returns appropriate compiler class
- Compiler instances are created per-query via `Query.get_compiler()`
- Backends can override behavior for database-specific features

## Summary

The Django ORM query compilation pipeline follows a clean separation of concerns:

1. **QuerySet API Layer** — User-facing methods (filter, exclude, etc.) that construct abstract query trees
2. **Query Abstraction** — Database-agnostic representation of the query structure
3. **Compiler Layer** — Transforms Query objects into SQL strings using the recursive `as_sql()` protocol
4. **Expression/Lookup System** — Reusable SQL generation components with vendor dispatch
5. **Backend Layer** — Database-specific SQL generation and execution

The key architectural insight is the **as_sql() protocol**: every SQL-generating component (Expression, Lookup, WhereNode, etc.) implements `as_sql(compiler, connection) → (sql_string, params)` with optional vendor-specific overrides via `as_{vendor}()` methods. This design enables clean composition, testability, and database portability while maintaining flexibility for database-specific optimizations.
