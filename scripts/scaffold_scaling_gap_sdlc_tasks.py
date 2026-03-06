#!/usr/bin/env python3
"""Scaffold SDLC tasks for scaling gap coverage.

Mid-tier (500MB-1GB) tasks for suites: debug, document, refactor, secure, test
XL (>1.5GB) tasks for suites: design, document, refactor, secure, test, understand
"""

import json
import os
import shutil
import sys

REPO_ROOT = os.path.join(os.path.dirname(__file__), '..')
SGONLY_WRAPPER = os.path.join(os.path.dirname(__file__), 'sgonly_verifier_wrapper.sh')

# Suite -> benchmark dir mapping
SUITE_DIRS = {
    "debug": os.path.join(REPO_ROOT, 'benchmarks', 'csb_sdlc_debug'),
    "document": os.path.join(REPO_ROOT, 'benchmarks', 'csb_sdlc_document'),
    "refactor": os.path.join(REPO_ROOT, 'benchmarks', 'csb_sdlc_refactor'),
    "secure": os.path.join(REPO_ROOT, 'benchmarks', 'csb_sdlc_secure'),
    "test": os.path.join(REPO_ROOT, 'benchmarks', 'csb_sdlc_test'),
    "design": os.path.join(REPO_ROOT, 'benchmarks', 'csb_sdlc_design'),
    "understand": os.path.join(REPO_ROOT, 'benchmarks', 'csb_sdlc_understand'),
}

# ── Mid-tier tasks (500MB - 1GB repos) ──────────────────────────────────

