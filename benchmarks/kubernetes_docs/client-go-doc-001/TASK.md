# Task: Client-Go Package Documentation

## Objective

Create a comprehensive `doc.go` file for the `staging/src/k8s.io/client-go` package that serves as package-level documentation for the official Kubernetes Go client library.

## Background

client-go is the primary Go library for interacting with the Kubernetes API. It provides:

- Typed and dynamic clients for API operations
- Informers, listers, and workqueues for building controllers
- Configuration loading (kubeconfig, in-cluster)
- Discovery of API groups/versions/resources

## What You Have Access To

You have access to the full Kubernetes source code. The `doc.go` file for the target package has been removed, but doc.go files for other packages remain available for reference.

### Key Files to Examine

- `staging/src/k8s.io/client-go/kubernetes/clientset.go` — Typed Clientset
- `staging/src/k8s.io/client-go/dynamic/interface.go` — Dynamic client
- `staging/src/k8s.io/client-go/discovery/discovery_client.go` — Discovery
- `staging/src/k8s.io/client-go/rest/config.go` — REST configuration
- `staging/src/k8s.io/client-go/tools/cache/shared_informer.go` — Informers
- `staging/src/k8s.io/client-go/tools/clientcmd/client_config.go` — Kubeconfig

## Requirements

Your `doc.go` file should:

1. **Package Overview**: Purpose of client-go
2. **Key Packages**: Document 6+ sub-packages and their roles
3. **Connecting to the API**: In-cluster and out-of-cluster patterns
4. **Interacting with Objects**: Typed vs dynamic, CRDs, Server-Side Apply
5. **Building Controllers**: Informer/lister/workqueue pattern, leader election

## Format

Valid Go `doc.go` file with copyright header and `package clientgo` declaration.

## Evaluation Criteria

1. **Technical Accuracy** (30%): Are the technical details correct?
2. **Completeness** (25%): Does it cover all major sub-packages and patterns?
3. **Style Conformance** (20%): Does it follow Go/Kubernetes documentation conventions?
4. **Ground Truth Alignment** (25%): Does it match the expected documentation structure?
