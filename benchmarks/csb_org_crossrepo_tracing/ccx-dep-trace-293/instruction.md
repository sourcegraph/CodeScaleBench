# Roslyn C# Type Inference and Overload Resolution Chain

## Your Task

Trace the type inference and method overload resolution pipeline in dotnet/roslyn. Find all C# source files under src/Compilers/CSharp/Portable/Binder/ that participate in overload resolution. Identify: the OverloadResolution class and its main Resolve methods, the MethodTypeInferrer that performs generic type argument inference, the BetterFunctionMember comparison, the Conversions class used to rank implicit conversions, and the BestTypeInferrer for array/conditional expressions. Report each file path and key class.

## Context

You are working on a codebase task involving repos from the crossrepo tracing domain.

## Available Resources

The local `/workspace/` directory contains: sg-evals/roslyn--v4.12.0.

## Output Format

Create a file at `/workspace/answer.json` with your findings in the following structure:

```json
{
  "files": [
    {"repo": "org/repo-name", "path": "relative/path/to/file.go"}
  ],
  "symbols": [
    {"repo": "org/repo-name", "path": "relative/path/to/file.go", "symbol": "SymbolName"}
  ],
  "chain": [
    {"repo": "org/repo-name", "path": "relative/path/to/file.go", "symbol": "FunctionName"}
  ],
  "text": "Narrative explanation of your findings, citing repos and file paths."
}
```

Include only the fields relevant to this task. Your answer is evaluated against a closed-world oracle — completeness matters.

## Evaluation

Your answer will be scored on:
- **File recall and precision**: Did you find all relevant files?
