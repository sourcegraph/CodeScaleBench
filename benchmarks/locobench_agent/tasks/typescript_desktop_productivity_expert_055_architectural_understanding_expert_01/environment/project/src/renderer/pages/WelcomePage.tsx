```typescript
/* PaletteFlow Studio ─ Welcome Page
 * ---------------------------------
 * Responsible for greeting users on cold-start and providing
 * quick entry points into the application:
 *   • Create a new workspace
 *   • Open an existing workspace
 *   • Re-open a recent workspace
 *   • Discover featured plugins & themes
 *
 * The component talks to the Electron main process exclusively
 * through IPC channels defined in
 *    packages/main/src/ipc/channels.ts
 *
 * NOTE:
 *  • This file purposely avoids any domain-specific business
 *    logic.  All use-cases live in the main process or in the
 *    domain layer and are exposed over IPC.
 *  • The renderer never reads the file-system directly.
 */

import React, {
  FC,
  useCallback,
  useEffect,
  useMemo,
  useState,
  KeyboardEvent,
} from 'react';
import { ipcRenderer } from 'electron';
import styled from 'styled-components';
import { FiFolderPlus, FiFolderOpen, FiZap, FiDownload } from 'react-icons/fi';
import { formatDistanceToNow } from 'date-fns';

import {
  IPC_CHANNELS,
  RecentWorkspaceDTO,
  PluginMarketplaceDTO,
  RendererToMainError,
} from '../../shared/ipc';

/* ------------------------------------------------------------------ */
/* ─────────────────────────  Styled  ─────────────────────────────── */
/* ------------------------------------------------------------------ */

const PageContainer = styled.div`
  display: flex;
  flex-direction: column;
  height: 100%;
  background: ${({ theme }) => theme.background.secondary};
  color: ${({ theme }) => theme.text.primary};
  overflow: hidden;
`;

const Header = styled.header`
  padding: 2.5rem 3rem 1.5rem;
  font-size: 2.4rem;
  font-weight: 800;
  user-select: none;
`;

const Content = styled.main`
  flex: 1;
  display: flex;
  gap: 2.5rem;
  padding: 0 3rem 3rem;
  overflow-y: auto;
`;

const Column = styled.section<{ shrink?: boolean }>`
  flex: ${({ shrink }) => (shrink ? '0 0 380px' : '1')};
  display: flex;
  flex-direction: column;
  gap: 1.4rem;
`;

const Card = styled.div`
  background: ${({ theme }) => theme.background.tertiary};
  border: 1px solid ${({ theme }) => theme.border.light};
  border-radius: 8px;
  padding: 1.2rem 1.4rem;
`;

const CardTitle = styled.h3`
  font-size: 1.25rem;
  font-weight: 600;
  margin: 0 0 0.8rem 0;
`;

const QuickAction = styled.button`
  display: flex;
  align-items: center;
  gap: 0.8rem;
  width: 100%;
  padding: 0.9rem 1rem;
  border: none;
  border-radius: 6px;
  font-size: 0.95rem;
  font-weight: 500;
  color: ${({ theme }) => theme.text.primary};
  background: ${({ theme }) => theme.button.secondary};
  cursor: pointer;
  transition: background 0.15s ease;

  &:hover {
    background: ${({ theme }) => theme.button.secondaryHover};
  }

  &:focus-visible {
    outline: 2px solid ${({ theme }) => theme.accent.primary};
  }

  svg {
    flex-shrink: 0;
  }
`;

const List = styled.ul`
  margin: 0;
  padding: 0;
  list-style: none;
`;

const ListItem = styled.li`
  display: flex;
  justify-content: space-between;
  align-items: center;
  padding: 0.6rem 0.3rem;
  border-bottom: 1px solid ${({ theme }) => theme.border.light};

  &:last-child {
    border-bottom: none;
  }

  button {
    border: none;
    background: transparent;
    padding: 0.4rem 0.6rem;
    opacity: 0.7;
    cursor: pointer;
    transition: opacity 0.15s;

    &:hover {
      opacity: 1;
    }
  }
`;

const ErrorBanner = styled.div`
  background: ${({ theme }) => theme.error.background};
  color: ${({ theme }) => theme.error.text};
  padding: 0.8rem 1rem;
  border-radius: 4px;
  font-size: 0.85rem;
  margin-bottom: 1rem;
`;

const Spinner = styled.div`
  width: 24px;
  height: 24px;
  border: 3px solid ${({ theme }) => theme.border.light};
  border-top-color: ${({ theme }) => theme.accent.primary};
  border-radius: 50%;
  animation: spin 0.9s linear infinite;

  @keyframes spin {
    to {
      transform: rotate(360deg);
    }
  }
