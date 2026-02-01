```tsx
/* PaletteFlow Studio
 * File: src/renderer/components/shell/CommandPalette.tsx
 *
 * The CommandPalette is a keyboard-driven overlay similar to VS Code’s “⌘ P”
 * palette.  Any feature—core or plugin—can register a PaletteCommand with the
 * global CommandRegistry.  This React component listens to the registry,
 * supports fuzzy-search with Fuse.js, and executes commands when the user
 * selects one.
 */

import React, {
  KeyboardEvent,
  ReactNode,
  useCallback,
  useEffect,
  useMemo,
  useRef,
  useState,
} from 'react';
import ReactDOM from 'react-dom';
import Fuse from 'fuse.js';
import styled, { css } from 'styled-components';

// ────────────────────────────────────────────────────────────────────────────────
// Domain & infrastructure imports
// ────────────────────────────────────────────────────────────────────────────────
import { CommandRegistry } from '../../infrastructure/commands/CommandRegistry'; // singleton
import { Analytics } from '../../infrastructure/analytics/Analytics'; // for crash reporting + usage stats
import { useHotkeys } from '../../hooks/useHotkeys'; // thin wrapper around 'react-hotkeys-hook'

// ────────────────────────────────────────────────────────────────────────────────
// Types
// ────────────────────────────────────────────────────────────────────────────────
export interface PaletteCommand {
  /** Unique identifier, namespaced (e.g. 'canvas.createNode') */
  id: string;
  /** Main headline shown in the palette */
  title: string;
  /** Optional secondary text */
  subtitle?: string;
  /** Optional React node or URL string for an icon */
  icon?: ReactNode | string;
  /** For fuzzy matching */
  keywords?: string[];
  /** Handler invoked when the user selects the command */
  handler: () => Promise<void> | void;
  /** Visual grouping (e.g. “File”, “View”, plugin name) */
  group?: string;
  /** Higher priority bubbles to the top when no query is provided */
  priority?: number;
}

// ────────────────────────────────────────────────────────────────────────────────
// Styled-components
// ────────────────────────────────────────────────────────────────────────────────
const Overlay = styled.div<{ visible: boolean }>`
  position: fixed;
  inset: 0;
  background: rgba(0, 0, 0, 0.35);
  backdrop-filter: blur(2px);
  z-index: 9999;
  display: ${({ visible }) => (visible ? 'flex' : 'none')};
  align-items: flex-start;
  justify-content: center;
  padding-top: 12vh;
`;

const PaletteBox = styled.div`
  width: 640px;
  max-width: 90vw;
  background-color: ${({ theme }) => theme.colors.elevatedBackground ?? '#1e1e1e'};
  color: ${({ theme }) => theme.colors.textPrimary ?? '#fafafa'};
  border-radius: 8px;
  box-shadow: 0 12px 32px rgba(0, 0, 0, 0.45);
  overflow: hidden;
  display: flex;
  flex-direction: column;
`;

const SearchInput = styled.input`
  width: 100%;
  padding: 14px 16px;
  font-size: 1.05rem;
  border: none;
  outline: none;
  background: transparent;
  color: inherit;

  ::placeholder {
    color: ${({ theme }) => theme.colors.textSecondary ?? '#8f8f8f'};
  }
`;

const Results = styled.ul`
  list-style: none;
  margin: 0;
  padding: 0;
  max-height: 360px;
  overflow-y: auto;
`;

const ResultItem = styled.li<{ active: boolean }>`
  display: flex;
  align-items: center;
  gap: 12px;
  padding: 10px 16px;
  cursor: pointer;
  ${({ active, theme }) =>
    active
      ? css`
          background: ${theme.colors.selection ?? '#264f78'};
        `
      : css`
          &:hover {
            background: ${theme.colors.selectionHover ?? '#2c2c2c'};
          }
        `}
`;

const Title = styled.span`
  font-size: 0.95rem;
  line-height: 1.3;
`;

const Subtitle = styled.span`
  font-size: 0.8rem;
  opacity: 0.65;
`;

const IconWrapper = styled.div`
  width: 18px;
  height: 18px;
  flex-shrink: 0;
  svg,
  img {
    width: 100%;
    height: 100%;
    object-fit: contain;
  }