MIDTIER_TASKS = [
    {
        "id": "tidb-query-plan-regression-debug-001",
        "suite": "debug",
        "repo": "pingcap/tidb",
        "mirror": "sg-evals/tidb--v8.5.0",
        "language": "go",
        "category": "debug",
        "difficulty": "hard",
        "time_limit_sec": 1200,
        "build_timeout_sec": 900,
        "description": "Debug a query plan regression in TiDB's cost-based optimizer",
        "instruction": """# Task: Debug Query Plan Regression in TiDB Cost-Based Optimizer

## Background
A user reports that after upgrading TiDB, a query that previously used an index scan is now doing a full table scan. The query involves a JOIN between two tables with a WHERE clause on an indexed column.

## Objective
Investigate the cost model in TiDB's query optimizer to identify which component could cause a plan regression where an IndexScan is replaced by a TableFullScan.

## Steps
1. Find the cost model implementation in `pkg/planner/core/` that computes the cost of IndexScan vs TableFullScan
2. Identify the `Stats` struct and how row count estimates feed into the cost calculation
3. Locate where the optimizer compares candidate plans and selects the cheapest
4. Create a file `debug_report.md` in `/workspace/` documenting:
   - The file paths and functions responsible for cost calculation of IndexScan
   - The file paths and functions responsible for cost calculation of TableFullScan
   - The comparison logic that picks the final plan
   - A hypothesis for what parameter change could cause the regression

## Key Reference Files
- `pkg/planner/core/` — optimizer core
- `pkg/planner/cardinality/` — cardinality estimation
- `pkg/statistics/` — statistics framework

## Success Criteria
- debug_report.md exists and contains the relevant file paths
- Report identifies cost model functions for both scan types
- Report includes a plausible regression hypothesis
""",
        "claude_md": """# tidb-query-plan-regression-debug-001

## Task Type: Debug (Query Plan Regression)
Investigate TiDB cost-based optimizer for plan regression root cause.

## Key Directories
- pkg/planner/core/ — optimizer, plan generation
- pkg/planner/cardinality/ — row count estimation
- pkg/statistics/ — stats collection and caching
""",
        "checks": [
            ("file_exists", "debug_report.md", "Debug report exists"),
            ("contains", "debug_report.md", "IndexScan\\|indexScan\\|IndexLookUp", "Report mentions IndexScan"),
            ("contains", "debug_report.md", "TableFullScan\\|tableScan\\|TableScan", "Report mentions TableFullScan"),
            ("contains", "debug_report.md", "cost\\|Cost", "Report discusses cost model"),
            ("contains", "debug_report.md", "pkg/planner", "Report references planner package"),
            ("contains", "debug_report.md", "hypothesis\\|Hypothesis\\|cause\\|Cause\\|regression\\|Regression", "Report includes hypothesis"),
        ],
    },
    {
        "id": "grpc-channel-api-docgen-001",
        "suite": "document",
        "repo": "grpc/grpc",
        "mirror": "sg-evals/grpc--v1.68.0",
        "language": "cpp",
        "category": "document",
        "difficulty": "hard",
        "time_limit_sec": 1200,
        "build_timeout_sec": 900,
        "description": "Generate API documentation for gRPC C++ Channel and Stub creation",
        "instruction": """# Task: Generate API Documentation for gRPC C++ Channel Creation

## Objective
Create comprehensive API documentation for the gRPC C++ channel creation and stub instantiation APIs, targeting developers who need to create gRPC clients.

## Steps
1. Find the public C++ headers for channel creation in `include/grpcpp/`
2. Identify the `CreateChannel`, `CreateCustomChannel` factory functions
3. Find the `ChannelCredentials` class hierarchy
4. Document the `ChannelArguments` configuration class
5. Create `docs/api_channel_creation.md` in `/workspace/` with:
   - Overview of channel creation patterns
   - Function signatures with parameter descriptions
   - Credential types (Insecure, SSL, Composite)
   - Channel arguments table with common options
   - Code examples for each credential type

## Key Reference Files
- `include/grpcpp/create_channel.h` — channel factory
- `include/grpcpp/security/credentials.h` — credential types
- `include/grpcpp/support/channel_arguments.h` — channel config

## Success Criteria
- docs/api_channel_creation.md exists
- Documents CreateChannel and CreateCustomChannel signatures
- Covers at least 3 credential types
- Includes channel arguments
""",
        "claude_md": """# grpc-channel-api-docgen-001

## Task Type: Document (API Reference)
Generate API docs for gRPC C++ channel creation APIs.

## Key Files
- include/grpcpp/create_channel.h
- include/grpcpp/security/credentials.h
- include/grpcpp/support/channel_arguments.h
""",
        "checks": [
            ("file_exists", "docs/api_channel_creation.md", "API doc file exists"),
            ("contains", "docs/api_channel_creation.md", "CreateChannel", "Documents CreateChannel"),
            ("contains", "docs/api_channel_creation.md", "CreateCustomChannel\\|CustomChannel", "Documents CreateCustomChannel"),
            ("contains", "docs/api_channel_creation.md", "ChannelCredentials\\|credentials", "Covers credentials"),
            ("contains", "docs/api_channel_creation.md", "InsecureChannelCredentials\\|SslCredentials\\|insecure\\|ssl\\|SSL", "Covers credential types"),
            ("contains", "docs/api_channel_creation.md", "ChannelArguments\\|channel_arguments\\|arguments", "Covers channel arguments"),
        ],
    },
    {
        "id": "beam-pipeline-builder-refac-001",
        "suite": "refactor",
        "repo": "apache/beam",
        "mirror": "sg-evals/beam--v2.62.0",
        "language": "java",
        "category": "refactor",
        "difficulty": "hard",
        "time_limit_sec": 1200,
        "build_timeout_sec": 900,
        "description": "Refactor Apache Beam PipelineOptions validation to use the Builder pattern",
        "instruction": """# Task: Refactor PipelineOptions Validation in Apache Beam

## Background
The PipelineOptions validation in Apache Beam is scattered across multiple locations. This task consolidates validation into a dedicated validator class using the Builder pattern.

## Objective
Create a `PipelineOptionsValidator` class that centralizes validation for PipelineOptions, replacing scattered validation calls.

## Steps
1. Study the existing PipelineOptions interface in `sdks/java/core/src/main/java/org/apache/beam/sdk/options/`
2. Identify validation logic in `PipelineOptionsFactory` and `PipelineOptionsValidator` (if exists)
3. Create `/workspace/sdks/java/core/src/main/java/org/apache/beam/sdk/options/PipelineOptionsValidator.java` with:
   - A Builder that accumulates validation rules
   - Methods: `validateRequired()`, `validateType()`, `validateRange()`
   - A `validate()` method that runs all accumulated rules and returns a `ValidationResult`
4. Create a `ValidationResult` class that holds errors and warnings
5. Create a test file for the validator

## Key Reference Files
- `sdks/java/core/src/main/java/org/apache/beam/sdk/options/PipelineOptions.java`
- `sdks/java/core/src/main/java/org/apache/beam/sdk/options/PipelineOptionsFactory.java`

## Success Criteria
- PipelineOptionsValidator.java exists with Builder pattern
- ValidationResult class exists
- Test file exists
- Validator has validateRequired, validateType, and validate methods
""",
        "claude_md": """# beam-pipeline-builder-refac-001

## Task Type: Refactor (Builder Pattern)
Refactor PipelineOptions validation to use Builder pattern.

## Key Directories
- sdks/java/core/src/main/java/org/apache/beam/sdk/options/
""",
        "checks": [
            ("file_exists", "sdks/java/core/src/main/java/org/apache/beam/sdk/options/PipelineOptionsValidator.java", "Validator file exists"),
            ("contains", "sdks/java/core/src/main/java/org/apache/beam/sdk/options/PipelineOptionsValidator.java", "class PipelineOptionsValidator", "Validator class defined"),
            ("contains", "sdks/java/core/src/main/java/org/apache/beam/sdk/options/PipelineOptionsValidator.java", "Builder\\|builder", "Uses Builder pattern"),
            ("contains", "sdks/java/core/src/main/java/org/apache/beam/sdk/options/PipelineOptionsValidator.java", "validateRequired\\|validateType\\|validate", "Has validation methods"),
            ("grep_recursive", "sdks/java/core/src/main/java/org/apache/beam/sdk/options/", "ValidationResult", "ValidationResult class referenced"),
            ("grep_recursive", "sdks/java/core/src/test/", "PipelineOptionsValidator\\|pipeline_options_validator", "Test file references validator"),
        ],
    },
    {
        "id": "ceph-rgw-auth-secure-001",
        "suite": "secure",
        "repo": "ceph/ceph",
        "mirror": "sg-evals/ceph--v19.2.1",
        "language": "cpp",
        "category": "secure",
        "difficulty": "hard",
        "time_limit_sec": 1200,
        "build_timeout_sec": 900,
        "description": "Audit and harden S3 authentication in Ceph RADOS Gateway",
        "instruction": """# Task: Security Audit of Ceph RADOS Gateway S3 Authentication

## Objective
Perform a security audit of the S3 authentication implementation in Ceph's RADOS Gateway (RGW) and create a findings report with remediation recommendations.

## Steps
1. Find the S3 authentication implementation in `src/rgw/` (look for AWS Signature V4 handling)
2. Identify the request signing and verification flow
3. Check for common S3 auth vulnerabilities:
   - Signature version fallback (V2 vs V4)
   - Timing attacks in signature comparison
   - Request replay prevention (timestamp validation window)
   - Secret key storage and access patterns
4. Create `security_audit.md` in `/workspace/` documenting:
   - Authentication flow overview (file paths and key functions)
   - Each finding with severity, description, file location, and remediation
   - At least 3 specific findings with code references
   - Summary risk assessment

## Key Reference Files
- `src/rgw/rgw_auth_s3.h` and `src/rgw/rgw_auth_s3.cc` — S3 auth
- `src/rgw/rgw_rest_s3.cc` — S3 REST handler
- `src/rgw/rgw_auth.h` — auth framework

## Success Criteria
- security_audit.md exists
- Contains file paths from src/rgw/
- Identifies at least 3 security findings
- Includes remediation recommendations
""",
        "claude_md": """# ceph-rgw-auth-secure-001

## Task Type: Security Audit
Audit S3 authentication in Ceph RADOS Gateway.

## Key Directories
- src/rgw/ — RADOS Gateway implementation
- src/rgw/rgw_auth_s3.* — S3 auth specifically
""",
        "checks": [
            ("file_exists", "security_audit.md", "Security audit report exists"),
            ("contains", "security_audit.md", "src/rgw", "Report references RGW source"),
            ("contains", "security_audit.md", "auth\\|Auth\\|authentication\\|Authentication", "Report covers authentication"),
            ("contains", "security_audit.md", "finding\\|Finding\\|vulnerability\\|Vulnerability\\|FINDING", "Report lists findings"),
            ("contains", "security_audit.md", "remediation\\|Remediation\\|recommendation\\|Recommendation\\|mitigation\\|Mitigation", "Report includes remediations"),
            ("contains", "security_audit.md", "signature\\|Signature\\|signing\\|Signing\\|V4\\|v4", "Report covers signature verification"),
        ],
    },
    {
        "id": "bazel-starlark-eval-test-001",
        "suite": "test",
        "repo": "bazelbuild/bazel",
        "mirror": "sg-evals/bazel--8.0.0",
        "language": "java",
        "category": "test",
        "difficulty": "hard",
        "time_limit_sec": 1200,
        "build_timeout_sec": 900,
        "description": "Write unit tests for Bazel Starlark evaluation of BUILD file rule() calls",
        "instruction": """# Task: Write Unit Tests for Bazel Starlark Rule Evaluation

## Objective
Write comprehensive unit tests for the Starlark evaluation of rule() calls in BUILD files, covering rule instantiation, attribute validation, and error handling.

## Steps
1. Study the Starlark rule evaluation in `src/main/java/com/google/devtools/build/lib/packages/`
2. Understand how `RuleClass` and `RuleFactory` process rule() calls
3. Study existing tests in `src/test/java/com/google/devtools/build/lib/packages/`
4. Create a test file `StarlarkRuleEvalTest.java` in the test directory with tests for:
   - Basic rule instantiation with required attributes
   - Missing required attribute produces error
   - Attribute type validation (string vs list vs label)
   - Default attribute values are applied
   - Visibility attribute handling
   - Rule name validation (valid and invalid names)

## Key Reference Files
- `src/main/java/com/google/devtools/build/lib/packages/RuleClass.java`
- `src/main/java/com/google/devtools/build/lib/packages/RuleFactory.java`
- `src/test/java/com/google/devtools/build/lib/packages/` — existing tests

## Success Criteria
- Test file exists in the test directory
- Tests cover rule instantiation
- Tests cover attribute validation
- Tests cover error cases
""",
        "claude_md": """# bazel-starlark-eval-test-001

## Task Type: Test (Unit Tests)
Write unit tests for Bazel Starlark rule() evaluation.

## Key Directories
- src/main/java/com/google/devtools/build/lib/packages/
- src/test/java/com/google/devtools/build/lib/packages/
""",
        "checks": [
            ("grep_recursive", "src/test/java/com/google/devtools/build/lib/packages/", "StarlarkRuleEval\\|starlarkRuleEval\\|RuleEvalTest", "Test file exists in packages test dir"),
            ("grep_recursive", "src/test/java/", "class.*StarlarkRuleEval\\|class.*RuleEvalTest", "Test class defined"),
            ("grep_recursive", "src/test/java/", "@Test.*\\|void test.*Rule\\|void.*ruleInstantiation\\|void.*ruleEval", "Has @Test methods for rules"),
            ("grep_recursive", "src/test/java/", "RuleClass\\|RuleFactory\\|ruleClass", "Tests reference RuleClass or RuleFactory"),
            ("grep_recursive", "src/test/java/", "attribute\\|Attribute\\|required\\|mandatory", "Tests cover attribute validation"),
            ("grep_recursive", "src/test/java/", "error\\|Error\\|exception\\|Exception\\|assertThrows\\|fail", "Tests cover error cases"),
        ],
    },
]

