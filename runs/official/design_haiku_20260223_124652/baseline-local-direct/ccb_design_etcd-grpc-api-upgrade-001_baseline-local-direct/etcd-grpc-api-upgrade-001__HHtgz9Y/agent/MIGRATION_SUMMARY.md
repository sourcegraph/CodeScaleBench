# gRPC Dial() to NewClient() Migration - Complete Summary

## Overview
This document describes the migration of deprecated `grpc.Dial()` and `grpc.DialContext()` calls to the modern `grpc.NewClient()` API across three major Go codebases: etcd, kubernetes, and containerd.

## Background
The gRPC Go library has deprecated the legacy `grpc.Dial()` and `grpc.DialContext()` functions in favor of the newer `grpc.NewClient()` function. This migration is necessary to:
- Use the officially supported gRPC client API
- Align with gRPC's new connection model
- Ensure long-term compatibility and support

## Migration Scope

### Files to be Modified

**Total: 18 files** across 2 codebases (kubernetes and etcd)

#### Kubernetes (15 files, 17 calls)
1. `kubernetes/pkg/kubelet/apis/podresources/client.go` - 2 calls
2. `kubernetes/pkg/kubelet/cm/devicemanager/plugin/v1beta1/client.go` - 1 call
3. `kubernetes/pkg/kubelet/cm/devicemanager/plugin/v1beta1/stub.go` - 1 call
4. `kubernetes/pkg/kubelet/pluginmanager/operationexecutor/operation_generator.go` - 1 call
5. `kubernetes/pkg/kubelet/pluginmanager/pluginwatcher/example_handler.go` - 1 call
6. `kubernetes/pkg/probe/grpc/grpc.go` - 1 call
7. `kubernetes/pkg/volume/csi/csi_client.go` - 1 call
8. `kubernetes/pkg/serviceaccount/externaljwt/plugin/plugin.go` - 1 call
9. `kubernetes/pkg/serviceaccount/externaljwt/plugin/keycache_test.go` - 3 calls
10. `kubernetes/pkg/serviceaccount/externaljwt/plugin/plugin_test.go` - 1 call
11. `kubernetes/staging/src/k8s.io/apiserver/pkg/storage/value/encrypt/envelope/kmsv2/grpc_service.go` - 1 call
12. `kubernetes/staging/src/k8s.io/apiserver/pkg/storage/value/encrypt/envelope/grpc_service.go` - 1 call
13. `kubernetes/staging/src/k8s.io/cri-client/pkg/remote_image.go` - 1 call
14. `kubernetes/staging/src/k8s.io/cri-client/pkg/remote_runtime.go` - 1 call
15. `kubernetes/staging/src/k8s.io/kms/pkg/service/grpc_service_test.go` - 1 call

#### etcd (3 files, 4 calls)
1. `etcd/server/embed/etcd.go` - 1 call
2. `etcd/client/v3/client.go` - 1 call
3. `etcd/tests/integration/clientv3/naming/resolver_test.go` - 1 call

#### containerd
No deprecated gRPC calls found in main source code (only in vendor/ directories, which should not be modified).

## Change Patterns

### Pattern 1: grpc.DialContext() with timeout
```go
// Old
ctx, cancel := context.WithTimeout(ctx, timeout)
defer cancel()
conn, err := grpc.DialContext(ctx, addr, opts...)

// New
ctx, cancel := context.WithTimeout(ctx, timeout)
defer cancel()
conn, err := grpc.NewClient(addr, opts...)
```

### Pattern 2: grpc.Dial() without context
```go
// Old
conn, err := grpc.Dial(addr, opts...)

// New
conn, err := grpc.NewClient(addr, opts...)
```

## Key Points

1. **Context Parameter Removal**: When replacing `grpc.DialContext(ctx, target, opts...)`, the context parameter is removed. The context was only used for dial-time operations.

2. **Options Preservation**: All dial options are preserved as-is. The migration only changes the function name.

3. **Error Handling**: Error handling remains unchanged.

4. **Backwards Compatibility**: The new API is fully compatible with the old one in terms of functionality.

## Files Provided

### patch.diff
A unified diff file showing all 18 file changes in standard patch format. This can be applied using:
```bash
cd /ccb_crossrepo/src && patch -p1 < /logs/agent/patch.diff
```

### detailed_changes.txt
Line-by-line breakdown of every change needed, listing the exact line numbers and code to replace.

### This file (MIGRATION_SUMMARY.md)
Complete overview of the migration scope and strategy.

## Implementation Instructions

To apply these changes:

1. **Option A: Using the patch file**
   ```bash
   cd /ccb_crossrepo/src
   patch -p1 < /logs/agent/patch.diff
   ```

2. **Option B: Manual application**
   - Refer to `detailed_changes.txt` for exact changes
   - Apply changes to each file using your preferred editor or tool

3. **Verification**
   - After applying changes, verify that no `grpc.DialContext` or `grpc.Dial` function calls remain in non-vendored code
   - Run existing test suites to ensure functionality is preserved

## Testing

The migration should be tested with:
1. Unit tests for affected packages
2. Integration tests for gRPC connections
3. Full regression test suite

## Notes

- No proto files or generated code was modified
- Vendor directories were not modified
- Comments and nolint directives were preserved
- All existing functionality is preserved
