```markdown
---
title: Command API
description: Authoritative reference for PaletteFlow Studio’s plugin command system.
sidebar_position: 20
---

# Command API

Commands are the backbone of PaletteFlow Studio’s extensibility model.  
Every time a user presses <kbd>⌘⇧P</kbd> to open the command palette, hits a
keyboard shortcut, or chooses an option from a context-menu, a `Command`
object is executed under the hood.

This document teaches you how to:

1. Declare and register a command inside your plugin
2. Receive strongly-typed execution context & arguments
3. Provide live `canRun` logic to enable/disable UI affordances
4. Report progress, throw rich errors, and return values
5. Chain commands programmatically

All code below is production-ready TypeScript that you can copy-paste into
your plugin project.

---

## Quick start

```ts title="plugins/com.acme.todo/index.ts"
import {
  definePlugin,
  CommandRegistrar,
  CommandExecutionContext,
  NodeKind,
  WorkspaceService,
  invariant,
} from 'paletteflow/plugin-sdk';

/**
 * Registers the plugin and its commands.
 */
export default definePlugin('com.acme.todo', (ctx) => {
  // Obtain a registrar scoped to this plugin instance.
  const { commands } = ctx;

  registerCreateTodoCommand(commands, ctx.services.workspaces);
});

/**
 * Registers a `todo.create` command that inserts a new TODO node
 * next to the user’s current selection.
 */
function registerCreateTodoCommand(
  registrar: CommandRegistrar,
  workspaces: WorkspaceService
): void {
  registrar.register({
    id: 'acme.todo.create',
    title: 'Create TODO Node',
    icon: 'mdi:checkbox-marked-circle-plus',
    description: 'Inserts a new pending TODO node in the active workspace.',
    shortcut: 'T',
    scope: 'workspace',

    // `canRun` is invoked *every* time the palette renders.  Keep it cheap!
    canRun: ({ workspace }) => !!workspace?.selection.first(),

    // The heart of the command.
    async run({ workspace, notify, abortSignal }: CommandExecutionContext) {
      invariant(workspace, 'Command executed outside of workspace scope');

      // React to user cancellation (e.g. ESC pressed while long task running).
      abortSignal.throwIfAborted();

      const position = workspace.selection.first()?.position ?? {
        x: workspace.viewport.center.x,
        y: workspace.viewport.center.y,
      };

      // Show visual feedback for long-running commands.
      const task = notify.progress({
        title: 'Creating TODO node',
        cancellable: true,
      });

      // Perform the actual mutation via a domain use-case.
      const nodeId = await workspaces.createNode({
        workspaceId: workspace.id,
        kind: NodeKind.Todo,
        position,
        props: { text: 'New TODO' },
        abortSignal,
      });

      await task.complete(`TODO #${nodeId} ready`);

      // Returning *anything* makes it available to chained commands.
      return { nodeId };
    },
  });
}
```

---

## Core types

```ts title="@types/plugin-sdk.d.ts"
export interface Command<TArgs = unknown, TResult = void> {
  /**
   * Unique, namespaced identifier (`[author].[domain].[verb]`).
   */
  readonly id: string;

  /**
   * Human-readable title displayed in the palette.
   */
  readonly title: string;

  /**
   * Optional Material-Design-Icon identifier (`mdi:content-copy`).
   */
  readonly icon?: string;

  /**
   * Markdown description shown in the palette side panel.
   */
  readonly description?: string;

  /**
   * Keyboard shortcut in [human-key](https://github.com/davidshort/human-key)
   * format.  Respects platform modifiers automatically.
   */
  readonly shortcut?: string;

  /**
   * Determines execution context injection & visibility rules.
   */
  readonly scope: CommandScope;

  /**
   * Executed _before_ `run`.  If it returns `false`, the command is hidden.
   */
  canRun?(ctx: CommandExecutionContext<TArgs>): boolean | Promise<boolean>;

  /**
   * The actual business logic.  Receives arguments passed programmatically
   * or via palette.
   */
  run(ctx: CommandExecutionContext<TArgs>): Promise<TResult> | TResult;
}

export type CommandScope =
  | 'global'     // Always available (e.g. “Toggle Dark Mode”)
  | 'workspace'  // Only when a workspace is active
  | 'selection'; // Only when one or more nodes are selected

export interface CommandExecutionContext<TArgs = unknown> {
  readonly args: TArgs;
  readonly workspace?: Workspace; // Present when scope != 'global'
  readonly abortSignal: AbortSignal;
  readonly notify: NotificationService;
  // `services` gives you access to any registered domain services.
  readonly services: PluginServiceLocator;
}
```

All SDK types ship with full IntelliSense so you rarely need to import them
manually; just reference `Command`, `CommandRegistrar`, etc.

---

## Programmatic invocation

Commands are first-class objects and can be chained or executed from other
commands:

```ts
await ctx.commands.execute<{ nodeId: string }>('acme.todo.create')
  .then(({ nodeId }) =>
    ctx.commands.execute('builtin.node.rename', { nodeId, newName: 'URGENT' }),
  );
```

The generic parameter describes the expected return shape, giving you full
type-safety across plugin boundaries.

---

## Error handling

Simply throw an `Error` (or a domain-specific subclass).
PaletteFlow catches it, formats the message, and surfaces it to the user.

```ts
run() {
  if (!userHasProLicense()) {
    throw new PermissionDeniedError(
      '⛔️ The “Export PDF” command requires a PaletteFlow Pro license.',
    );
  }
}
```

Unhandled rejections are automatically captured by the crash reporter—still,
strive to surface actionable, friendly messages whenever possible.

---

## Progress & cancellation

Long-running commands **must** respect the `AbortSignal` to ensure a smooth UX:

```ts
async run({ abortSignal, notify }) {
  const task = notify.progress({ title: 'Uploading...' });
  try {
    await uploadLargeFile({ abortSignal });
    await task.complete('Upload done 🎉');
  } catch (err) {
    await task.fail('Upload aborted');
    throw err;
  }
}
```

Pressing <kbd>ESC</kbd> or closing the workspace window aborts the signal,
letting you free resources immediately.

---

## Dynamic enablement

`canRun` can return an `Observable<boolean>` (RxJS), making palette items
reactive. For example, disable “Redo” when the history stack is empty:

```ts
import { map } from 'rxjs/operators';

registrar.register({
  id: 'builtin.history.redo',
  title: 'Redo',
  icon: 'mdi:redo',
  scope: 'workspace',
  canRun: ctx.workspace!.history.canRedo$, // Observable<boolean>
  run: () => ctx.workspace!.history.redo(),
});
```

The palette subscribes & unsubscribes automatically to avoid memory leaks.

---

## Built-in commands

| ID                           | Description                  | Scope      |
| ---------------------------- | ---------------------------- | ---------- |
| `builtin.workspace.save`     | Save current workspace       | workspace  |
| `builtin.viewport.center`    | Center view on selection     | selection  |
| `builtin.toggle.darkmode`    | Switch UI theme              | global     |

Call `ctx.commands.getAll()` to discover the entire set at runtime.

---

## Gotchas & best practices

• **Keep `run` pure**—delegate mutations to domain services/use-cases.  
• **Return value** only when the caller might care; otherwise `void`.  
• **Namespace** your IDs to avoid clashes (`<vendor>.<feature>.<verb>`).  
• **Document** your commands so other plugins can compose them seamlessly.

Happy building!
```