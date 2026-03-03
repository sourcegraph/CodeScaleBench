# OpenJDK Security Provider Registration Framework

## Your Task

Find all Java source files in openjdk/jdk that implement the security provider registration framework. Identify: the base Provider class with putService() (java.security.Provider), the SunJCE provider that registers crypto algorithms, the SunJSSE provider for SSL/TLS factories, the SunEC provider for elliptic curve algorithms, the Sun provider for core algorithms, and the ProviderConfig lazy-loading mechanism that maps provider names to classes.

## Context

You are working on a codebase task involving repos from the migration domain.

## Available Resources

The local `/workspace/` directory contains: sg-evals/jdk--742e735d.

**Note:** Additional repositories are accessible via Sourcegraph MCP tools:
- `sg-evals/jdk--742e735d` (openjdk/jdk)

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