# ── XL tasks (>1.5GB repos) ─────────────────────────────────────────────

XL_TASKS = [
    {
        "id": "elasticsearch-shard-alloc-design-001",
        "suite": "design",
        "repo": "elastic/elasticsearch",
        "mirror": "sg-evals/elasticsearch--v8.17.0",
        "language": "java",
        "category": "design",
        "difficulty": "hard",
        "time_limit_sec": 1800,
        "build_timeout_sec": 1200,
        "description": "Design a priority-based shard allocation strategy for Elasticsearch",
        "instruction": """# Task: Design a Priority-Based Shard Allocation Strategy

## Background
Elasticsearch's shard allocation balances shards across nodes, but doesn't support priority-based allocation where critical indices get preferred placement on faster nodes.

## Objective
Design a new `PriorityShardsAllocator` that extends the existing allocation framework to support index-priority-aware shard placement.

## Steps
1. Study the existing shard allocation in `server/src/main/java/org/elasticsearch/cluster/routing/allocation/`
2. Understand the `ShardsAllocator` interface and `BalancedShardsAllocator`
3. Study `AllocationDeciders` and how decisions compose
4. Create a design document `design_doc.md` in `/workspace/` with:
   - Architecture overview of current allocation
   - Proposed PriorityShardsAllocator class design
   - New `AllocationDecider` for priority constraints
   - Index setting for priority level (`index.routing.allocation.priority`)
   - Interaction with existing deciders (DiskThresholdDecider, AwarenessAllocationDecider)
   - API changes needed
5. Create a skeleton Java file `PriorityShardsAllocator.java` showing the class structure

## Key Reference Files
- `server/src/main/java/org/elasticsearch/cluster/routing/allocation/allocator/BalancedShardsAllocator.java`
- `server/src/main/java/org/elasticsearch/cluster/routing/allocation/allocator/ShardsAllocator.java`
- `server/src/main/java/org/elasticsearch/cluster/routing/allocation/decider/AllocationDeciders.java`

## Success Criteria
- Design doc exists with architecture overview
- Skeleton Java file exists
- Design references existing allocation classes
- Includes interaction with existing deciders
""",
        "claude_md": """# elasticsearch-shard-alloc-design-001

## Task Type: Design (Architecture)
Design priority-based shard allocation for Elasticsearch.

## Key Directories
- server/src/main/java/org/elasticsearch/cluster/routing/allocation/
""",
        "checks": [
            ("file_exists", "design_doc.md", "Design document exists"),
            ("contains", "design_doc.md", "PriorityShardsAllocator\\|priority.*alloc", "Design names the new allocator"),
            ("contains", "design_doc.md", "BalancedShardsAllocator\\|ShardsAllocator", "References existing allocator"),
            ("contains", "design_doc.md", "AllocationDecider\\|decider\\|Decider", "Covers allocation deciders"),
            ("contains", "design_doc.md", "index.routing\\|priority", "Defines priority setting"),
            ("grep_recursive", ".", "class PriorityShardsAllocator\\|class.*PriorityAlloc", "Skeleton Java class exists"),
        ],
    },
    {
        "id": "godot-gdscript-api-docgen-001",
        "suite": "document",
        "repo": "godotengine/godot",
        "mirror": "sg-evals/godot--4.3-stable",
        "language": "cpp",
        "category": "document",
        "difficulty": "hard",
        "time_limit_sec": 1800,
        "build_timeout_sec": 1200,
        "description": "Document the GDScript virtual machine bytecode instruction set",
        "instruction": """# Task: Document GDScript VM Bytecode Instruction Set

## Objective
Create internal developer documentation for the GDScript virtual machine bytecode instruction set, covering opcode definitions, operand formats, and execution semantics.

## Steps
1. Find the GDScript VM implementation in `modules/gdscript/`
2. Identify the opcode definitions (likely an enum in a header file)
3. Study the bytecode interpreter dispatch loop
4. Study the compiler that generates bytecodes
5. Create `docs/gdscript_vm_reference.md` in `/workspace/` with:
   - VM architecture overview (stack-based vs register-based)
   - Complete opcode table with categories (arithmetic, control flow, member access, calls)
   - Operand format for each instruction category
   - Function call convention (how arguments are passed)
   - Local variable and member variable access patterns
   - Type system interaction (Variant types)

## Key Reference Files
- `modules/gdscript/gdscript_vm.cpp` — VM interpreter
- `modules/gdscript/gdscript_compiler.cpp` — bytecode generation
- `modules/gdscript/gdscript_function.h` — opcode definitions

## Success Criteria
- docs/gdscript_vm_reference.md exists
- Covers opcode categories
- Documents function call convention
- References actual source files
""",
        "claude_md": """# godot-gdscript-api-docgen-001

## Task Type: Document (Internal Reference)
Document the GDScript VM bytecode instruction set.

## Key Files
- modules/gdscript/gdscript_vm.cpp
- modules/gdscript/gdscript_compiler.cpp
- modules/gdscript/gdscript_function.h
""",
        "checks": [
            ("file_exists", "docs/gdscript_vm_reference.md", "VM reference doc exists"),
            ("contains", "docs/gdscript_vm_reference.md", "opcode\\|Opcode\\|OPCODE", "Documents opcodes"),
            ("contains", "docs/gdscript_vm_reference.md", "stack\\|Stack\\|register\\|Register", "Describes VM architecture"),
            ("contains", "docs/gdscript_vm_reference.md", "call\\|Call\\|function.*call\\|CALL", "Covers function calls"),
            ("contains", "docs/gdscript_vm_reference.md", "modules/gdscript", "References source files"),
            ("contains", "docs/gdscript_vm_reference.md", "Variant\\|variant\\|type", "Covers type system"),
        ],
    },
    {
        "id": "roslyn-symbol-resolver-refac-001",
        "suite": "refactor",
        "repo": "dotnet/roslyn",
        "mirror": "sg-evals/roslyn--v4.12.0",
        "language": "csharp",
        "category": "refactor",
        "difficulty": "hard",
        "time_limit_sec": 1800,
        "build_timeout_sec": 1200,
        "description": "Refactor Roslyn symbol lookup to use a unified resolution strategy",
        "instruction": """# Task: Refactor Roslyn Symbol Lookup to Unified Resolution Strategy

## Background
Roslyn's symbol lookup has separate code paths for different contexts (expression binding, type resolution, member access). This task extracts common patterns into a shared strategy.

## Objective
Create a `UnifiedSymbolResolver` that consolidates the common symbol lookup patterns used across different binding contexts.

## Steps
1. Study symbol resolution in `src/Compilers/CSharp/Portable/Binder/`
2. Identify common patterns in `Binder.LookupSymbolsInSingleBinder`, `Binder_Lookup.cs`, and type resolution
3. Create `src/Compilers/CSharp/Portable/Binder/UnifiedSymbolResolver.cs` with:
   - A strategy interface `ISymbolResolutionStrategy`
   - Concrete strategies for: TypeResolution, MemberAccess, NamespaceResolution
   - A `Resolve()` method that walks scope chains using the strategy
   - Results type that captures both found symbols and diagnostics
4. Create a test file in the test directory

## Key Reference Files
- `src/Compilers/CSharp/Portable/Binder/Binder_Lookup.cs`
- `src/Compilers/CSharp/Portable/Binder/Binder.cs`
- `src/Compilers/CSharp/Portable/Symbols/` — symbol types

## Success Criteria
- UnifiedSymbolResolver.cs exists
- Defines ISymbolResolutionStrategy interface
- Has concrete strategy implementations
- Test file exists
""",
        "claude_md": """# roslyn-symbol-resolver-refac-001

## Task Type: Refactor (Strategy Pattern)
Extract unified symbol resolution strategy from Roslyn binder.

## Key Directories
- src/Compilers/CSharp/Portable/Binder/
- src/Compilers/CSharp/Portable/Symbols/
""",
        "checks": [
            ("file_exists", "src/Compilers/CSharp/Portable/Binder/UnifiedSymbolResolver.cs", "Resolver file exists"),
            ("contains", "src/Compilers/CSharp/Portable/Binder/UnifiedSymbolResolver.cs", "class UnifiedSymbolResolver\\|UnifiedSymbolResolver", "Resolver class defined"),
            ("contains", "src/Compilers/CSharp/Portable/Binder/UnifiedSymbolResolver.cs", "ISymbolResolutionStrategy\\|interface.*Strategy", "Strategy interface defined"),
            ("contains", "src/Compilers/CSharp/Portable/Binder/UnifiedSymbolResolver.cs", "Resolve\\|resolve", "Has Resolve method"),
            ("grep_recursive", "src/Compilers/CSharp/", "TypeResolution\\|MemberAccess\\|NamespaceResolution", "Has concrete strategies"),
            ("grep_recursive", "src/Compilers/CSharp/Test/", "UnifiedSymbolResolver\\|SymbolResolver", "Test file references resolver"),
        ],
    },
    {
        "id": "typescript-type-narrowing-secure-001",
        "suite": "secure",
        "repo": "microsoft/TypeScript",
        "mirror": "sg-evals/TypeScript--v5.7.2",
        "language": "typescript",
        "category": "secure",
        "difficulty": "hard",
        "time_limit_sec": 1800,
        "build_timeout_sec": 1200,
        "description": "Security review of TypeScript compiler type narrowing for unsound patterns",
        "instruction": """# Task: Security Review of TypeScript Type Narrowing

## Objective
Review the TypeScript compiler's type narrowing implementation for patterns that could lead to unsound type assertions, enabling developers to bypass type safety unknowingly.

## Steps
1. Find the type narrowing implementation in `src/compiler/checker.ts`
2. Identify the narrowing functions (narrowType, narrowTypeByGuard, narrowTypeByTypeof, etc.)
3. Analyze potential unsoundness in:
   - typeof narrowing with user-defined type guards
   - Discriminated union narrowing edge cases
   - Control flow analysis across function boundaries
   - Type assertion vs type narrowing interaction
4. Create `security_review.md` in `/workspace/` documenting:
   - Overview of the narrowing architecture (file paths and functions)
   - At least 3 patterns where narrowing could produce unsound types
   - TypeScript code examples demonstrating each pattern
   - Severity assessment for each finding
   - Recommendations for stricter narrowing

## Key Reference Files
- `src/compiler/checker.ts` — main type checker with narrowing
- `src/compiler/types.ts` — type system definitions
- `src/compiler/utilities.ts` — helper functions

## Success Criteria
- security_review.md exists
- Identifies specific narrowing functions
- Documents at least 3 unsound patterns
- Includes TypeScript code examples
""",
        "claude_md": """# typescript-type-narrowing-secure-001

## Task Type: Security Review
Review TypeScript type narrowing for unsoundness.

## Key Files
- src/compiler/checker.ts — type checker
- src/compiler/types.ts — type definitions
""",
        "checks": [
            ("file_exists", "security_review.md", "Security review exists"),
            ("contains", "security_review.md", "narrowType\\|narrowing\\|Narrowing\\|narrow", "Discusses type narrowing"),
            ("contains", "security_review.md", "checker.ts\\|src/compiler", "References compiler source"),
            ("contains", "security_review.md", "unsound\\|Unsound\\|unsafe\\|bypass\\|soundness", "Identifies unsoundness"),
            ("contains", "security_review.md", "typeof\\|discriminated\\|type guard\\|TypeGuard", "Covers specific narrowing patterns"),
            ("contains", "security_review.md", "example\\|Example\\|```", "Includes code examples"),
        ],
    },
    {
        "id": "cockroach-kv-txn-test-001",
        "suite": "test",
        "repo": "cockroachdb/cockroach",
        "mirror": "sg-evals/cockroach--v24.3.0",
        "language": "go",
        "category": "test",
        "difficulty": "hard",
        "time_limit_sec": 1800,
        "build_timeout_sec": 1200,
        "description": "Write tests for CockroachDB KV transaction conflict resolution",
        "instruction": """# Task: Write Tests for CockroachDB KV Transaction Conflict Resolution

## Objective
Write unit tests for the transaction conflict resolution logic in CockroachDB's KV layer, covering write-write conflicts, read-write conflicts, and deadlock detection.

## Steps
1. Study the transaction conflict handling in `pkg/kv/kvserver/concurrency/`
2. Understand the `LockTable` and `ConcurrencyManager` interfaces
3. Study the `TxnWaitQueue` or equivalent conflict resolution mechanism
4. Create a test file in `pkg/kv/kvserver/concurrency/` with tests for:
   - Write-write conflict detection between two transactions
   - Read-write conflict with different isolation levels
   - Deadlock detection with two transactions waiting on each other
   - Transaction priority-based conflict resolution
   - Lock acquisition timeout behavior
   - Intent resolution after transaction commit/abort

## Key Reference Files
- `pkg/kv/kvserver/concurrency/concurrency_manager.go`
- `pkg/kv/kvserver/concurrency/lock_table.go`
- `pkg/kv/kvserver/concurrency/` — existing tests as pattern

## Success Criteria
- Test file exists in the concurrency package
- Tests cover write-write conflicts
- Tests cover deadlock scenarios
- Tests reference ConcurrencyManager or LockTable
""",
        "claude_md": """# cockroach-kv-txn-test-001

## Task Type: Test (Unit Tests)
Write tests for CockroachDB KV transaction conflict resolution.

## Key Directories
- pkg/kv/kvserver/concurrency/ — concurrency control
- pkg/kv/kvserver/ — KV server layer
""",
        "checks": [
            ("grep_recursive", "pkg/kv/kvserver/concurrency/", "func Test.*Conflict\\|func Test.*Transaction\\|func Test.*Lock\\|func Test.*Deadlock", "Test functions defined"),
            ("grep_recursive", "pkg/kv/kvserver/concurrency/", "testing.T\\|*testing.T", "Uses Go testing framework"),
            ("grep_recursive", "pkg/kv/kvserver/concurrency/", "write.*conflict\\|Write.*Conflict\\|WriteWrite\\|write-write", "Tests write-write conflicts"),
            ("grep_recursive", "pkg/kv/kvserver/concurrency/", "deadlock\\|Deadlock\\|dead_lock", "Tests deadlock detection"),
            ("grep_recursive", "pkg/kv/kvserver/concurrency/", "LockTable\\|ConcurrencyManager\\|lockTable\\|concurrencyManager", "References core types"),
            ("grep_recursive", "pkg/kv/kvserver/concurrency/", "priority\\|Priority\\|isolation\\|Isolation", "Tests priority or isolation"),
        ],
    },
    {
        "id": "clickhouse-mergetree-arch-understand-001",
        "suite": "understand",
        "repo": "ClickHouse/ClickHouse",
        "mirror": "sg-evals/ClickHouse--v24.12",
        "language": "cpp",
        "category": "understand",
        "difficulty": "hard",
        "time_limit_sec": 1800,
        "build_timeout_sec": 1200,
        "description": "Analyze and document the MergeTree storage engine architecture in ClickHouse",
        "instruction": """# Task: Understand ClickHouse MergeTree Storage Engine Architecture

## Objective
Produce a comprehensive architecture analysis of the MergeTree storage engine, the core table engine in ClickHouse, covering its data organization, merge process, and query execution path.

## Steps
1. Find the MergeTree implementation in `src/Storages/MergeTree/`
2. Trace the write path: how INSERTs create new data parts
3. Trace the merge path: how background merges combine parts
4. Trace the read path: how SELECT queries scan parts with index skipping
5. Create `architecture_analysis.md` in `/workspace/` documenting:
   - High-level MergeTree architecture diagram (text-based)
   - Data part structure (columns, marks, primary index, skip indices)
   - Write path: from INSERT to committed part
   - Merge path: merge selection, merge algorithm, part replacement
   - Read path: part pruning, mark selection, column reading
   - Key source files with their roles
   - At least 10 specific file paths referenced

## Key Reference Files
- `src/Storages/MergeTree/MergeTreeData.h` — base class
- `src/Storages/MergeTree/MergeTreeDataWriter.cpp` — write path
- `src/Storages/MergeTree/MergeTreeDataMergerMutator.cpp` — merge logic
- `src/Storages/MergeTree/MergeTreeDataSelectExecutor.cpp` — read path

## Success Criteria
- architecture_analysis.md exists
- Covers write, merge, and read paths
- References at least 10 specific source files
- Describes data part structure
""",
        "claude_md": """# clickhouse-mergetree-arch-understand-001

## Task Type: Understand (Architecture Analysis)
Analyze MergeTree storage engine architecture in ClickHouse.

## Key Directories
- src/Storages/MergeTree/ — MergeTree engine implementation
""",
        "checks": [
            ("file_exists", "architecture_analysis.md", "Architecture analysis exists"),
            ("contains", "architecture_analysis.md", "MergeTree\\|mergetree", "Covers MergeTree"),
            ("contains", "architecture_analysis.md", "INSERT\\|insert\\|write path\\|Write Path", "Covers write path"),
            ("contains", "architecture_analysis.md", "merge\\|Merge\\|background", "Covers merge path"),
            ("contains", "architecture_analysis.md", "SELECT\\|select\\|read path\\|Read Path\\|query", "Covers read path"),
            ("contains", "architecture_analysis.md", "MergeTreeData\\|MergeTreeDataWriter\\|MergeTreeDataMerger\\|MergeTreeDataSelect", "References key classes"),
            ("contains", "architecture_analysis.md", "part\\|Part\\|data part\\|DataPart", "Describes data parts"),
            ("contains", "architecture_analysis.md", "src/Storages/MergeTree", "References source directory"),
        ],
    },
]

