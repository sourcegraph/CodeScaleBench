# Add Evaluation Metadata Field to Flipt (Proto + Go)

**Repository:** flipt-io/flipt
**Access Scope:** You may modify files in `rpc/flipt/evaluation/` (protobuf schema + generated code) and `internal/server/evaluation/` (Go server). You may read any other files to understand existing patterns.

## Context

Flipt is a feature flag platform built with Go and gRPC. Its API is defined in Protocol Buffer (`.proto`) files, with generated Go code alongside. The evaluation server constructs protobuf response objects returned to clients.

Operators have requested that evaluation responses include a `segment_match_type` field so clients can see whether the evaluation matched a segment using `ALL` (all constraints matched) or `ANY` (at least one constraint matched) logic. This information is already available in the evaluation flow but is not exposed in the response.

## Task

Add a `segment_match_type` string field to the evaluation responses. This requires changes to **both** the protobuf schema (`.proto` file) and the Go server code that constructs responses — a cross-language change.

**YOU MUST IMPLEMENT CODE CHANGES.**

### Requirements

1. **Protobuf schema change** — Add `string segment_match_type` to the `VariantEvaluationResponse` message in the evaluation proto file. Determine the next sequential tag by examining existing fields in the message. The value should be "ALL", "ANY", or "" (empty when no segment matched).

2. **Generated Go code change** — Add the corresponding `SegmentMatchType string` field and getter method to the Go generated code (`.pb.go` file). Match the exact patterns used by existing fields. Do NOT regenerate code with protoc — manually add the field.

3. **Server code change** — In the evaluation server, populate `SegmentMatchType` on the response after evaluation logic determines which rule matched. The evaluation must set this field for variant evaluations, and batch responses should include it too.

4. **Determine the source value** — The storage layer carries segment operator information on evaluation rules that indicates ALL vs ANY. Find this type and trace how the operator maps to the string values you need.

## Success Criteria

- Evaluation proto has `segment_match_type` field in `VariantEvaluationResponse`
- Generated Go code has matching `SegmentMatchType` field and getter
- Server code populates `SegmentMatchType` from the rule's segment operator
- Proto tag number is valid (no collision with existing fields)
- Changes span both proto and Go files (cross-language change)
- Go code compiles: `go build ./internal/server/evaluation/...`
