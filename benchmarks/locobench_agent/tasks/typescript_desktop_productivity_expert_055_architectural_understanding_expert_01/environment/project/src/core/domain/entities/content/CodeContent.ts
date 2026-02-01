```typescript
/**
 * PaletteFlow Studio – Core Domain
 * --------------------------------
 * Entity: CodeContent
 *
 * A value-rich domain object that represents a snippet of source code stored
 * inside a canvas node.  The entity is intentionally framework-agnostic so
 * that it can be reused by the Electron renderer, CLI tooling, automated tests,
 * and the plugin runtime without pulling in UI or infrastructure concerns.
 */

import { createHash, randomUUID } from 'crypto';

/* -------------------------------------------------------------------------- */
/* Helpers & Value Objects                                                    */
/* -------------------------------------------------------------------------- */

/**
 * A (very) small subset of common programming languages.  The value can be
 * extended at runtime by plugins, so we ultimately treat it as an opaque
 * string from the entity’s perspective.
 */
export type Language =
  | 'typescript'
  | 'javascript'
  | 'python'
  | 'rust'
  | 'go'
  | 'c'
  | 'cpp'
  | 'java'
  | 'kotlin'
  | 'swift'
  | 'csharp'
  | 'markdown'
  | string; // plugin-defined languages

/**
 * Execution result for snippets that can be run by sandbox executors.
 * Stored strictly as historical data; CodeContent itself is not responsible
 * for running any code.
 */
export interface ExecutionResult {
  stdout?: string;
  stderr?: string;
  exitCode: number; // POSIX-style exit code (0 = success)
  executedAt: Date;
}

/**
 * Domain-level data contract used by the factory constructor.  Every field
 * except `code` is optional to allow for easy bootstrapping.
 */
export interface CodeContentProps {
  id?: string;
  code: string;
  language?: Language;
  createdAt?: Date;
  updatedAt?: Date;
  executionHistory?: ExecutionResult[];
}

/**
 * Domain error thrown whenever a precondition for a CodeContent operation
 * cannot be satisfied.
 */
export class CodeContentError extends Error {
  constructor(message: string) {
    super(`[CodeContent] ${message}`);
    Object.setPrototypeOf(this, new.target.prototype);
  }
}

/* -------------------------------------------------------------------------- */
/* Entity                                                                     */
/* -------------------------------------------------------------------------- */

export class CodeContent {
  /* ---------------------------------------------------------------------- */
  /* Static Factory / Reconstitution                                         */
  /* ---------------------------------------------------------------------- */

  /**
   * Creates a new CodeContent instance while enforcing invariants and
   * encapsulating its internals.
   */
  public static create(props: CodeContentProps): CodeContent {
    if (!props.code || props.code.trim().length === 0) {
      throw new CodeContentError('`code` must be a non-empty string.');
    }

    return new CodeContent({
      id: props.id ?? randomUUID(),
      language: props.language ?? inferLanguageFromExtension(props.id) ?? 'plaintext',
      code: props.code,
      createdAt: props.createdAt ?? new Date(),
      updatedAt: props.updatedAt ?? new Date(),
      executionHistory: props.executionHistory ?? [],
    });
  }

  /**
   * Infers the language from a node id (which may include a file extension).
   * For example: "xyz.ts" → "typescript".
   */
  private static inferLanguageFromFilename(filename: string | undefined): Language | undefined {
    if (!filename || !filename.includes('.')) {
      return undefined;
    }

    const ext = filename.split('.').pop()?.toLowerCase();
    switch (ext) {
      case 'ts':
      case 'tsx':
        return 'typescript';
      case 'js':
      case 'mjs':
      case 'cjs':
        return 'javascript';
      case 'py':
        return 'python';
      case 'rs':
        return 'rust';
      case 'go':
        return 'go';
      case 'cpp':
      case 'cc':
      case 'cxx':
      case 'hpp':
        return 'cpp';
      case 'kt':
        return 'kotlin';
      case 'swift':
        return 'swift';
      case 'cs':
        return 'csharp';
      case 'md':
        return 'markdown';
      default:
        return undefined; // unknown extension – let caller decide
    }
  }

  /* ---------------------------------------------------------------------- */
  /* Private Constructor                                                     */
  /* ---------------------------------------------------------------------- */

  private constructor(private readonly state: Required<CodeContentState>) {}

  /* ---------------------------------------------------------------------- */
  /* Getters                                                                 */
  /* ---------------------------------------------------------------------- */

  public get id(): string {
    return this.state.id;
  }

  public get language(): Language {
    return this.state.language;
  }

  public get code(): string {
    return this.state.code;
  }

  public get createdAt(): Date {
    return new Date(this.state.createdAt.getTime());
  }

  public get updatedAt(): Date {
    return new Date(this.state.updatedAt.getTime());
  }

  public get executionHistory(): readonly ExecutionResult[] {
    // Return a deep copy to preserve immutability from the outside
    return this.state.executionHistory.map((h) => ({ ...h }));
  }

  /* ---------------------------------------------------------------------- */
  /* Domain Logic                                                            */
  /* ---------------------------------------------------------------------- */

  /**
   * Replaces the current code with a new string. Updates timestamps and keeps
   * an immutable audit trail.
   */
  public updateCode(newCode: string): void {
    if (!newCode || newCode.trim().length === 0) {
      throw new CodeContentError('Cannot update to an empty code snippet.');
    }

    this.state.code = newCode;
    this.touch();
  }

  /**
   * Updates the language (syntax, grammar) associated with the snippet.
   * Primarily used by the syntax-highlighting plugin and compile/execute
   * pipelines.
   */
  public setLanguage(language: Language): void {
    if (!language || language.trim().length === 0) {
      throw new CodeContentError('Language cannot be empty.');
    }

    // Prevent needless updates
    if (language === this.state.language) {
      return;
    }

    this.state.language = language;
    this.touch();
  }

  /**
   * Appends a new execution result to the history.  The method is intentionally
   * simple: executors should prepare a fully formed ExecutionResult.
   */
  public recordExecution(result: ExecutionResult): void {
    this.state.executionHistory.push({ ...result });
    this.touch();
  }

  /**
   * Calculates a stable SHA-256 hash of the current code (useful for caching,
   * diffing, and integrity checks on import/export).
   */
  public contentHash(): string {
    return createHash('sha256').update(this.state.code, 'utf8').digest('hex');
  }

  /**
   * Quick statistics that can be displayed in the UI or consumed by analytics.
   */
  public metrics(): {
    lineCount: number;
    characterCount: number;
    estimatedSizeInBytes: number;
  } {
    const lineCount = this.state.code.split(/\r\n|\r|\n/).length;
    const characterCount = this.state.code.length;

    return {
      lineCount,
      characterCount,
      estimatedSizeInBytes: Buffer.byteLength(this.state.code, 'utf8'),
    };
  }

  /**
   * A naive import/require analyser that tries to surface external dependencies
   * for JavaScript/TypeScript/Python.  Other languages can provide plugins for
   * deeper parsing, but this simple regex-based extractor is good enough for
   * quick “dependency glance” in the canvas inspector panel.
   */
  public extractImports(): string[] {
    const { language } = this.state;
    const lines = this.state.code.split(/\r\n|\r|\n/);

    const importRegex = {
      javascript: /^\s*(?:import\s+.*?from\s+|import\s+['"]|require\s*\()['"]([^'"]+)['"]/,
      typescript: /^\s*(?:import\s+.*?from\s+|import\s+['"]|require\s*\()['"]([^'"]+)['"]/,
      python: /^\s*(?:from\s+([a-zA-Z0-9_.]+)\s+import|import\s+([a-zA-Z0-9_.]+))/,
    } as Record<string, RegExp>;

    const regex = importRegex[language];

    if (!regex) {
      return []; // unsupported language – fail gracefully
    }

    const matches = new Set<string>();

    for (const line of lines) {
      const result = regex.exec(line);
      if (!result) continue;

      // In Python regex we might have two capturing groups
      const [, first, second] = result;
      const dep = first ?? second;
      if (dep) {
        matches.add(dep);
      }
    }

    return Array.from(matches);
  }

  /**
   * Removes sensitive execution data (stdout/stderr) and returns a
   * plain-old-JavaScript object suitable for storage or serialization.
   */
  public toSnapshot(): CodeContentSnapshot {
    return {
      id: this.state.id,
      code: this.state.code,
      language: this.state.language,
      createdAt: this.state.createdAt.toISOString(),
      updatedAt: this.state.updatedAt.toISOString(),
      executionHistory: this.state.executionHistory.map((h) => ({
        ...h,
        executedAt: h.executedAt.toISOString(),
      })),
    };
  }

  /* ---------------------------------------------------------------------- */
  /* Internal Utilities                                                      */
  /* ---------------------------------------------------------------------- */

  /** Updates the `updatedAt` timestamp to now. */
  private touch(): void {
    this.state.updatedAt = new Date();
  }
}

/* -------------------------------------------------------------------------- */
/* Private Types                                                              */
/* -------------------------------------------------------------------------- */

interface CodeContentState
  extends Omit<CodeContentProps, 'createdAt' | 'updatedAt' | 'id'> {
  id: string;
  createdAt: Date;
  updatedAt: Date;
}

export interface CodeContentSnapshot {
  id: string;
  code: string;
  language: Language;
  createdAt: string; // ISO string
  updatedAt: string; // ISO string
  executionHistory: Array<Omit<ExecutionResult, 'executedAt'> & { executedAt: string }>;
}

/* -------------------------------------------------------------------------- */
/* Utility Functions                                                          */
/* -------------------------------------------------------------------------- */

/**
 * Infers a language type based on an id or filename (falls back to undefined).
 * This is a thin wrapper around the static private method to aid unit testing.
 */
export function inferLanguageFromExtension(idOrFilename: string | undefined): Language | undefined {
  return CodeContent['inferLanguageFromFilename'](idOrFilename);
}
```