ALL_TASKS = MIDTIER_TASKS + XL_TASKS


def generate_test_sh(task):
    """Generate test.sh for a task."""
    checks = task["checks"]
    total = len(checks)

    lines = [
        '#!/bin/bash',
        'set -euo pipefail',
        '',
        '[ -f /tmp/.sg_only_mode ] && [ -f /tests/sgonly_verifier_wrapper.sh ] && source /tests/sgonly_verifier_wrapper.sh',
        '',
        'SCORE=0',
        f'TOTAL={total}',
        'WORKSPACE="${VERIFY_REPO:-/workspace}"',
        '',
    ]

    for i, (check_type, *args) in enumerate(checks, 1):
        description = args[-1]
        lines.append(f'# Check {i}: {description}')

        if check_type == "file_exists":
            path = args[0]
            lines.append(f'if [ -f "$WORKSPACE/{path}" ]; then')
        elif check_type == "contains":
            path, pattern = args[0], args[1]
            lines.append(f"if grep -q '{pattern}' \"$WORKSPACE/{path}\" 2>/dev/null; then")
        elif check_type in ("grep_recursive", "grep_any"):
            path, pattern = args[0], args[1]
            lines.append(f"if grep -rq '{pattern}' \"$WORKSPACE/{path}\" 2>/dev/null; then")
        elif check_type == "contains_any":
            path, pattern = args[0], args[1]
            lines.append(f"if grep -rqE '{pattern}' \"$WORKSPACE/{path}\" 2>/dev/null; then")
        elif check_type == "file_pattern":
            pattern = args[0]
            lines.append(f'if ls $WORKSPACE/{pattern} 1>/dev/null 2>&1; then')

        lines.append('    SCORE=$((SCORE + 1))')
        lines.append(f'    echo "PASS: {description}"')
        lines.append('else')
        lines.append(f'    echo "FAIL: {description}"')
        lines.append('fi')
        lines.append('')

    lines.extend([
        'echo ""',
        'echo "Score: $SCORE / $TOTAL"',
        '',
        'mkdir -p /logs/verifier',
        'python3 -c "print($SCORE / $TOTAL)" > /logs/verifier/reward.txt',
    ])

    return '\n'.join(lines) + '\n'


