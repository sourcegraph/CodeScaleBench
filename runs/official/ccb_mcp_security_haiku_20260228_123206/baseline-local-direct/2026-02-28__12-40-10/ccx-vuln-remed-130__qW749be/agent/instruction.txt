# JCE Cryptography Provider Architecture Audit

## Your Task

Audit the Java Cryptography Extension (JCE) provider architecture in OpenJDK. Find: 1. The file `src/java.base/share/classes/java/security/Provider.java` that defines the abstract `Provider` class and its inner `Service` class. 2. The file that defines `Security` class which manages registered providers (`src/java.base/share/classes/java/security/Security.java`). 3. The SunJCE provider implementation file (`src/java.crypto/share/classes/com/sun/crypto/provider/SunJCE.java` or under `java.base`). 4. The file that implements `Cipher.getInstance()` — the factory method that resolves providers (`src/java.base/share/classes/javax/crypto/Cipher.java`). 5. The `java.security` configuration file that lists default providers. Report each file path and key class/method.

## Context

You are working on a codebase task involving repos from the security domain.

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
