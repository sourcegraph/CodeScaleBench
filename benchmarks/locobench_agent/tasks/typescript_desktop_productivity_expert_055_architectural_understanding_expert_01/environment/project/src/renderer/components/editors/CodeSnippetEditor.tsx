```typescript
/**************************************************************************************************
 * File: CodeSnippetEditor.tsx
 * Project: PaletteFlow Studio
 * Description:
 *   React component that embeds a Monaco-powered editor for “Code Snippet” canvas nodes.
 *   The component is responsible for:
 *     • Boot-strapping Monaco with palette plugins (languages, themes, intelli-sense providers)
 *     • Persisting edits through the domain use-case `UpdateNodeContent`
 *     • Respecting the global UI theme (light / dark, font-family, font-size, …)
 *     • Emitting change events to the rest of the application (node dirty-state, undo-stack, …)
 *     • Exposing a light command palette (format, copy, share) via hot-keys
 *
 * Clean-Architecture notes:
 *   – No domain logic lives here; we merely invoke injected use-cases / gateways.
 *   – We never import Electron/Node APIs directly, but go through thin renderer-side adapters.
 **************************************************************************************************/

import React, {
  useCallback,
  useEffect,
  useLayoutEffect,
  useMemo,
  useRef,
  useState,
} from 'react';
import * as monaco from 'monaco-editor';
import { useDebouncedCallback } from 'use-debounce';
import { useHotkeys } from 'react-hotkeys-hook';
import { nanoid } from 'nanoid';

import { UpdateNodeContent } from '@core/use-cases/UpdateNodeContent';
import { NodeRepository } from '@core/repositories/NodeRepository';
import { useTheme } from '@renderer/hooks/useTheme';
import { eventBus } from '@renderer/services/eventBus';
import { notify } from '@renderer/services/notifications';
import { wrapDomainError } from '@renderer/utils/errorBoundary';
import { pluginRegistry } from '@core/plugins';

type Props = {
  /**
   * Canvas node identifier (stable across workspace sessions)
   */
  nodeId: string;

  /**
   * The canonical code text for the node.
   */
  initialCode: string;

  /**
   * Programming language of the snippet (e.g. "typescript", "python")
   * When omitted the language is detected via plugins or defaults to plaintext.
   */
  language?: string;

  /**
   * When true the editor is rendered read-only.
   */
  readOnly?: boolean;

  /**
   * Additional CSS classes for container div.
   */
  className?: string;
};

/**
 * Utility: correlates a Monaco model to a palette node so multiple editors
 * pointing at the same node share the same undo / version history.
 */
const getModelUri = (nodeId: string) =>
  monaco.Uri.parse(`palette-node://${nodeId}.code`);

