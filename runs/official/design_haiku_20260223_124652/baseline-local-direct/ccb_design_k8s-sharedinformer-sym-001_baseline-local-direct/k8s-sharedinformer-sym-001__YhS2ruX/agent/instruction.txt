Find all callers and usages of Kubernetes client-go's `Apps().V1().Deployments()` SharedInformer factory method across two repositories.

## Background

Kubernetes controllers use SharedInformerFactory from `k8s.io/client-go/informers` to watch and cache Kubernetes resources. The `Apps().V1().Deployments()` method returns a DeploymentInformer that controllers use to watch Deployment objects across the cluster. This pattern is used extensively in both the core Kubernetes controller-manager and in ecosystem controllers like the autoscaler.

## Repositories

Two repositories are available under `/workspace/`:

- `/workspace/kubernetes/` — kubernetes/kubernetes (Go, core Kubernetes control plane)
- `/workspace/autoscaler/` — kubernetes/autoscaler (Go, Kubernetes autoscaling controllers including VPA and cluster-autoscaler)

## Task

Find **all** places where `Apps().V1().Deployments()` is called on a SharedInformerFactory — across both repositories. Include production code, controller implementations, and test code.

For each caller/usage, record:
- `repo`: either `kubernetes/kubernetes` or `kubernetes/autoscaler`
- `file`: path relative to the repository root (e.g., `cmd/kube-controller-manager/app/apps.go`)
- `function`: the enclosing function or method name (e.g., `newDeploymentController`, `NewVpaTargetSelectorFetcher`)

## Output

Write your results to `/workspace/callers.json` as a JSON array:

```json
[
  {
    "repo": "kubernetes/kubernetes",
    "file": "cmd/kube-controller-manager/app/apps.go",
    "function": "newDeploymentController"
  },
  {
    "repo": "kubernetes/autoscaler",
    "file": "vertical-pod-autoscaler/pkg/target/fetcher.go",
    "function": "NewVpaTargetSelectorFetcher"
  }
]
```

Do not include:
- Generated code files (`*_generated.go`, `zz_generated.*.go`)
- Mock or fake implementations (`mock_*.go`, `fake_*.go`) unless they implement actual controller logic
- Pure documentation or comments
- Import statements

You should include:
- Production controller initialization code
- Test setup code that instantiates real controllers
- Any code that calls the method to get a DeploymentInformer
