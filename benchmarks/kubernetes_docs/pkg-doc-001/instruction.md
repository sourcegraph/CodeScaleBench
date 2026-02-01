# [Kubernetes] Container Manager Package Documentation

**Repository:** kubernetes/kubernetes
**Difficulty:** MEDIUM
**Category:** package-documentation
**Task Type:** Documentation Generation - Code Inference

## Description

Generate comprehensive package documentation (`doc.go`) for the `pkg/kubelet/cm` (Container Manager) package in Kubernetes. The existing documentation has been stripped from the workspace. You must infer the documentation entirely from the source code.

**Why this requires MCP:** The container manager interacts with many other kubelet subsystems. Understanding its full scope requires searching across the codebase for how it's used, what interfaces it implements, and how subpackages relate. Sourcegraph search on the `kubernetes-stripped` repository provides this cross-package context efficiently.

## Task

YOU MUST CREATE A `doc.go` FILE at `pkg/kubelet/cm/doc.go`.

### Requirements

Your `doc.go` file should:

1. **Package Overview**: Explain the purpose of the container manager package and its role in the kubelet
2. **Key Responsibilities**: List main responsibilities (cgroup management, QoS enforcement, resource allocation)
3. **Important Types**: Document key interfaces, especially the `ContainerManager` interface
4. **Subpackages**: Reference important subpackages (`cpumanager`, `memorymanager`, `topologymanager`, `devicemanager`) and their relationship to the main package
5. **Platform Considerations**: Note differences between Linux and Windows implementations, and cgroup v1 vs v2 if relevant

### Key Files to Examine

- `container_manager.go` - Main interface definitions
- `container_manager_linux.go` - Linux-specific implementation
- `container_manager_windows.go` - Windows-specific implementation
- `types.go` - Type definitions
- Subpackages: `cpumanager/`, `memorymanager/`, `topologymanager/`, `devicemanager/`

### Go Documentation Conventions

- Use `// Package cm ...` line comment style OR `/* ... */` block comment style
- Include copyright header (Apache 2.0, The Kubernetes Authors)
- Reference sub-packages and key types by name
- Keep descriptions precise and technically accurate

### Kubernetes Documentation Style

- Be concise but comprehensive — cover the "what" and "why", not implementation details
- Use the abbreviation "cm" for "container manager" as Kubernetes convention
- Reference related kubelet subsystems and how they interact
- Note platform-specific differences (Linux, Windows, cgroup versions)

### Format

The output must be a valid Go `doc.go` file following Kubernetes conventions:

```go
/*
Copyright YEAR The Kubernetes Authors.

Licensed under the Apache License, Version 2.0 (the "License");
...
*/

// Package cm (container manager) ...
package cm
```

## Success Criteria

- `pkg/kubelet/cm/doc.go` file exists
- Contains valid Go package documentation
- Accurately describes the container manager's purpose and responsibilities
- References key types/interfaces and subpackages
- Follows Go and Kubernetes documentation conventions

## Testing

The verifier checks that `doc.go` was created and scores it based on:
- File existence and valid Go syntax
- Coverage of key concepts (ContainerManager, cgroups, QoS, resource allocation)
- Mention of subpackages and platform-specific behavior

**Time Limit:** 15 minutes