`;

/* ------------------------------------------------------------------ */
/* ────────────────────────  Component  ───────────────────────────── */
/* ------------------------------------------------------------------ */

const WelcomePage: FC = () => {
  /* --------------------------- state ---------------------------- */

  const [recentWorkspaces, setRecentWorkspaces] = useState<
    RecentWorkspaceDTO[]
  >([]);
  const [featuredPlugins, setFeaturedPlugins] = useState<
    PluginMarketplaceDTO[]
  >([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<RendererToMainError | null>(null);

  /* ---------------------- side-effects -------------------------- */

  useEffect(() => {
    let disposed = false;

    const fetchInitialData = async () => {
      try {
        setLoading(true);
        const [recent, plugins] = await Promise.all([
          ipcRenderer.invoke(IPC_CHANNELS.RECENT_WORKSPACES_LIST),
          ipcRenderer.invoke(IPC_CHANNELS.PLUGIN_MARKETPLACE_FEATURED),
        ]);

        if (disposed) return;
        setRecentWorkspaces(recent);
        setFeaturedPlugins(plugins);
        setLoading(false);
      } catch (err) {
        if (disposed) return;
        setError(err as RendererToMainError);
        setLoading(false);
      }
    };

    fetchInitialData();
    return () => {
      disposed = true;
    };
  }, []);

  /* ---------------------- handlers ------------------------------- */

  const handleCreateWorkspace = useCallback(async () => {
    try {
      await ipcRenderer.invoke(IPC_CHANNELS.WORKSPACE_CREATE);
    } catch (err) {
      setError(err as RendererToMainError);
    }
  }, []);

  const handleOpenWorkspaceDialog = useCallback(async () => {
    try {
      await ipcRenderer.invoke(IPC_CHANNELS.DIALOG_OPEN_WORKSPACE);
    } catch (err) {
      setError(err as RendererToMainError);
    }
  }, []);

  const handleOpenRecentWorkspace = useCallback(async (path: string) => {
    try {
      await ipcRenderer.invoke(IPC_CHANNELS.WORKSPACE_OPEN, path);
    } catch (err) {
      setError(err as RendererToMainError);
    }
  }, []);

  const handleInstallPlugin = useCallback(async (pluginId: string) => {
    try {
      await ipcRenderer.invoke(IPC_CHANNELS.PLUGIN_INSTALL, pluginId);
    } catch (err) {
      setError(err as RendererToMainError);
    }
  }, []);

  const handleKeyboardShortcuts = useCallback(
    (e: KeyboardEvent<HTMLDivElement>) => {
      if (e.ctrlKey || e.metaKey) {
        switch (e.key.toLowerCase()) {
          case 'n':
            e.preventDefault();
            handleCreateWorkspace();
            break;
          case 'o':
            e.preventDefault();
            handleOpenWorkspaceDialog();
            break;
        }
      }
    },
    [handleCreateWorkspace, handleOpenWorkspaceDialog],
  );

  /* ------------------------ memoized ----------------------------- */

  const sortedRecent = useMemo(
    () =>
      [...recentWorkspaces].sort(
        (a, b) =>
          new Date(b.lastOpened).getTime() - new Date(a.lastOpened).getTime(),
      ),
    [recentWorkspaces],
  );

  /* ------------------------- render ------------------------------ */

  if (loading) {
    return (
      <PageContainer>
        <Header>Welcome to PaletteFlow Studio</Header>
        <Content style={{ alignItems: 'center', justifyContent: 'center' }}>
          <Spinner />
        </Content>
      </PageContainer>
    );
  }

  return (
    <PageContainer tabIndex={0} onKeyDown={handleKeyboardShortcuts}>
      <Header>Welcome to PaletteFlow Studio</Header>
      <Content>
        {/* Left column: Quick actions */}
        <Column shrink>
          {error && (
            <ErrorBanner>
              {error.message || 'Unexpected error while talking to main process'}
            </ErrorBanner>
          )}

          <Card>
            <CardTitle>Get started</CardTitle>
            <QuickAction onClick={handleCreateWorkspace}>
              <FiFolderPlus size={18} />
              New Workspace&nbsp;⌘/Ctrl + N
            </QuickAction>
            <QuickAction onClick={handleOpenWorkspaceDialog}>
              <FiFolderOpen size={18} />
              Open Workspace…&nbsp;⌘/Ctrl + O
            </QuickAction>
          </Card>

          <Card>
            <CardTitle>Recent workspaces</CardTitle>
            {sortedRecent.length === 0 && (
              <div style={{ fontSize: '0.85rem', opacity: 0.6 }}>
                None yet – create your first workspace!
              </div>
            )}
            <List>
              {sortedRecent.slice(0, 7).map(({ path, name, lastOpened }) => (
                <ListItem key={path}>
                  <span
                    style={{
                      overflow: 'hidden',
                      textOverflow: 'ellipsis',
                      whiteSpace: 'nowrap',
                      cursor: 'pointer',
                    }}
                    title={path}
                    onClick={() => handleOpenRecentWorkspace(path)}
                  >
                    {name}
                  </span>
                  <small style={{ opacity: 0.6, fontSize: '0.75rem' }}>
                    {formatDistanceToNow(new Date(lastOpened), {
                      addSuffix: true,
                    })}
                  </small>
                </ListItem>
              ))}
            </List>
          </Card>
        </Column>

        {/* Right column: Plugins, tips, news */}
        <Column>
          <Card style={{ flex: 1 }}>
            <CardTitle>Featured plugins</CardTitle>
            <List>
              {featuredPlugins.map((plugin) => (
                <ListItem key={plugin.id}>
                  <span
                    style={{
                      display: 'flex',
                      flexDirection: 'column',
                      overflow: 'hidden',
                    }}
                  >
                    <strong style={{ fontSize: '0.9rem' }}>{plugin.name}</strong>
                    <span
                      style={{
                        fontSize: '0.75rem',
                        opacity: 0.7,
                        whiteSpace: 'nowrap',
                        overflow: 'hidden',
                        textOverflow: 'ellipsis',
                      }}
                    >
                      {plugin.subtitle}
                    </span>
                  </span>
                  <button
                    aria-label={`Install ${plugin.name}`}
                    onClick={() => handleInstallPlugin(plugin.id)}
                  >
                    {plugin.installed ? (
                      <FiZap size={16} color="#44c" />
                    ) : (
                      <FiDownload size={16} />
                    )}
                  </button>
                </ListItem>
              ))}
            </List>
          </Card>
        </Column>
      </Content>
    </PageContainer>
  );
};

export default WelcomePage;
```
