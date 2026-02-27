Migrate deprecated grpc.Dial() calls to grpc.NewClient() across the Go ecosystem

The gRPC Go library deprecated grpc.Dial() and grpc.DialContext() in favor of grpc.NewClient(). Find and update all deprecated gRPC dial calls across the etcd, kubernetes, and containerd codebases under /ccb_crossrepo/src/.

For each callsite:
- Replace grpc.Dial(target, opts...) with grpc.NewClient(target, opts...)
- Replace grpc.DialContext(ctx, target, opts...) with grpc.NewClient(target, opts...)
- Preserve any existing dial options and error handling
- Do not modify proto definitions or generated code

**Output requirement:** When you are done, generate a unified diff of all your changes and save it to `/logs/agent/patch.diff`. You can do this with:
```bash
cd /ccb_crossrepo/src && for d in */; do (cd "$d" && git diff HEAD); done > /logs/agent/patch.diff
```
If you prefer, you can also just make your changes directly to the source files — the evaluator will auto-collect diffs from the git repositories as a fallback.
