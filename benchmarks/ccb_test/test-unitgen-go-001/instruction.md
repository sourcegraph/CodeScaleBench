# Task: Generate Unit Tests for Kubernetes Storage Value Package

**Repository:** kubernetes/kubernetes
**Output:** Write your test file to `/workspace/staging/src/k8s.io/apiserver/pkg/storage/value/value_test.go`

## Objective

Generate comprehensive unit tests for the `k8s.io/apiserver/pkg/storage/value` package. This package handles transparent data encryption and transformation for Kubernetes API server storage.

## Scope

Focus on the `value.go` and `transformer.go` files in `staging/src/k8s.io/apiserver/pkg/storage/value/`. Your tests must cover:

- The `Transformer` interface contract (encrypt/decrypt round-trips)
- The `PrefixTransformer` decorator behavior
- The `TransformerUnion` fanout-and-select logic
- Error propagation for stale/corrupted data
- Edge cases: empty values, nil transformers, mismatched prefixes

## Content Expectations

Your test file must include:
- At least 8 test functions with `Test` prefix
- Table-driven tests (`t.Run` subtests) for at least one major function
- Coverage of the primary happy path AND at least 3 failure/edge cases
- Use of `testing.T`, `t.Fatal`/`t.Errorf` appropriately
- No external test dependencies beyond the standard library and the package under test

## Quality Bar

- Test names must be descriptive (e.g., `TestTransformerRoundTrip`, `TestPrefixTransformerMismatch`)
- Do not fabricate function signatures — inspect the actual source before writing tests
- Tests must be syntactically valid Go
- Do NOT run the tests yourself — write the test file and the evaluation system validates independently

## Output

Write your test file to:
```
/workspace/staging/src/k8s.io/apiserver/pkg/storage/value/value_test.go
```