def generate_task_toml(task):
    """Generate task.toml."""
    return f'''version = "1.0"

[metadata]
name = "{task['id']}"
description = "{task['description']}"
license = "Apache-2.0"
author_name = "CodeScaleBench"
author_email = "ccb@example.com"

[task]
id = "{task['id']}"
repo = "{task['repo']}"
category = "{task['category']}"
language = "{task['language']}"
difficulty = "{task['difficulty']}"
time_limit_sec = {task['time_limit_sec']}

[verification]
type = "test"
command = "bash /tests/test.sh"
reward_type = "checklist"
description = "Checks task completion: file existence, content validation, pattern matching"

[environment]
build_timeout_sec = {task['build_timeout_sec']}.0
cpus = 4
memory = "8G"
storage = "20G"

[environment.setup_scripts]
mcp_config = \'\'\'
#!/bin/bash
echo "Sourcegraph MCP available for code search"
\'\'\'
'''


def generate_dockerfile(task):
    """Generate baseline Dockerfile."""
    return f'''FROM ubuntu:22.04

ENV DEBIAN_FRONTEND=noninteractive

RUN apt-get update && apt-get install -y --no-install-recommends \\
    git ca-certificates python3 curl \\
    && rm -rf /var/lib/apt/lists/*

# Pre-create claude user
RUN (adduser --disabled-password --gecos '' claude 2>/dev/null || true)

# Clone repo as claude user
USER claude
WORKDIR /workspace
RUN git clone --depth 1 https://github.com/{task['repo']}.git . || \\
    (git init && git config user.email "agent@example.com" && git config user.name "Agent")
USER root

RUN mkdir -p /logs/agent /logs/verifier && \\
    chown -R claude:claude /logs

ENTRYPOINT []
'''


