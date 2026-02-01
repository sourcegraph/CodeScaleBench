# Kubernetes Documentation Task: client-go-doc-001

## Task
Generate comprehensive package documentation (`doc.go`) for the `staging/src/k8s.io/client-go` package.

## Constraints
- **Do NOT find or use** the `doc.go` file for `staging/src/k8s.io/client-go/` — it has been removed from the workspace.
- You CAN and SHOULD read `doc.go` files from other packages to understand Go documentation conventions and cross-package relationships.
- **Inference**: Use your understanding of the implementation code, interfaces, and cross-package interactions to write the documentation.

## Requirements for doc.go
1. Explain the purpose of client-go as the official Kubernetes Go client library.
2. Document key sub-packages: kubernetes, dynamic, discovery, tools/cache, tools/clientcmd, rest.
3. Describe connecting to the API (in-cluster vs out-of-cluster).
4. Cover interacting with API objects (typed vs dynamic, CRDs, Server-Side Apply).
5. Explain the controller pattern (informers, listers, workqueues, leader election).
6. Follow Go documentation conventions.

## Verification
Write the final documentation to `staging/src/k8s.io/client-go/doc.go`.