`;

// Placeholder root element for the portal (created once at runtime)
let portalRoot: HTMLElement | null = null;
function ensurePortalRoot(): HTMLElement {
  if (!portalRoot) {
    portalRoot = document.createElement('div');
    portalRoot.id = 'pf-command-palette-portal';
    document.body.appendChild(portalRoot);
  }
  return portalRoot;
}

// ────────────────────────────────────────────────────────────────────────────────
// Component
// ────────────────────────────────────────────────────────────────────────────────
export const CommandPalette: React.FC = () => {
  const [visible, setVisible] = useState(false);
  const [query, setQuery] = useState('');
  const [commands, setCommands] = useState<PaletteCommand[]>([]);
  const [activeIndex, setActiveIndex] = useState(0);

  // Ref to the input to programmatically focus when the palette opens
  const inputRef = useRef<HTMLInputElement>(null);

  // Resolve the command list from the registry
  const refreshCommands = useCallback(() => {
    setCommands(CommandRegistry.getAll());
  }, []);

  // Listen to registry updates (plugins may register at runtime)
  useEffect(() => {
    refreshCommands(); // initial load

    const unsubscribe = CommandRegistry.onChange(refreshCommands);
    return () => unsubscribe();
  }, [refreshCommands]);

  // Keyboard shortcut to toggle the palette
  useHotkeys(
    ['ctrl+p', 'command+p', 'ctrl+k', 'command+k'],
    () => setVisible((v) => !v),
    { preventDefault: true },
    []
  );

  // Close palette on ESC when visible
  useHotkeys(
    ['esc'],
    () => {
      if (visible) close();
    },
    { enableOnFormTags: ['INPUT'] },
    [visible]
  );

  // Build the Fuse.js index whenever commands change
  const fuse = useMemo(() => {
    return new Fuse(commands, {
      keys: ['title', 'subtitle', 'keywords'],
      threshold: 0.35,
      ignoreLocation: true,
      includeScore: true,
    });
  }, [commands]);

  // Compute search results
  const results = useMemo(() => {
    if (!query) {
      // Default ordering by priority desc then title asc
      return [...commands].sort(
        (a, b) => (b.priority ?? 0) - (a.priority ?? 0) || a.title.localeCompare(b.title)
      );
    }
    return fuse.search(query).map((r) => r.item);
  }, [query, commands, fuse]);

  // Keep active index within bounds
  useEffect(() => {
    setActiveIndex((i) => Math.max(0, Math.min(i, results.length - 1)));
  }, [results.length]);

  // Focus the search input when palette becomes visible
  useEffect(() => {
    if (visible) {
      // Defer to next tick so element exists
      setTimeout(() => inputRef.current?.focus(), 0);
    } else {
      setQuery('');
    }
  }, [visible]);

  const close = () => {
    setVisible(false);
  };

  const executeCommand = async (cmd: PaletteCommand) => {
    close();
    try {
      await cmd.handler();
      Analytics.track('command_executed', { id: cmd.id });
    } catch (err) {
      console.error(`Command "${cmd.id}" failed`, err);
      Analytics.captureException(err, { context: 'command_palette', commandId: cmd.id });
    }
  };

  const handleKeyDown = (e: KeyboardEvent) => {
    if (e.key === 'ArrowDown') {
      e.preventDefault();
      setActiveIndex((i) => (i + 1) % results.length);
    } else if (e.key === 'ArrowUp') {
      e.preventDefault();
      setActiveIndex((i) => (i - 1 + results.length) % results.length);
    } else if (e.key === 'Enter') {
      e.preventDefault();
      const cmd = results[activeIndex];
      if (cmd) executeCommand(cmd);
    }
  };

  // ──────────────────────────────────────────────────────────────────────────
  // Render helpers
  // ──────────────────────────────────────────────────────────────────────────
  const renderIcon = (icon: PaletteCommand['icon']) => {
    if (!icon) return null;
    if (React.isValidElement(icon)) return icon;
    // assume string -> treat as URL
    return <img src={icon as string} alt="" draggable={false} />;
  };

  const body = (
    <Overlay visible={visible} onClick={close}>
      <PaletteBox
        onClick={(e) => e.stopPropagation()} // Prevent overlay close when clicking inside
        onKeyDown={handleKeyDown}
      >
        <SearchInput
          ref={inputRef}
          placeholder="Type a command or search…"
          value={query}
          onChange={(e) => setQuery(e.target.value)}
          autoComplete="off"
          spellCheck={false}
        />

        <Results>
          {results.length === 0 && (
            <ResultItem active={false} style={{ pointerEvents: 'none' }}>
              <Title>No commands found</Title>
            </ResultItem>
          )}

          {results.map((cmd, idx) => (
            <ResultItem
              key={cmd.id}
              active={idx === activeIndex}
              onMouseEnter={() => setActiveIndex(idx)}
              onClick={() => executeCommand(cmd)}
            >
              {cmd.icon && <IconWrapper>{renderIcon(cmd.icon)}</IconWrapper>}
              <div style={{ flex: 1, display: 'flex', flexDirection: 'column' }}>
                <Title>{cmd.title}</Title>
                {cmd.subtitle && <Subtitle>{cmd.subtitle}</Subtitle>}
              </div>
            </ResultItem>
          ))}
        </Results>
      </PaletteBox>
    </Overlay>
  );

  return ReactDOM.createPortal(body, ensurePortalRoot());
};

// ────────────────────────────────────────────────────────────────────────────────
// Command registration helper (optional but convenient)
// ────────────────────────────────────────────────────────────────────────────────
/**
 * Registers a command and returns a disposer that removes it again.
 * Plugins can import { registerCommand } from 'CommandPalette' rather than
 * using CommandRegistry directly, keeping the renderer decoupled.
 */
export function registerCommand(cmd: PaletteCommand): () => void {
  return CommandRegistry.register(cmd);
}
```