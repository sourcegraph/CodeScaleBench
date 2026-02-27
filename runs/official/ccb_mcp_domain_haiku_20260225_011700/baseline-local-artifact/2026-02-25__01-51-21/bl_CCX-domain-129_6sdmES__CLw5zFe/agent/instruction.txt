# Java ClassLoader Delegation Chain

## Your Task

Trace the Java class loading delegation chain in OpenJDK. Find: 1. The Java source file `src/java.base/share/classes/java/lang/ClassLoader.java` that defines the `loadClass(String, boolean)` method implementing parent-first delegation. 2. The file that defines `BuiltinClassLoader` — the base for the three built-in loaders (`src/java.base/share/classes/jdk/internal/loader/BuiltinClassLoader.java`). 3. The file defining `ClassLoaders` that creates the bootstrap, platform, and application class loaders. 4. The HotSpot C++ file that implements native class loading (`src/hotspot/share/classfile/classLoader.cpp`). 5. The file that defines `SystemDictionary` which caches loaded classes. Report each file path and key class/method.

## Context

You are working on a codebase task involving repos from the domain domain.

## Available Resources

No local repositories are pre-checked out.

**Note:** Additional repositories may be relevant to this task:
- `sg-evals/jdk--742e735d` (openjdk/jdk)

## Output Format

Create a file at `/workspace/answer.json` with your findings in the following structure:

```json
{
  "files": [
    {"repo": "org/repo-name", "path": "relative/path/to/file.java"}
  ],
  "symbols": [
    {"repo": "org/repo-name", "path": "relative/path/to/file.java", "symbol": "SymbolName"}
  ],
  "chain": [
    {"repo": "org/repo-name", "path": "relative/path/to/file.java", "symbol": "FunctionName"}
  ],
  "text": "Narrative explanation of your findings, citing repos and file paths."
}
```

Include only the fields relevant to this task. Your answer is evaluated against a closed-world oracle — completeness matters.

## Evaluation

Your answer will be scored on:
- **File recall and precision**: Did you find all relevant files?
