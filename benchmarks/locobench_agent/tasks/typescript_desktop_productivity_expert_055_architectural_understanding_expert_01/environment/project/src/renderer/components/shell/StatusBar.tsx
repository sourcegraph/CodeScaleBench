```typescript
/**
 * PaletteFlow Studio – StatusBar.tsx
 *
 * A rich status-bar that sits at the bottom of every workspace window.
 * It surfaces real-time information coming from several sub-systems:
 *   – Active workspace name + dirty state
 *   – Node / link statistics
 *   – Auto-update channel & lifecycle
 *   – Plugin health (failed plugins, reload button, etc.)
 *   – Crash reporter heartbeat
 *   – Memory usage (renderer)
 *
 * The component purposefully avoids direct business-logic.  Instead it
 * listens to view-models and Electron IPC channels, in line with Clean
 * Architecture guidelines adopted across the code-base.
 */

import React, {
  useCallback,
  useEffect,
  useMemo,
  useState,
  MouseEvent,
} from 'react';
import styled, { css } from 'styled-components';
import { ipcRenderer } from 'electron';
import {
  FiAlertTriangle,
  FiCloud,
  FiCpu,
  FiRefreshCw,
  FiSave,
} from 'react-icons/fi';
import shallow from 'zustand/shallow';

import { useShellStore } from '../../store/shellStore';
import { bytesToHumanReadable } from '../../utils/formatters';
import { theme } from '../../styles/theme';

/* -------------------------------------------------------------------------- */
/*                              Type Declarations                             */
/* -------------------------------------------------------------------------- */

enum UpdatePhase {
  Idle = 'idle',
  Checking = 'checking',
  Available = 'available',
  Downloading = 'downloading',
  Ready = 'ready',
  Error = 'error',
}

interface UpdateStatus {
  phase: UpdatePhase;
  progress?: number; // 0–100 (%), meaningful in Downloading phase
  error?: string;
}

interface PluginHealth {
  failedPlugins: number;
}

/* -------------------------------------------------------------------------- */
/*                                 Constants                                  */
/* -------------------------------------------------------------------------- */

const MEMORY_POLL_INTERVAL = 10_000; // ms
const ONE_MB = 1024 * 1024;

/* -------------------------------------------------------------------------- */
/*                            Styled View Components                          */
/* -------------------------------------------------------------------------- */

const Bar = styled.footer`
  display: flex;
  align-items: center;
  width: 100%;
  height: 28px;
  padding: 0 8px;
  box-sizing: border-box;
  user-select: none;
  background: ${theme.colors.surfaceRaised};
  color: ${theme.colors.textSecondary};
  font-size: 0.75rem;
  line-height: 1;
  border-top: 1px solid ${theme.colors.outline};
`;

const Section = styled.div<{ $interactive?: boolean }>`
  display: flex;
  align-items: center;
  gap: 4px;
  padding: 0 6px;

  ${({ $interactive }) =>
    $interactive &&
    css`
      cursor: pointer;
      &:hover {
        background: ${theme.colors.surfaceHovered};
        color: ${theme.colors.textPrimary};
      }
    `}
`;

const Sep = styled.div`
  width: 1px;
  height: 14px;
  background: ${theme.colors.outlineVariant};
  margin: 0 4px;
`;

const ProgressBar = styled.div<{ $value: number }>`
  width: 50px;
  height: 4px;
  border-radius: 2px;
  overflow: hidden;
  background: ${theme.colors.surfaceLow};

  &::after {
    content: '';
    display: block;
    width: ${({ $value }) => `${$value}%`};
    height: 100%;
    background: ${theme.colors.accent};
    transition: width 0.3s ease;
  }