def generate_dockerfile_sg_only(task):
    """Generate Dockerfile.sg_only for MCP-only mode."""
    return f'''FROM ubuntu:22.04

ENV SOURCEGRAPH_REPO_NAME={task['mirror']}
ENV DEBIAN_FRONTEND=noninteractive

RUN apt-get update && apt-get install -y --no-install-recommends \\
    git ca-certificates python3 curl \\
    && rm -rf /var/lib/apt/lists/*

WORKDIR /workspace

RUN git init && \\
    git config user.email "agent@example.com" && \\
    git config user.name "Agent"

RUN mkdir -p /logs/agent /logs/verifier

RUN touch /tmp/.sg_only_mode

RUN (adduser --disabled-password --gecos '' claude 2>/dev/null || true) && \\
    for d in /workspace /logs; do [ -d "$d" ] && chown -R claude:claude "$d"; done || true

ENTRYPOINT []
'''


def generate_ground_truth(task):
    """Generate ground_truth.json."""
    gt = {
        "task_id": task["id"],
        "expected_files": [],
        "expected_keywords": [],
    }

    for check_type, *args in task["checks"]:
        if check_type == "file_exists":
            gt["expected_files"].append(args[0])
        elif check_type in ("contains", "grep_recursive", "grep_any", "contains_any"):
            pattern = args[1]
            keyword = pattern.replace('\\|', '|').split('|')[0].replace('\\', '')
            gt["expected_keywords"].append(keyword)

    return json.dumps(gt, indent=2) + '\n'


