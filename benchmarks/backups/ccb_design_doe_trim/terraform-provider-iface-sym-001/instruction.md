Find all implementations and usages of Terraform's `provider.Provider` interface across two repositories.

## Background

Terraform providers are plugins that implement the `providers.Interface` (commonly referred to as `provider.Provider`) defined in the Terraform core codebase. This interface defines the contract between Terraform's execution engine and provider plugins, specifying methods for schema retrieval, configuration, resource lifecycle operations (plan/apply/read/delete), and state management.

The interface is defined in `hashicorp/terraform` at `internal/providers/provider.go` and includes key methods like:
- `GetProviderSchema()` - returns provider, resource, and data source schemas
- `ConfigureProvider()` - configures the provider with settings
- `PlanResourceChange()` / `ApplyResourceChange()` - resource lifecycle operations
- `ReadResource()` - refreshes resource state
- `ValidateResourceConfig()` / `ValidateDataResourceConfig()` - configuration validation

Provider plugins (like terraform-provider-aws) implement this interface, while Terraform core invokes these methods during plan, apply, refresh, and validate operations.

## Repositories

Two repositories are available under `/workspace/`:

- `/workspace/terraform/` — hashicorp/terraform (Go, core Terraform engine with interface definition and internal callers)
- `/workspace/terraform-provider-aws/` — hashicorp/terraform-provider-aws (Go, AWS provider implementation)

## Task

Find **all** places where the `providers.Interface` (provider.Provider) is:
1. **Implemented** as a struct/type (e.g., `MockProvider`, `GRPCProvider`, or provider factory functions)
2. **Called/invoked** as a method receiver (e.g., `provider.ConfigureProvider()`, `provider.ReadResource()`)
3. **Used as a type** in function signatures or variable declarations where the interface methods are actually invoked

Include production code and test code. Focus on concrete implementations and actual method invocations, not just type declarations or comments.

For each implementation or usage, record:
- `repo`: either `hashicorp/terraform` or `hashicorp/terraform-provider-aws`
- `file`: path relative to the repository root (e.g., `terraform/provider_mock.go`, `internal/provider/provider.go`)
- `function`: the enclosing function or method name, OR the struct/type name if it's an implementation (e.g., `MockProvider`, `managedResourceExecute`, `ProtoV5ProviderServerFactory`)

## Output

Write your results to `/workspace/callers.json` as a JSON array:

```json
[
  {
    "repo": "hashicorp/terraform",
    "file": "terraform/provider_mock.go",
    "function": "MockProvider"
  },
  {
    "repo": "hashicorp/terraform",
    "file": "terraform/node_resource_apply_instance.go",
    "function": "managedResourceExecute"
  },
  {
    "repo": "hashicorp/terraform-provider-aws",
    "file": "internal/provider/provider.go",
    "function": "ProtoV5ProviderServerFactory"
  }
]
```

Do not include:
- The interface definition itself (`internal/providers/provider.go` where `Interface` is declared)
- Pure documentation references (`.md` files)
- Type alias declarations that don't invoke or implement the interface methods
- Auto-generated code or vendor directories
