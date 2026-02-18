# big-code-camel-arch-001: Apache Camel Message Routing Architecture

This repository is large (~2.8M LOC, multi-module Maven project). Use comprehensive search strategies across multiple modules.

## Task Type: Architectural Understanding

Your goal is to trace the complete message routing pipeline in Apache Camel. Focus on:

1. **Component hierarchy**: Find the API interfaces (Component, Endpoint, Consumer, Processor, Producer) in core/camel-api/
2. **Base implementations**: Find DefaultComponent, DefaultEndpoint, DefaultConsumer, DefaultProducer in core/camel-support/
3. **Engine layer**: Trace Pipeline, SendProcessor, DefaultChannel in core/camel-core-processor/ and core/camel-base-engine/
4. **Reification**: Understand how RouteReifier converts RouteDefinition to runtime Route objects

## Output Format

Write your analysis to `/logs/agent/solution.md` with these required sections:

```markdown
## Files Examined
- path/to/file.ext — role in the architecture

## Dependency Chain
1. path/to/core.ext (foundational types/interfaces)
2. path/to/impl.ext (implementation layer)
3. path/to/integration.ext (integration/wiring layer)

## Analysis
[Your architectural analysis]
```

## Search Strategy

- Start with `core/camel-api/src/main/java/org/apache/camel/` for interfaces (Component, Endpoint, Consumer, Processor, Producer)
- Explore `core/camel-support/src/main/java/org/apache/camel/support/` for Default* base classes
- Check `core/camel-core-processor/src/main/java/org/apache/camel/processor/` for Pipeline, SendProcessor
- Check `core/camel-base-engine/src/main/java/org/apache/camel/impl/engine/` for DefaultChannel, DefaultRoute, RouteService
- Use `find_references` to trace how Component.createEndpoint flows through to runtime
- Use `go_to_definition` to understand interface implementations
