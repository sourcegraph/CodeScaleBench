# big-code-camel-feat-001: Implement camel-fix Component

This repository is large (~2M LOC). Use comprehensive search to understand existing patterns before implementing.

## Task Type: Feature Implementation

Your goal is to implement a new Camel component module. Focus on:

1. **Pattern discovery**: Study existing components (camel-kafka, camel-netty, camel-amqp) to understand conventions
2. **File identification**: Identify ALL files that need creation (new module) and modification (parent POM)
3. **Implementation**: Write code that follows existing Camel component patterns
4. **Verification**: Ensure the module integrates with the parent Maven build

## Key Reference Files

- `components/camel-kafka/src/main/java/org/apache/camel/component/kafka/KafkaComponent.java` — component pattern
- `components/camel-kafka/src/main/java/org/apache/camel/component/kafka/KafkaEndpoint.java` — endpoint pattern
- `components/camel-kafka/src/main/java/org/apache/camel/component/kafka/KafkaConsumer.java` — consumer pattern
- `components/camel-kafka/src/main/java/org/apache/camel/component/kafka/KafkaProducer.java` — producer pattern
- `components/camel-kafka/src/main/java/org/apache/camel/component/kafka/KafkaConfiguration.java` — configuration pattern
- `components/camel-netty/src/main/java/org/apache/camel/component/netty/NettyComponent.java` — network protocol component
- `components/camel-netty/pom.xml` — POM pattern for protocol components

## Camel Component Conventions

- All components extend `DefaultComponent` and override `createEndpoint()`
- Endpoints extend `DefaultEndpoint` and use `@UriEndpoint` annotation
- Configuration POJOs use `@UriParams` class annotation and `@UriParam` field annotations
- Consumers extend `DefaultConsumer` with `doStart()`/`doStop()` lifecycle
- Producers extend `DefaultAsyncProducer` with `process(Exchange, AsyncCallback)`
- Component discovery via `@Component("scheme")` annotation
- Auto-generated files: configurers, URI factories, JSON schemas (via `camel-package-maven-plugin`)

## Output Format

Write your analysis to `/logs/agent/solution.md` with these required sections:

```markdown
## Files Examined
- path/to/file.ext — examined to understand [pattern/API/convention]

## Dependency Chain
1. Define types/interfaces: path/to/types.ext
2. Implement core logic: path/to/impl.ext
3. Wire up integration: path/to/integration.ext
4. Add tests: path/to/tests.ext

## Code Changes
### path/to/file1.ext
\`\`\`diff
- old code
+ new code
\`\`\`

## Analysis
[Implementation strategy, design decisions, integration approach]
```

## Search Strategy

- Search for `DefaultComponent` in components/ to find component implementation patterns
- Search for `@UriEndpoint` to understand endpoint annotation conventions
- Search for `camel-kafka` or `camel-netty` to find reference implementations
- Check `components/pom.xml` to understand module registration