`;

/* -------------------------------------------------------------------------- */
/*                        Local State & Custom Hooks                          */
/* -------------------------------------------------------------------------- */

/**
 * Subscribes to update-status events over IPC and returns the latest value.
 */
function useUpdateStatus(): UpdateStatus {
  const [status, setStatus] = useState<UpdateStatus>(() => ({
    phase: UpdatePhase.Idle,
  }));

  useEffect(() => {
    function onStatus(_: unknown, payload: UpdateStatus) {
      setStatus(payload);
    }

    ipcRenderer.on('autoUpdater:status', onStatus);
    ipcRenderer.send('autoUpdater:requestStatus');

    return () => {
      ipcRenderer.removeListener('autoUpdater:status', onStatus);
    };
  }, []);

  return status;
}

/**
 * Periodically pulls renderer memory usage.
 */
function useMemoryInfo(): string {
  const [info, setInfo] = useState<string>('—');

  useEffect(() => {
    const tick = () => {
      const bytes = process.memoryUsage().rss;
      setInfo(bytesToHumanReadable(bytes));
    };

    tick(); // first sample immediately
    const id = setInterval(tick, MEMORY_POLL_INTERVAL);
    return () => clearInterval(id);
  }, []);

  return info;
}

/**
 * Subscribes to plugin health events over IPC.
 */
function usePluginHealth(): PluginHealth {
  const [health, setHealth] = useState<PluginHealth>({ failedPlugins: 0 });

  useEffect(() => {
    const onHealth = (_: unknown, payload: PluginHealth) =>
      setHealth(payload);

    ipcRenderer.on('plugins:health', onHealth);
    ipcRenderer.send('plugins:requestHealth');

    return () => ipcRenderer.removeListener('plugins:health', onHealth);
  }, []);

  return health;
}

/* -------------------------------------------------------------------------- */
/*                               StatusBar UI                                */
/* -------------------------------------------------------------------------- */

export const StatusBar: React.FC = () => {
  /* --------------------------- Global Shell Store -------------------------- */
  const {
    workspaceName,
    unsavedChanges,
    nodeCount,
    linkCount,
    triggerSaveAll,
  } = useShellStore(
    (s) => ({
      workspaceName: s.workspace.name,
      unsavedChanges: s.workspace.unsavedChanges,
      nodeCount: s.workspace.stats.nodes,
      linkCount: s.workspace.stats.links,
      triggerSaveAll: s.actions.triggerSaveAll,
    }),
    shallow,
  );

  /* ------------------------------ Sub-Systems ------------------------------ */
  const update = useUpdateStatus();
  const memoryUsage = useMemoryInfo();
  const pluginHealth = usePluginHealth();

  /* ------------------------------ Callbacks -------------------------------- */
  const onUpdateClick = useCallback(
    (e: MouseEvent) => {
      e.stopPropagation();

      switch (update.phase) {
        case UpdatePhase.Available:
          ipcRenderer.send('autoUpdater:download');
          break;
        case UpdatePhase.Ready:
          ipcRenderer.send('autoUpdater:quitAndInstall');
          break;
        case UpdatePhase.Error:
          ipcRenderer.send('autoUpdater:openLogs');
          break;
        default:
          ipcRenderer.send('autoUpdater:check');
      }
    },
    [update.phase],
  );

  const onPluginWarningClick = useCallback(() => {
    ipcRenderer.send('plugins:openManager');
  }, []);

  const onSaveClick = useCallback(() => {
    triggerSaveAll();
  }, [triggerSaveAll]);

  /* -------------------------------- Labels -------------------------------- */
  const updateLabel = useMemo(() => {
    switch (update.phase) {
      case UpdatePhase.Checking:
        return 'Checking for updates…';
      case UpdatePhase.Available:
        return 'Update available';
      case UpdatePhase.Downloading:
        return `Downloading ${update.progress ?? 0}%`;
      case UpdatePhase.Ready:
        return 'Restart to update';
      case UpdatePhase.Error:
        return 'Update failed';
      default:
        return 'Up to date';
    }
  }, [update.phase, update.progress]);

  /* -------------------------------- Render -------------------------------- */
  return (
    <Bar role="status" aria-label="Application status bar">
      {/* Workspace information */}
      <Section>
        {workspaceName}
        {unsavedChanges ? '*' : ''}
      </Section>

      <Sep />

      {/* Node/link stats */}
      <Section title="Nodes / Links">
        {nodeCount} nodes, {linkCount} links
      </Section>

      <Sep />

      {/* Save-all if dirty */}
      {unsavedChanges > 0 && (
        <>
          <Section
            title="Save all (⌘S)"
            $interactive
            onClick={onSaveClick}
          >
            <FiSave size={14} />
            {unsavedChanges} unsaved
          </Section>
          <Sep />
        </>
      )}

      {/* Auto-update */}
      <Section
        title={updateLabel}
        $interactive={update.phase !== UpdatePhase.Idle}
        onClick={onUpdateClick}
      >
        <FiCloud size={14} />
        {updateLabel}
        {update.phase === UpdatePhase.Downloading && (
          <ProgressBar $value={update.progress ?? 0} />
        )}
      </Section>

      <Sep />

      {/* Plugin warnings */}
      {pluginHealth.failedPlugins > 0 && (
        <>
          <Section
            title="Some plugins failed to load"
            $interactive
            onClick={onPluginWarningClick}
          >
            <FiAlertTriangle size={14} color={theme.colors.warning} />
            {pluginHealth.failedPlugins}
          </Section>
          <Sep />
        </>
      )}

      {/* Memory usage */}
      <Section title="Renderer memory usage">
        <FiCpu size={14} />
        {memoryUsage}
      </Section>

      {/* Right-aligned filler */}
      <div style={{ flex: 1 }} />

      {/* Reload renderer (dev) */}
      {process.env.NODE_ENV === 'development' && (
        <Section
          title="Reload renderer"
          $interactive
          onClick={() => ipcRenderer.send('app:reloadRenderer')}
        >
          <FiRefreshCw size={14} />
        </Section>
      )}
    </Bar>
  );
};

export default StatusBar;

/* -------------------------------------------------------------------------- */
/*                                    EOF                                     */
/* -------------------------------------------------------------------------- */
```