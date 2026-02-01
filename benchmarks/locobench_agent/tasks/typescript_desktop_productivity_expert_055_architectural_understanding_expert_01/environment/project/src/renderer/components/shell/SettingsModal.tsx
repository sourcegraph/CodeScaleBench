```typescript
/**
 * PaletteFlow Studio
 * File: src/renderer/components/shell/SettingsModal.tsx
 *
 * A full–featured settings dialog rendered inside the Electron renderer
 * process.  The component synchronises local UI state with the persisted
 * application settings that live in the main process via IPC.
 *
 * Key responsibilities:
 *  • Display & edit global application settings (theme, telemetry, updates)
 *  • Provide basic plugin management (enable / disable)
 *  • Offer manual “Check for updates” action
 *
 * The UI is intentionally opinionated, relying on @mui for rapid
 * implementation while the business-logic remains clean and testable.
 */

import React, { FC, useCallback, useEffect, useMemo, useState } from 'react';
import {
  Backdrop,
  Box,
  Button,
  CircularProgress,
  Dialog,
  DialogActions,
  DialogContent,
  DialogTitle,
  Divider,
  FormControl,
  FormControlLabel,
  IconButton,
  List,
  ListItem,
  ListItemSecondaryAction,
  ListItemText,
  MenuItem,
  Select,
  Switch,
  Tab,
  Tabs,
  Tooltip,
  Typography,
} from '@mui/material';
import { Close as CloseIcon, Refresh as RefreshIcon } from '@mui/icons-material';
import { ipcRenderer } from 'electron';
import { z } from 'zod';

/* ---------- Types & Validation ------------------------------------------------ */

export type ThemeOption = 'light' | 'dark' | 'system';

export interface AppSettings {
  theme: ThemeOption;
  autoUpdate: boolean;
  crashReporting: boolean;
}

export interface PluginInfo {
  id: string;
  name: string;
  version: string;
  enabled: boolean;
}

const SettingsSchema: z.ZodSchema<AppSettings> = z.object({
  theme: z.enum(['light', 'dark', 'system']),
  autoUpdate: z.boolean(),
  crashReporting: z.boolean(),
});

/* ---------- IPC Channels ------------------------------------------------------ */

const IPC_CHANNELS = {
  GET_SETTINGS: 'settings:get',
  SAVE_SETTINGS: 'settings:save',
  LIST_PLUGINS: 'plugins:list',
  TOGGLE_PLUGIN: 'plugins:toggle',
  CHECK_UPDATES: 'updates:check',
} as const;

/* ---------- Component --------------------------------------------------------- */

interface SettingsModalProps {
  /** Controls open state from parent */
  open: boolean;
  /** Fired when the modal should be closed */
  onClose: () => void;
}

const SettingsModal: FC<SettingsModalProps> = ({ open, onClose }) => {
  /* ---------- Local State ---------------------------------------------------- */

  const [settings, setSettings] = useState<AppSettings | null>(null);
  const [plugins, setPlugins] = useState<PluginInfo[]>([]);
  const [tabIdx, setTabIdx] = useState<number>(0);
  const [saving, setSaving] = useState<boolean>(false);
  const [updateChecking, setUpdateChecking] = useState<boolean>(false);

  /* ---------- Derived -------------------------------------------------------- */

  const isLoaded = useMemo(() => settings !== null, [settings]);

  /* ---------- Lifecycle ------------------------------------------------------ */

  useEffect(() => {
    if (!open) return;

    // Fetch settings & plugins in parallel
    Promise.all([
      ipcRenderer.invoke(IPC_CHANNELS.GET_SETTINGS),
      ipcRenderer.invoke(IPC_CHANNELS.LIST_PLUGINS),
    ])
      .then(([rawSettings, rawPlugins]) => {
        try {
          const parsed = SettingsSchema.parse(rawSettings);
          setSettings(parsed);
        } catch (err) {
          console.error('Invalid settings payload', err);
        }
        setPlugins(rawPlugins as PluginInfo[]);
      })
      .catch((err) => console.error('Failed to load settings', err));
  }, [open]);

  /* ---------- Handlers ------------------------------------------------------- */

  const handleTabChange = useCallback((_e: React.SyntheticEvent, newValue: number) => {
    setTabIdx(newValue);
  }, []);

  const handleSettingChange = useCallback(
    <K extends keyof AppSettings>(key: K, value: AppSettings[K]) => {
      setSettings((prev) => (prev ? { ...prev, [key]: value } : prev));
    },
    [],
  );

  const handlePluginToggle = useCallback(
    (pluginId: string) => {
      setPlugins((prev) =>
        prev.map((p) => (p.id === pluginId ? { ...p, enabled: !p.enabled } : p)),
      );
    },
    [],
  );

  const handleSave = useCallback(async () => {
    if (!settings) return;

    setSaving(true);
    try {
      await ipcRenderer.invoke(IPC_CHANNELS.SAVE_SETTINGS, settings);
      // Flush individual plugin toggles
      await Promise.all(
        plugins.map((p) =>
          ipcRenderer.invoke(IPC_CHANNELS.TOGGLE_PLUGIN, { id: p.id, enabled: p.enabled }),
        ),
      );
      onClose();
    } catch (err) {
      console.error('Failed to persist settings', err);
    } finally {
      setSaving(false);
    }
  }, [settings, plugins, onClose]);

  const handleCheckUpdates = useCallback(async () => {
    setUpdateChecking(true);
    try {
      await ipcRenderer.invoke(IPC_CHANNELS.CHECK_UPDATES);
    } catch (err) {
      console.error('Update check failed', err);
    } finally {
      setUpdateChecking(false);
    }
  }, []);

  /* ---------- Render Helpers ------------------------------------------------- */

  const renderGeneralTab = () =>
    settings && (
      <Box display="flex" flexDirection="column" gap={2}>
        <FormControl fullWidth>
          <Typography variant="subtitle1">Interface Theme</Typography>
          <Select
            value={settings.theme}
            onChange={(e) => handleSettingChange('theme', e.target.value as ThemeOption)}
            size="small"
          >
            <MenuItem value="system">System</MenuItem>
            <MenuItem value="light">Light</MenuItem>
            <MenuItem value="dark">Dark</MenuItem>
          </Select>
        </FormControl>

        <FormControlLabel
          control={
            <Switch
              checked={settings.autoUpdate}
              onChange={(_, checked) => handleSettingChange('autoUpdate', checked)}
            />
          }
          label="Automatically download updates"
        />

        <FormControlLabel
          control={
            <Switch
              checked={settings.crashReporting}
              onChange={(_, checked) => handleSettingChange('crashReporting', checked)}
            />
          }
          label="Enable anonymous crash reporting"
        />

        <Divider sx={{ my: 1 }} />

        <Box display="flex" alignItems="center" gap={1}>
          <Button
            variant="outlined"
            startIcon={<RefreshIcon />}
            onClick={handleCheckUpdates}
            disabled={updateChecking}
          >
            Check for Updates
          </Button>
          {updateChecking && <CircularProgress size={18} />}
        </Box>
      </Box>
    );

  const renderPluginsTab = () => (
    <List dense>
      {plugins.map((plugin) => (
        <ListItem key={plugin.id} divider>
          <ListItemText
            primary={plugin.name}
            secondary={`v${plugin.version} — ${plugin.id}`}
            secondaryTypographyProps={{ variant: 'caption' }}
          />
          <ListItemSecondaryAction>
            <Switch
              edge="end"
              checked={plugin.enabled}
              onChange={() => handlePluginToggle(plugin.id)}
            />
          </ListItemSecondaryAction>
        </ListItem>
      ))}
      {plugins.length === 0 && (
        <Typography variant="body2" color="textSecondary" align="center" sx={{ width: '100%' }}>
          No plugins installed.
        </Typography>
      )}
    </List>
  );

  /* ---------- Render --------------------------------------------------------- */

  return (
    <Dialog open={open} onClose={onClose} fullWidth maxWidth="sm">
      <DialogTitle sx={{ m: 0, p: 2 }}>
        Settings
        <IconButton
          aria-label="close"
          onClick={onClose}
          sx={{
            position: 'absolute',
            right: 8,
            top: 8,
          }}
        >
          <CloseIcon />
        </IconButton>
      </DialogTitle>

      <DialogContent dividers>
        {/* Tabs Header */}
        <Tabs
          value={tabIdx}
          onChange={handleTabChange}
          variant="scrollable"
          scrollButtons="auto"
          sx={{ mb: 2 }}
        >
          <Tab label="General" />
          <Tab label="Plugins" />
        </Tabs>

        {/* Tabs Body */}
        {!isLoaded && (
          <Backdrop open>
            <CircularProgress color="inherit" />
          </Backdrop>
        )}

        {isLoaded && (
          <>
            {tabIdx === 0 && renderGeneralTab()}
            {tabIdx === 1 && renderPluginsTab()}
          </>
        )}
      </DialogContent>

      <DialogActions sx={{ p: 2 }}>
        <Button onClick={onClose} color="inherit" disabled={saving}>
          Cancel
        </Button>
        <Tooltip title="Save & apply settings">
          <span>
            <Button
              variant="contained"
              onClick={handleSave}
              disabled={saving || !isLoaded}
              color="primary"
            >
              {saving ? 'Saving…' : 'Save'}
            </Button>
          </span>
        </Tooltip>
      </DialogActions>
    </Dialog>
  );
};

export default SettingsModal;
```
