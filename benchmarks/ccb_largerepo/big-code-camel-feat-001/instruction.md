# big-code-camel-feat-001: Implement camel-fix Component for FIX Protocol

## Task

Implement a new `camel-fix` component in Apache Camel that enables routing FIX (Financial Information eXchange) protocol messages through Camel routes. The FIX protocol is the standard electronic messaging protocol for securities trading, used by exchanges, brokers, and asset managers worldwide.

The component must follow Apache Camel's standard component architecture:

1. **FixComponent** (`components/camel-fix/src/main/java/org/apache/camel/component/fix/FixComponent.java`):
   - Extends `DefaultComponent`
   - Annotated `@Component("fix")`
   - Creates `FixEndpoint` instances via `createEndpoint()`
   - Manages shared FIX engine lifecycle

2. **FixEndpoint** (`components/camel-fix/src/main/java/org/apache/camel/component/fix/FixEndpoint.java`):
   - Extends `DefaultEndpoint`
   - Annotated `@UriEndpoint(scheme = "fix", syntax = "fix:sessionID", ...)`
   - Creates Consumer and Producer instances
   - URI format: `fix:sessionID?options`

3. **FixConsumer** (`components/camel-fix/src/main/java/org/apache/camel/component/fix/FixConsumer.java`):
   - Extends `DefaultConsumer`
   - Receives inbound FIX messages and feeds them into Camel routes
   - Lifecycle management: starts/stops FIX acceptor sessions

4. **FixProducer** (`components/camel-fix/src/main/java/org/apache/camel/component/fix/FixProducer.java`):
   - Extends `DefaultAsyncProducer`
   - Sends outbound FIX messages from Camel exchanges
   - Implements `process(Exchange, AsyncCallback)`

5. **FixConfiguration** (`components/camel-fix/src/main/java/org/apache/camel/component/fix/FixConfiguration.java`):
   - POJO with `@UriParams` and `@UriParam` annotations
   - Fields: configFile, senderCompID, targetCompID, fixVersion, heartBeatInterval, socketConnectHost, socketConnectPort

6. **FixConstants** (`components/camel-fix/src/main/java/org/apache/camel/component/fix/FixConstants.java`):
   - Header constants for FIX message type, session ID, sender/target comp IDs

7. **Build and registration**:
   - `components/camel-fix/pom.xml` — Maven POM inheriting from `components` parent
   - `components/pom.xml` — Add `<module>camel-fix</module>` to modules list
   - Component descriptor files for Camel's service loader

Study existing components like `camel-kafka`, `camel-netty`, or `camel-amqp` for the complete pattern.

## Context

- **Repository**: apache/camel (Java, ~2M LOC)
- **Category**: Feature Implementation
- **Difficulty**: hard
- **Subsystem Focus**: components/camel-fix/ (new module), components/pom.xml (registration)

## Requirements

1. Identify all files that need creation or modification
2. Follow existing Camel component patterns (`DefaultComponent`, `DefaultEndpoint`, `@UriEndpoint`)
3. Implement the component with actual code changes
4. Ensure the module integrates correctly with the parent build

## Expected Output

Write your analysis to `/logs/agent/solution.md` with the following structure:

```markdown
## Files Examined
- path/to/file1.ext — examined to understand [pattern/API/convention]
- path/to/file2.ext — modified to add [feature component]
...

## Dependency Chain
1. Define types/interfaces: path/to/types.ext
2. Implement core logic: path/to/impl.ext
3. Wire up integration: path/to/integration.ext
4. Add tests: path/to/tests.ext
...

## Code Changes
### path/to/file1.ext
```diff
- old code
+ new code
```

### path/to/file2.ext
```diff
- old code
+ new code
```

## Analysis
[Explanation of implementation strategy, design decisions, and how the feature
integrates with existing architecture]
```

## Evaluation Criteria

- Compilation: Does the code compile after changes?
- File coverage: Did you modify all necessary files?
- Pattern adherence: Do changes follow existing codebase conventions?
- Feature completeness: Is the feature fully implemented?
