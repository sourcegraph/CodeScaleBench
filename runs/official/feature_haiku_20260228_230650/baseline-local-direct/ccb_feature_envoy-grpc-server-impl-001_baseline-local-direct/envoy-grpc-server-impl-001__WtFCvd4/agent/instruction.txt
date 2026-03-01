Find all concrete server implementations of the `AggregatedDiscoveryServiceServer` gRPC interface across xDS control plane repositories.

## Background

The Aggregated Discovery Service (ADS) is the primary xDS protocol for delivering configuration to Envoy proxies. The gRPC service is defined in the proto file `envoy/service/discovery/v3/ads.proto`:

```protobuf
service AggregatedDiscoveryService {
  rpc StreamAggregatedResources(stream DiscoveryRequest)
    returns (stream DiscoveryResponse) {}

  rpc DeltaAggregatedResources(stream DeltaDiscoveryRequest)
    returns (stream DeltaDiscoveryResponse) {}
}
```

When compiled to Go, this generates a server interface `AggregatedDiscoveryServiceServer` in the package `github.com/envoyproxy/go-control-plane/envoy/service/discovery/v3`. Any struct that implements the methods of this interface acts as an xDS control plane server.

## Repositories

Three repositories are available under `/workspace/`:

- `/workspace/go-control-plane/` — envoyproxy/go-control-plane (Go xDS server SDK, reference implementations)
- `/workspace/istio/` — istio/istio (Istio control plane with Pilot xDS server)
- `/workspace/emissary/` — emissary-ingress/emissary (Envoy-based API gateway with xDS configuration server)

## Task

Find **all struct types** that implement the `AggregatedDiscoveryServiceServer` interface across all three repositories. These are types that provide concrete implementations of:
- `StreamAggregatedResources(stream AggregatedDiscoveryService_StreamAggregatedResourcesServer) error`
- `DeltaAggregatedResources(stream AggregatedDiscoveryService_DeltaAggregatedResourcesServer) error`

For each implementor, record:
- `repo`: one of `envoyproxy/go-control-plane`, `istio/istio`, or `emissary-ingress/emissary`
- `file`: path relative to the repository root (e.g., `pkg/server/v3/server.go`)
- `struct_name`: the name of the struct type that implements the interface (e.g., `Server`, `DiscoveryServer`)

## Output

Write your results to `/workspace/implementors.json` as a JSON array:

```json
[
  {
    "repo": "envoyproxy/go-control-plane",
    "file": "pkg/server/v3/server.go",
    "struct_name": "Server"
  },
  {
    "repo": "istio/istio",
    "file": "pilot/pkg/xds/ads.go",
    "struct_name": "DiscoveryServer"
  }
]
```

## Inclusion Criteria

**Include:**
- Production server implementations (the main control plane servers)
- Test server implementations (mock servers, fake servers for testing)
- Partial implementations (types that implement at least one of the two methods)
- Embedded server types (if a struct embeds the interface but provides its own methods)

**Exclude:**
- The generated protobuf interface definition itself (in `*_grpc.pb.go` files)
- Pure interface embeddings without method implementations (e.g., `type X struct { AggregatedDiscoveryServiceServer }` with no methods)
- Deprecated or commented-out implementations
- Vendor directory code
- Types that only **call** the server interface (clients), not implement it
