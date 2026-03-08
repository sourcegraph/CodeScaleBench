Find all callers and usages of Envoy's `StreamAggregatedResources` xDS gRPC method across two repositories.

## Background

The Aggregated Discovery Service (ADS) is Envoy's primary mechanism for receiving configuration from a control plane. The `StreamAggregatedResources` RPC method is defined in the proto file `api/envoy/service/discovery/v3/ads.proto` within the `AggregatedDiscoveryService` service. It is used by both the Envoy proxy itself and by gRPC's xDS client implementation.

## Repositories

Two repositories are available under `/workspace/`:

- `/workspace/envoy/` — envoyproxy/envoy (C++, proto definitions + xDS client implementation)
- `/workspace/grpc-go/` — grpc/grpc-go (Go, xDS client + test infrastructure)

## Task

Find **all** places where `StreamAggregatedResources` is called, referenced as a method descriptor, implemented as a gRPC server method, or used as a method name string — across both repositories. Include production code and test code.

For each caller/usage, record:
- `repo`: either `envoyproxy/envoy` or `grpc/grpc-go`
- `file`: path relative to the repository root (e.g., `source/server/proto_descriptors.cc`)
- `function`: the enclosing function or method name (e.g., `validateProtoDescriptors`, `GrpcMuxImpl::updateMuxSource`)

## Output

Write your results to `/workspace/callers.json` as a JSON array:

```json
[
  {
    "repo": "envoyproxy/envoy",
    "file": "source/server/proto_descriptors.cc",
    "function": "validateProtoDescriptors"
  },
  {
    "repo": "grpc/grpc-go",
    "file": "internal/xds/clients/xdsclient/ads_stream.go",
    "function": "adsStreamImpl.runner"
  }
]
```

Do not include:
- The proto definition itself (`ads.proto`)
- Pure documentation references (`.rst`, `.md` files)
- Generated protobuf code (`*.pb.go`, `*_grpc.pb.go`, `*.pb.cc`, `*.pb.h`)
- Type alias declarations that don't invoke or implement the method
