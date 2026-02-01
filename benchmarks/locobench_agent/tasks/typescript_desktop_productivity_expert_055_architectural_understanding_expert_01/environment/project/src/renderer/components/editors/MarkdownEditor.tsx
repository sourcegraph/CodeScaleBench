```typescript
/**********************************************************************************************************************
 * File:        src/renderer/components/editors/MarkdownEditor.tsx
 * Project:     PaletteFlow Studio
 * Description: Rich Markdown editor/preview component used inside Canvas nodes.
 *              The component wraps CodeMirror 6 for editing, renders a live ReactMarkdown
 *              preview, and wires persistence to the palette-level UpdateNodeContent use-case.
 *
 * Author:      PaletteFlow Core Team
 * License:     MIT – see root LICENSE file for details.
 *********************************************************************************************************************/

import React, {
  FC,
  useCallback,
  useEffect,
  useMemo,
  useRef,
  useState,
  Suspense,
} from 'react';
import { css, cx } from '@emotion/css';
import { useDebouncedCallback } from 'use-debounce';
import { Controlled as CodeMirror } from 'react-codemirror2';
import ReactMarkdown from 'react-markdown';
import remarkGfm from 'remark-gfm';
import emoji from 'remark-emoji';
import { useObservable } from 'react-use';
import { Subject, merge } from 'rxjs';
import {
  distinctUntilChanged,
  filter,
  map,
  throttleTime,
  debounceTime,
} from 'rxjs/operators';

import { ThemeContext } from '../../contexts/ThemeContext';
import { useCommand } from '../../hooks/useCommand';
import { useHotkeys } from '../../hooks/useHotkeys';
import { ErrorBoundary } from '../shared/ErrorBoundary';
import {
  UpdateNodeContentCommand,
  UpdateNodeContentPayload,
} from '../../../domain/commands';
import {
  MarkdownToolbar,
  MarkdownToolbarContribution,
} from './MarkdownToolbar';
import { PluginManager } from '../../../plugins/PluginManager';

import 'codemirror/lib/codemirror.css';
import 'codemirror/mode/markdown/markdown';
import 'codemirror/addon/display/placeholder';
import 'codemirror/addon/selection/active-line';

// -------------------------------------------------------------------------------------------------
// Types
// -------------------------------------------------------------------------------------------------

export interface MarkdownEditorProps {
  /** UUID of the canvas node being edited. */
  nodeId: string;
  /** Initial content of the node; subsequent updates will be streamed via props. */
  initialContent: string;
  /** Whether the editor should be focused when first mounted. */
  autoFocus?: boolean;
  /** Called whenever the *server-side save* finishes (optimistic UI). */
  onPersisted?: () => void;
}

// -------------------------------------------------------------------------------------------------
// Component
// -------------------------------------------------------------------------------------------------

/**
 * Rich Markdown editor with live preview and plugin-powered toolbar.
 *
 * The component is opinionated about persistence – it dispatches UpdateNodeContentCommand after a
 * debounced interval and listens for external content changes to enable multi-window sync.
 */
export const MarkdownEditor: FC<MarkdownEditorProps> = ({
  nodeId,
  initialContent,
  autoFocus,
  onPersisted,
}) => {
  // Local UI state -------------------------------------------------------------------------------
  const [content, setContent] = useState<string>(initialContent);
  const [isPreviewMode, setPreviewMode] = useState<boolean>(false);

  // Refs -----------------------------------------------------------------------------------------
  const editorRef = useRef<CodeMirror>(null);

  // Theme ----------------------------------------------------------------------------------------
  const { theme } = React.useContext(ThemeContext);

  // Command dispatchers --------------------------------------------------------------------------
  const updateNodeContent = useCommand<UpdateNodeContentPayload>(
    UpdateNodeContentCommand,
  );

  // Event bus to stream content edits ------------------------------------------------------------
  const contentChanges$ = useMemo(() => new Subject<string>(), []);
  const externalUpdates$ = useMemo(() => new Subject<string>(), []);

  /**
   * Handle editor change event.
   */
  const handleEditorChange = useCallback(
    (_: any, __: any, value: string) => {
      setContent(value);
      contentChanges$.next(value);
    },
    [contentChanges$],
  );

  /**
   * Persist edits after the user stops typing for N milliseconds.
   */
  const persistEdits = useDebouncedCallback(
    (latest: string) => {
      updateNodeContent({ nodeId, markdown: latest })
        .then(() => onPersisted?.())
        .catch((err) => {
          // TODO: surface via global notification system
          // eslint-disable-next-line no-console
          console.error(`Failed to persist markdown for node ${nodeId}`, err);
        });
    },
    // Debounce interval tuned for best perceived latency.
    650,
  );

  // Wire in RxJS pipelines -----------------------------------------------------------------------
  useEffect(() => {
    const sub = merge(
      // Local edits
      contentChanges$.pipe(
        // Only forward if different from last value emitted
        distinctUntilChanged(),
        // Avoid spamming quick key strokes – smaller interval than persistEdits
        throttleTime(200),
        map((val) => ({
          src: 'local' as const,
          val,
        })),
      ),

      // Cross-window/server updates from externalChanges$
      externalUpdates$.pipe(
        filter((v) => v !== content),
        map((val) => ({
          src: 'external' as const,
          val,
        })),
      ),
    ).subscribe(({ src, val }) => {
      if (src === 'local') {
        // Debounced persistence
        persistEdits(val);
      } else {
        // External changes override local
        setContent(val);
      }
    });

    return () => {
      sub.unsubscribe();
      contentChanges$.complete();
      externalUpdates$.complete();
    };
  }, [content, contentChanges$, externalUpdates$, persistEdits]);

  // Hotkeys --------------------------------------------------------------------------------------
  useHotkeys(
    [
      {
        combo: 'mod+p',
        description: 'Toggle Markdown preview',
        handler: () => setPreviewMode((prev) => !prev),
      },
    ],
    [setPreviewMode],
  );

  // Toolbar contributions from plugins -----------------------------------------------------------
  const toolbarContributions = useMemo<MarkdownToolbarContribution[]>(() => {
    const plugins = PluginManager.getInstance().getToolbarContributions(
      'markdown',
    );
    return plugins;
  }, []);

  // ------------------------------------------------------------------------------------------------
  // Render
  // ------------------------------------------------------------------------------------------------

  const containerCls = cx(
    css`
      display: flex;
      flex-direction: column;
      height: 100%;
      &.pf--dark {
        background: ${theme.background700};
        color: ${theme.textPrimary};
      }
    `,
    theme.isDark ? 'pf--dark' : '',
  );

  const editorCls = css`
    flex: 1 1 auto;
    .CodeMirror {
      height: 100%;
      font-family: ${theme.fontMono};
      background-color: ${theme.background800};
      color: ${theme.textPrimary};
    }
  `;

  const previewCls = css`
    flex: 1 1 auto;
    overflow-y: auto;
    padding: 1rem;
    font-family: ${theme.fontSans};
    background: ${theme.background600};
    color: ${theme.textPrimary};

    h1,
    h2,
    h3,
    h4 {
      margin-top: 1.5rem;
      margin-bottom: 1rem;
    }

    code {
      background: ${theme.background700};
      padding: 2px 4px;
      border-radius: 4px;
      font-size: 0.85em;
    }
  `;

  return (
    <ErrorBoundary
      fallback={<div>Markdown editor crashed! See console for details.</div>}
    >
      <div className={containerCls}>
        {/* Toolbar */}
        <MarkdownToolbar
          isPreviewMode={isPreviewMode}
          onTogglePreview={setPreviewMode}
          contributions={toolbarContributions}
          onClickItem={(item) => {
            // Plugin contributions may invoke rich transforms
            item.onClick({
              editorRef: editorRef.current,
              content,
              setContent,
            });
          }}
        />

        {/* Editor / Preview Swap */}
        {isPreviewMode ? (
          <div className={previewCls}>
            <Suspense fallback={<div>Rendering preview…</div>}>
              <ReactMarkdown
                remarkPlugins={[remarkGfm, emoji]}
                // eslint-disable-next-line react/no-children-prop
                children={content}
              />
            </Suspense>
          </div>
        ) : (
          <CodeMirror
            ref={editorRef as any}
            className={editorCls}
            value={content}
            autoCursor={autoFocus}
            options={{
              mode: 'markdown',
              theme: theme.isDark ? 'material' : 'default',
              placeholder: 'Write your thoughts in Markdown…',
              lineWrapping: true,
              styleActiveLine: true,
              tabSize: 2,
            }}
            onBeforeChange={handleEditorChange}
          />
        )}
      </div>
    </ErrorBoundary>
  );
};

// -------------------------------------------------------------------------------------------------
// Default export (for React.lazy)
// -------------------------------------------------------------------------------------------------

export default React.memo(MarkdownEditor);
```
