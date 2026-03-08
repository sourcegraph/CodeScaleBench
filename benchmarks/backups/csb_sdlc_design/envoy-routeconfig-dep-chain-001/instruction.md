Trace the definition of `RouteConfiguration` through the Envoy xDS dependency chain.

## Background

In the Envoy xDS ecosystem, configuration types flow from protobuf definitions through generated Go code to service mesh implementations. The `RouteConfiguration` type is a core xDS resource used for HTTP routing configuration.

## Repositories

Three repositories are available under `/workspace/`:

- `/workspace/istio/` — istio/istio (service mesh implementation using xDS)
- `/workspace/go-control-plane/` — envoyproxy/go-control-plane (generated Go code from proto definitions)
- `/workspace/data-plane-api/` — envoyproxy/data-plane-api (canonical protobuf definitions for xDS API)

## Task

Trace the `RouteConfiguration` type from its **usage site** in Istio through the **generated Go code** in go-control-plane to the **original protobuf definition** in data-plane-api. Document each step in the chain.

Start from this usage site:
- **File**: `/workspace/istio/pilot/pkg/xds/rds.go` (or similar RDS generator file)
- **Usage**: Functions that construct or reference `RouteConfiguration` objects

For each link in the chain, record:
- `step`: sequence number (1 for usage, 2 for generated code, 3 for proto definition)
- `repo`: which repository (e.g., `istio/istio`, `envoyproxy/go-control-plane`, `envoyproxy/data-plane-api`)
- `file`: path relative to the repository root
- `line`: line number where the symbol appears (approximate is acceptable)
- `context`: what happens at this step (e.g., "RDS generator creates RouteConfiguration", "Generated Go struct", "Proto message definition")

## Output

Write your results to `/workspace/chain.json`:

```json
[
  {
    "step": 1,
    "repo": "istio/istio",
    "file": "pilot/pkg/xds/rds.go",
    "line": 150,
    "context": "Istio RDS generator creates RouteConfiguration objects"
  },
  {
    "step": 2,
    "repo": "envoyproxy/go-control-plane",
    "file": "envoy/config/route/v3/route.pb.go",
    "line": 200,
    "context": "Generated Go struct for RouteConfiguration from protobuf"
  },
  {
    "step": 3,
    "repo": "envoyproxy/data-plane-api",
    "file": "envoy/config/route/v3/route.proto",
    "line": 50,
    "context": "Proto message definition for RouteConfiguration"
  }
]
```

## Notes

- The go-control-plane repository contains **generated code** from protobuf definitions. The `.pb.go` files are auto-generated from `.proto` files in data-plane-api.
- Use definition lookup or import tracing to navigate from Istio's usage to the generated Go types.
- The final step should identify the **source `.proto` file**, not just the generated code.
- Line numbers are approximate; +/- 50 lines is acceptable if the symbol is in that region.