export const CodeSnippetEditor: React.FC<Props> = ({
  nodeId,
  initialCode,
  language,
  readOnly = false,
  className,
}) => {
  /***********************************************************************************************
   * Refs & State
   **********************************************************************************************/
  const containerRef = useRef<HTMLDivElement | null>(null);
  const editorRef = useRef<monaco.editor.IStandaloneCodeEditor | null>(null);
  const [isDirty, setDirty] = useState(false);
  const theme = useTheme(); // ← renderer hook that tracks global theme store

  /***********************************************************************************************
   * Boot-strap Monaco editor
   **********************************************************************************************/
  useLayoutEffect(() => {
    if (!containerRef.current) return;

    /**** Register plugin contributions BEFORE the editor is instantiated ****/
    pluginRegistry.languages.registerAllWithMonaco(monaco);
    pluginRegistry.editor.configureMonaco(monaco);

    const modelUri = getModelUri(nodeId);

    // Re-use existing model when the node is mounted in multiple views
    const model =
      monaco.editor.getModel(modelUri) ??
      monaco.editor.createModel(
        initialCode,
        language ?? inferLanguageFromFileName(nodeId) ?? 'plaintext',
        modelUri,
      );

    editorRef.current = monaco.editor.create(containerRef.current, {
      language: model.getLanguageId(),
      readOnly,
      minimap: { enabled: false },
      automaticLayout: true, // ← React-friendly
      scrollBeyondLastLine: false,
      fontFamily: theme.monoFont,
      fontSize: theme.fontSize,
      theme: theme.isDark ? 'vs-dark' : 'vs',
      model,
    });

    const subscription = model.onDidChangeContent(() => {
      if (!isDirty) setDirty(true);
      emitNodeChange(model.getValue());
      debouncedPersist(model.getValue());
    });

    return () => {
      subscription.dispose();
      editorRef.current?.dispose();
      // keep the model alive – other views might still use it
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []); // run once

  /***********************************************************************************************
   * Sync Monaco theme when the user toggles light/dark at runtime
   **********************************************************************************************/
  useEffect(() => {
    monaco.editor.setTheme(theme.isDark ? 'vs-dark' : 'vs');
    if (editorRef.current) {
      editorRef.current.updateOptions({
        fontFamily: theme.monoFont,
        fontSize: theme.fontSize,
      });
    }
  }, [theme]);

  /***********************************************************************************************
   * Debounced persistence (500 ms after last keystroke)
   **********************************************************************************************/
  const debouncedPersist = useDebouncedCallback(
    async (nextCode: string) => {
      try {
        await new UpdateNodeContent(NodeRepository.current).execute({
          nodeId,
          mimeType: 'text/x-code',
          content: nextCode,
        });
        setDirty(false);
        eventBus.publish('node:saved', { nodeId });
      } catch (err) {
        notify.error('Failed to save code snippet', wrapDomainError(err));
      }
    },
    500,
    { maxWait: 2000 },
  );

  /***********************************************************************************************
   * Command palette / keyboard shortcuts
   **********************************************************************************************/
  useHotkeys(
    'cmd+s,ctrl+s',
    (ev) => {
      ev.preventDefault();
      editorRef.current?.getAction('editor.action.formatDocument')?.run();
      debouncedPersist.flush(); // immediately persist
    },
    { enableOnTags: ['TEXTAREA', 'INPUT'] },
    [debouncedPersist],
  );

  useHotkeys(
    'cmd+shift+c,ctrl+shift+c',
    () => {
      if (!editorRef.current) return;
      navigator.clipboard
        .writeText(editorRef.current.getModel()?.getValue() ?? '')
        .then(() => notify.success('Code copied to clipboard'))
        .catch((err) => notify.error('Clipboard error', err));
    },
    {},
    [],
  );

  /***********************************************************************************************
   * Callbacks
   **********************************************************************************************/
  const emitNodeChange = useCallback(
    (code: string) => {
      eventBus.publish('node:dirty', { nodeId, value: code });
    },
    [nodeId],
  );

  /***********************************************************************************************
   * Render
   **********************************************************************************************/
  return (
    <div
      ref={containerRef}
      className={className}
      data-node-id={nodeId}
      style={{ height: '100%', width: '100%' }}
    />
  );
};

/**************************************************************************************************
 * Helpers
 **************************************************************************************************/

/**
 * Attempts to infer the programming language by nodeId (which doubles
 * as filename for file-backed nodes via plugins).
 */
const inferLanguageFromFileName = (nodeId: string): string | undefined => {
  const ext = (nodeId.split('.').pop() ?? '').toLowerCase();
  return (
    ({
      ts: 'typescript',
      tsx: 'typescript',
      js: 'javascript',
      jsx: 'javascript',
      py: 'python',
      rb: 'ruby',
      cs: 'csharp',
      rs: 'rust',
      go: 'go',
      java: 'java',
      cpp: 'cpp',
      c: 'c',
      html: 'html',
      css: 'css',
      scss: 'scss',
      json: 'json',
      yml: 'yaml',
      yaml: 'yaml',
      sql: 'sql',
      md: 'markdown',
    } as Record<string, string>)[ext] ?? undefined
  );
};

/**************************************************************************************************
 * Type-safety augmentation for palette plugins
 **************************************************************************************************/

declare global {
  // eslint-disable-next-line @typescript-eslint/no-namespace
  namespace Monaco {
    interface IExportsFromPlugin {
      /**
       * Plugins can register additional language definitions.
       */
      languages: {
        registerAllWithMonaco(m: typeof monaco): void;
      };

      /**
       * Plugins can patch Monaco’s global settings.
       */
      editor: {
        configureMonaco(m: typeof monaco): void;
      };
    }
  }
}

/**************************************************************************************************
 * Dev-time diagnostics (removed in production via tree-shaking)
 **************************************************************************************************/
if (process.env.NODE_ENV === 'development') {
  // eslint-disable-next-line no-console
  console.debug(
    `[CodeSnippetEditor] mounted for node ${nanoid(6)} (${window.location.hash})`,
  );
}
```