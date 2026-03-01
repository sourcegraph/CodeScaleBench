Trace the Kubernetes Container Runtime Interface (CRI) from its gRPC service definition to containerd's implementation

The Kubernetes CRI defines a gRPC RuntimeService in its api.proto file. Trace the complete interface contract:
1. Find the CRI RuntimeService gRPC definition in the kubernetes repo (under staging/src/k8s.io/cri-api/)
2. Identify the key RPC methods (RunPodSandbox, StopPodSandbox, RemovePodSandbox, etc.)
3. Find where containerd implements these CRI methods
4. Document how kubernetes vendors containerd's API types (check kubernetes/vendor/github.com/containerd/)

Your analysis must span both the kubernetes and containerd source trees under /ccb_crossrepo/src/.
Write your findings to REASONING.md in the workspace.