def main():
    dry_run = '--dry-run' in sys.argv

    for task in ALL_TASKS:
        suite = task['suite']
        benchmark_dir = SUITE_DIRS[suite]
        task_dir = os.path.join(benchmark_dir, task['id'])
        env_dir = os.path.join(task_dir, 'environment')
        tests_dir = os.path.join(task_dir, 'tests')

        if dry_run:
            print(f"  [DRY RUN] Would scaffold: {task['id']} -> {task_dir}")
            continue

        os.makedirs(env_dir, exist_ok=True)
        os.makedirs(tests_dir, exist_ok=True)

        with open(os.path.join(task_dir, 'task.toml'), 'w') as f:
            f.write(generate_task_toml(task))

        with open(os.path.join(task_dir, 'instruction.md'), 'w') as f:
            f.write(task['instruction'].strip() + '\n')

        with open(os.path.join(task_dir, 'CLAUDE.md'), 'w') as f:
            f.write(task['claude_md'].strip() + '\n')

        with open(os.path.join(env_dir, 'Dockerfile'), 'w') as f:
            f.write(generate_dockerfile(task))

        with open(os.path.join(env_dir, 'Dockerfile.sg_only'), 'w') as f:
            f.write(generate_dockerfile_sg_only(task))

        test_sh_path = os.path.join(tests_dir, 'test.sh')
        with open(test_sh_path, 'w') as f:
            f.write(generate_test_sh(task))
        os.chmod(test_sh_path, 0o755)

        with open(os.path.join(tests_dir, 'ground_truth.json'), 'w') as f:
            f.write(generate_ground_truth(task))

        if os.path.exists(SGONLY_WRAPPER):
            shutil.copy2(SGONLY_WRAPPER, os.path.join(tests_dir, 'sgonly_verifier_wrapper.sh'))

        print(f"  Scaffolded: {task['id']} ({suite})")

    action = "planned" if dry_run else "scaffolded"
    print(f"\nTotal: {len(ALL_TASKS)} scaling gap SDLC tasks {action}")
    print(f"  Mid-tier (500MB-1GB): {len(MIDTIER_TASKS)} tasks")
    print(f"  XL (>1.5GB): {len(XL_TASKS)} tasks")


if __name__ == '__main__':
    main()
