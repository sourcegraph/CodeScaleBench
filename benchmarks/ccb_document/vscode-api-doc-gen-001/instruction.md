# Task: Generate VS Code Diagnostic API Reference Documentation

## Objective

Generate comprehensive API reference documentation for the **VS Code Diagnostic API**. The Diagnostic API allows extensions to report code issues (errors, warnings, information, hints) to users within the editor.

## Scope

Your documentation should cover the following API surface within the `vscode.languages` namespace:

### Core Interfaces and Classes

1. **Diagnostic class**: Represents a single diagnostic (error, warning, info, hint)
2. **DiagnosticCollection interface**: Container for managing diagnostics across documents
3. **DiagnosticSeverity enum**: Severity levels (Error, Warning, Information, Hint)
4. **DiagnosticRelatedInformation class**: Additional context for diagnostics
5. **DiagnosticTag enum**: Tags for categorizing diagnostics (Unnecessary, Deprecated)

### Key Functions

1. **createDiagnosticCollection()**: Factory function for creating diagnostic collections
2. **getDiagnostics()**: Retrieve diagnostics for a resource or workspace

### Events

1. **onDidChangeDiagnostics**: Event fired when diagnostics change globally

## Required Content

Your API reference must include:

### For Each API Method/Function:
- **Signature**: Full TypeScript signature with parameter types and return type
- **Parameters**: Description of each parameter, including optional/required status
- **Return value**: Description of what is returned
- **Behavior notes**: How the API behaves in different scenarios
- **Error cases**: What errors can occur and when

### For Each Interface/Class:
- **Properties**: All properties with types and descriptions
- **Methods**: All methods with signatures and behavior
- **Constructor**: Construction pattern (if applicable)
- **Lifecycle**: Object lifecycle and disposal semantics

### Usage Examples:
- **Basic usage**: Simple diagnostic creation and publishing
- **Advanced patterns**: Event subscription, cleanup, related information
- **Real-world patterns**: Extract usage examples from internal VS Code code

## Deliverable

Write your documentation to `/workspace/documentation.md` using Markdown format.

You may choose any clear structure as long as all required sections are covered:

```
# VS Code Diagnostic API Reference

## Overview
[Brief introduction to the Diagnostic API]

## Core Types

### Diagnostic
[Class documentation]

### DiagnosticCollection
[Interface documentation]

### DiagnosticSeverity
[Enum documentation]

### DiagnosticRelatedInformation
[Class documentation]

### DiagnosticTag
[Enum documentation]

## Functions

### createDiagnosticCollection()
[Function documentation]

### getDiagnostics()
[Function documentation]

## Events

### onDidChangeDiagnostics
[Event documentation]

## Usage Examples

### Basic Example
[Code example with explanation]

### Advanced Example
[Code example with explanation]

## Common Patterns
[Patterns discovered from internal usage]

## Error Handling
[Error cases and handling strategies]
```

## Tips

- Use the VS Code repository's TypeScript definitions (src/vs/vscode.d.ts) to find exact API signatures
- Search for internal usage in src/vs/workbench/ and extensions/ directories to discover real-world patterns
- Include behavioral notes that aren't obvious from type signatures (e.g., disposal requirements, threading considerations)
- Document the relationship between DiagnosticCollection.set() and getDiagnostics()
- Explain when onDidChangeDiagnostics fires and what information it provides

## Evaluation

Your documentation will be scored on:
- **API completeness** (40%): Coverage of all required API methods, properties, and types
- **Behavioral notes** (30%): Correct description of non-obvious behaviors, lifecycle, error cases
- **Usage examples** (20%): Quality and correctness of code examples from internal callers
- **Structure** (10%): Organization, clarity, and completeness of documentation structure
