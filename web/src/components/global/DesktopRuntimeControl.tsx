import { getCurrentWindow } from '@tauri-apps/api/window';
import { invoke, isTauri } from '@tauri-apps/api/core';
import { listen } from '@tauri-apps/api/event';
import { disable as disableAutostart, enable as enableAutostart } from '@tauri-apps/plugin-autostart';
import { isPermissionGranted, requestPermission, sendNotification } from '@tauri-apps/plugin-notification';
import { register, unregister } from '@tauri-apps/plugin-global-shortcut';
import { confirm } from '@tauri-apps/plugin-dialog';
import { Activity, Archive, ChevronDown, CircleAlert, Cog, Database, FolderSync, Power, RefreshCw, X } from 'lucide-react';
import { useCallback, useEffect, useRef, useState, type FormEvent } from 'react';
import { createPortal } from 'react-dom';
import { invoke as tauriInvoke } from '@tauri-apps/api/core';
import { toDesktopDroppedFile, type DesktopDroppedFilePayload } from '../../lib/desktopDrop';
import { api, setApiToken } from '../../services/api';
import type { ModelCatalog } from '../../types';
import { friendlyModelName } from '../../lib/modelName';
import { CustomSelect } from '../ui/CustomSelect';

type RuntimePhase = 'stopped' | 'starting' | 'ready' | 'degraded' | 'stopping' | 'error';

interface RuntimeSnapshot {
  phase: RuntimePhase;
  message: string;
  apiUrl: string;
  dockerAvailable: boolean;
  provider: 'unconfigured' | 'mock' | 'openai';
  baseUrl: string;
  model: string;
  closeToTray: boolean;
  autostart: boolean;
  notifications: boolean;
  globalShortcut: string;
  hasProviderKey: boolean;
  providerConnections?: ApiConnection[];
  activeProviderConnectionId?: string | null;
  logs: string[];
}

interface ApiConnection {
  id: string;
  name: string;
  baseUrl: string;
  model: string;
  hasApiKey: boolean;
}

interface DesktopRunEventState {
  eventId: string;
  status: string;
  approvalPending: boolean;
}

interface DesktopAutomationEventState {
  eventId: string;
  status: string;
}

interface DesktopRuntimeControlProps {
  runEvents?: DesktopRunEventState[];
  automationRuns?: DesktopAutomationEventState[];
  settingsRequest?: number;
  providerSettingsRequest?: number;
  onModelsChanged?: (catalog: ModelCatalog) => void;
  onDroppedFiles?: (files: File[]) => void | Promise<void>;
  onDropError?: (message: string) => void;
}

const isDesktop = isTauri();
const AUTO_RELOAD_KEY = 'aura:desktop-awaiting-api-ready';

export function DesktopRuntimeControl({ runEvents = [], automationRuns = [], settingsRequest = 0, providerSettingsRequest = 0, onModelsChanged, onDroppedFiles, onDropError }: DesktopRuntimeControlProps) {
  const [snapshot, setSnapshot] = useState<RuntimeSnapshot | null>(null);
  const [open, setOpen] = useState(false);
  const [settingsSection, setSettingsSection] = useState<'provider' | 'desktop'>('desktop');
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [provider, setProvider] = useState<'unconfigured' | 'mock' | 'openai'>('unconfigured');
  const [connectionId, setConnectionId] = useState('__new__');
  const [providerName, setProviderName] = useState('');
  const [baseUrl, setBaseUrl] = useState('');
  const [model, setModel] = useState('');
  const [modelCatalog, setModelCatalog] = useState<ModelCatalog>({ providers: [] });
  const [selectedProviderModel, setSelectedProviderModel] = useState('');
  const [providerConnectionStatus, setProviderConnectionStatus] = useState<string | null>(null);
  const [providerKey, setProviderKey] = useState('');
  const [closeToTray, setCloseToTray] = useState(true);
  const [autostart, setAutostart] = useState(false);
  const [notifications, setNotifications] = useState(false);
  const [globalShortcut, setGlobalShortcut] = useState('CommandOrControl+Alt+A');
  const previousReady = useRef(false);
  const previousRunEvents = useRef(new Map<string, { status: string; approvalPending: boolean }>());
  const previousAutomationRuns = useRef(new Map<string, string>());
  const settingsHydrated = useRef(false);

  useEffect(() => {
    if (settingsRequest > 0) { setSettingsSection('desktop'); setOpen(true); }
  }, [settingsRequest]);

  useEffect(() => {
    if (providerSettingsRequest > 0) { setSettingsSection('provider'); setOpen(true); }
  }, [providerSettingsRequest]);

  const notify = useCallback((title: string, body: string) => {
    if (!snapshot?.notifications) return;
    void isPermissionGranted().then((granted) => {
      if (granted) sendNotification({ title, body });
    }).catch(() => {});
  }, [snapshot?.notifications]);

  const refresh = useCallback(async () => {
    const next = await invoke<RuntimeSnapshot>('desktop_status');
    setSnapshot(next);
    if (!settingsHydrated.current) {
      setProvider(next.provider);
      const active = next.providerConnections?.find((item) => item.id === next.activeProviderConnectionId);
      setConnectionId(active?.id ?? '__new__');
      setProviderName(active?.name ?? '');
      setBaseUrl(active?.baseUrl || next.baseUrl || 'https://api.openai.com/v1');
      setModel(active?.model ?? next.model);
      if (active?.model) setSelectedProviderModel(`openai:${active.model}`);
      setCloseToTray(next.closeToTray);
      setAutostart(next.autostart);
      setNotifications(next.notifications);
      setGlobalShortcut(next.globalShortcut ?? 'CommandOrControl+Alt+A');
      settingsHydrated.current = true;
    }

    if (next.phase === 'ready') {
      if (!previousReady.current && window.sessionStorage.getItem(AUTO_RELOAD_KEY) === '1') {
        window.sessionStorage.removeItem(AUTO_RELOAD_KEY);
        window.location.reload();
      }
      previousReady.current = true;
    } else {
      previousReady.current = false;
    }
    return next;
  }, []);

  useEffect(() => {
    if (!isDesktop) return;
    let active = true;
    let unlistenOpen: (() => void) | undefined;
    let unlistenDrop: (() => void) | undefined;
    let unlistenDropRejected: (() => void) | undefined;
    const consumeDroppedFiles = async () => {
      try {
        const dropped = await invoke<DesktopDroppedFilePayload[]>('desktop_consume_dropped_files');
        if (!dropped.length || !active) return;
        await onDroppedFiles?.(dropped.map(toDesktopDroppedFile));
      } catch (cause) {
        if (active) onDropError?.(cause instanceof Error ? cause.message : String(cause));
      }
    };
    const poll = async () => {
      try { if (active) await refresh(); }
      catch (cause) { if (active) setError(cause instanceof Error ? cause.message : String(cause)); }
    };
    void poll();
    const timer = window.setInterval(() => void poll(), 2_000);
    void listen('desktop:open-settings', () => { setSettingsSection('desktop'); setOpen(true); }).then((unlisten) => {
      unlistenOpen = unlisten;
      if (!active) unlisten();
    });
    void listen('desktop:files-dropped', () => void consumeDroppedFiles()).then((unlisten) => {
      unlistenDrop = unlisten;
      if (!active) unlisten();
      else void consumeDroppedFiles();
    });
    void listen('desktop:file-drop-rejected', () => {
      onDropError?.('Kuractus is still processing earlier dropped files. Try again in a moment.');
    }).then((unlisten) => {
      unlistenDropRejected = unlisten;
      if (!active) unlisten();
    });
    return () => {
      active = false;
      window.clearInterval(timer);
      unlistenOpen?.();
      unlistenDrop?.();
      unlistenDropRejected?.();
    };
  }, [onDropError, onDroppedFiles, refresh]);

  useEffect(() => {
    if (!isDesktop || !globalShortcut || globalShortcut === 'none') return;
    void register(globalShortcut, (event) => {
      if (event.state !== 'Pressed') return;
      void getCurrentWindow().show();
      void getCurrentWindow().unminimize();
      void getCurrentWindow().setFocus();
    }).catch(() => {});
    return () => {
      void unregister(globalShortcut).catch(() => {});
    };
  }, [globalShortcut]);

  useEffect(() => {
    if (!isDesktop) return;
    const currentRunEvents = new Map(runEvents.map((event) => [event.eventId, { status: event.status, approvalPending: event.approvalPending }]));
    for (const event of runEvents) {
      const previous = previousRunEvents.current.get(event.eventId);
      if (!previous) continue;
      if (event.status === 'waiting_for_approval' && previous.status !== 'waiting_for_approval') {
        notify('Kuractus approval requested', 'Open Kuractus to review the pending approval.');
      } else if (event.approvalPending && !previous.approvalPending && event.status !== 'waiting_for_approval') {
        notify('Kuractus approval requested', 'Open Kuractus to review the pending approval.');
      } else if (event.status === 'completed' && ['running', 'cancellation_requested', 'resuming_routing'].includes(previous.status)) {
        notify('Kuractus run completed', 'A local Kuractus run finished.');
      } else if (event.status === 'failed' && ['running', 'cancellation_requested', 'resuming_routing'].includes(previous.status)) {
        notify('Kuractus run failed', 'Open Kuractus to review the runtime status.');
      }
    }
    previousRunEvents.current = currentRunEvents;

    const currentAutomationRuns = new Map(automationRuns.map((event) => [event.eventId, event.status]));
    for (const event of automationRuns) {
      const previousStatus = previousAutomationRuns.current.get(event.eventId);
      if ((previousStatus === 'queued' || previousStatus === 'running') && event.status !== previousStatus) {
        if (event.status === 'completed') notify('Kuractus automation completed', 'An automation run finished.');
        if (event.status === 'failed') notify('Kuractus automation failed', 'Open Kuractus to review the automation status.');
      }
    }
    previousAutomationRuns.current = currentAutomationRuns;
  }, [automationRuns, notify, runEvents]);

  if (!isDesktop) return null;

  const start = async (restart = false) => {
    setBusy(true);
    setError(null);
    window.sessionStorage.setItem(AUTO_RELOAD_KEY, '1');
    try {
      const token = await tauriInvoke<string>('desktop_api_token');
      setApiToken(token);
      setSnapshot(await tauriInvoke<RuntimeSnapshot>(restart ? 'desktop_restart' : 'desktop_start'));
    } catch (cause) {
      window.sessionStorage.removeItem(AUTO_RELOAD_KEY);
      setError(cause instanceof Error ? cause.message : String(cause));
      try { await refresh(); } catch { /* Keep the actionable startup error. */ }
    } finally { setBusy(false); }
  };

  const stop = async () => {
    setBusy(true);
    setError(null);
    try { setSnapshot(await invoke<RuntimeSnapshot>('desktop_stop')); }
    catch (cause) { setError(cause instanceof Error ? cause.message : String(cause)); }
    finally { setBusy(false); }
  };

  const createBackup = async () => {
    setBusy(true);
    setError(null);
    window.sessionStorage.setItem(AUTO_RELOAD_KEY, '1');
    try {
      setSnapshot(await invoke<RuntimeSnapshot>('desktop_create_backup'));
    } catch (cause) {
      window.sessionStorage.removeItem(AUTO_RELOAD_KEY);
      setError(cause instanceof Error ? cause.message : String(cause));
      try { await refresh(); } catch { /* Keep the backup error visible. */ }
    } finally { setBusy(false); }
  };

  const restoreBackup = async () => {
    const accepted = await confirm(
      'Restoring replaces the Kuractus database, workspace files and checkpoints with the selected backup. Kuractus creates a safety backup first. Continue?',
      { title: 'Restore Kuractus Desktop backup', kind: 'warning' },
    );
    if (!accepted) return;
    setBusy(true);
    setError(null);
    window.sessionStorage.setItem(AUTO_RELOAD_KEY, '1');
    try {
      setSnapshot(await invoke<RuntimeSnapshot>('desktop_restore_backup'));
      setApiToken(await invoke<string>('desktop_api_token'));
    } catch (cause) {
      window.sessionStorage.removeItem(AUTO_RELOAD_KEY);
      setError(cause instanceof Error ? cause.message : String(cause));
      try { await refresh(); } catch { /* Keep the restore error visible. */ }
    } finally { setBusy(false); }
  };

  const saveSettings = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    setBusy(true);
    setError(null);
    try {
      if (autostart) await enableAutostart(); else await disableAutostart();
      if (notifications) {
        const granted = await isPermissionGranted();
        if (!granted && await requestPermission() !== 'granted') throw new Error('Allow Kuractus notifications in Windows Settings to enable this option.');
      }
      const next = await invoke<RuntimeSnapshot>('desktop_save_windows_preferences', {
        closeToTray,
        autostart,
        notifications,
        globalShortcut,
      });
      setSnapshot(next);
      if (notifications) {
        const granted = await isPermissionGranted();
        if (granted) sendNotification({ title: 'Kuractus', body: 'Kuractus Desktop notifications are enabled.' });
      }
    } catch (cause) {
      try { if (snapshot?.autostart) await enableAutostart(); else await disableAutostart(); } catch { /* Keep the settings error visible. */ }
      setError(cause instanceof Error ? cause.message : String(cause));
      try { await refresh(); } catch { /* Keep the settings error visible. */ }
    } finally { setBusy(false); }
  };

  const selectConnection = (id: string) => {
    setConnectionId(id);
    setProviderKey('');
    const connection = snapshot?.providerConnections?.find((item) => item.id === id);
    if (!connection) {
      setProviderName('OpenAI');
      setBaseUrl('https://api.openai.com/v1');
      setModel('gpt-4o-mini');
      setSelectedProviderModel('');
      return;
    }
    setProviderName(connection.name);
    setBaseUrl(connection.baseUrl);
    setModel(connection.model);
    setSelectedProviderModel(`openai:${connection.model}`);
  };

  const saveProviderConnection = async (activate: boolean, bootstrapModel = false): Promise<boolean> => {
    const selectedModelId = selectedProviderModel.startsWith('openai:') ? selectedProviderModel.slice('openai:'.length) : '';
    const targetName = providerName.trim() || 'OpenAI';
    const targetBaseUrl = baseUrl.trim() || 'https://api.openai.com/v1';
    const targetModel = selectedModelId || model.trim() || (bootstrapModel ? 'gpt-4o-mini' : '');
    if (!targetModel) {
      setError('Connect first, then choose one of the models returned by your provider.');
      return false;
    }
    const id = connectionId === '__new__'
      ? globalThis.crypto?.randomUUID?.().replace(/-/g, '') ?? `api-${Date.now()}`
      : connectionId;
    setBusy(true);
    setError(null);
    try {
      const next = await invoke<RuntimeSnapshot>('desktop_save_provider_connection', {
        connectionId: id,
        name: targetName,
        baseUrl: targetBaseUrl,
        model: targetModel,
        providerApiKey: providerKey || null,
        activate,
      });
      setSnapshot(next);
      setConnectionId(id);
      setProviderName(targetName);
      setBaseUrl(targetBaseUrl);
      setModel(targetModel);
      if (activate) {
        setProvider('openai');
        setApiToken(await invoke<string>('desktop_api_token'));
      }
      setProviderKey('');
      return true;
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : String(cause));
      try { await refresh(); } catch { /* Keep the connection error visible. */ }
      return false;
    } finally { setBusy(false); }
  };

  const discoverModels = async () => {
    setBusy(true);
    setError(null);
    setProviderConnectionStatus('Checking connected providers…');
    try {
      const nextCatalog = await api.refreshModels();
      setModelCatalog(nextCatalog);
      onModelsChanged?.(nextCatalog);
      const available = nextCatalog.providers.reduce((count, item) => count + (item.available ? item.models.length : 0), 0);
      setProviderConnectionStatus(available ? `${available} available models found.` : 'No models are available yet. Connect a provider or start a local model service.');
      return nextCatalog;
    } catch (cause) {
      const message = cause instanceof Error ? cause.message : String(cause);
      setProviderConnectionStatus(null);
      setError(`Could not discover models. ${message}`);
      return null;
    } finally { setBusy(false); }
  };

  const connectAndDiscover = async () => {
    setProviderConnectionStatus('Connecting and checking model access…');
    setError(null);
    if (provider === 'unconfigured') {
      await discoverModels();
      return;
    }
    if (provider === 'mock') {
      setBusy(true);
      try {
        const next = await invoke<RuntimeSnapshot>('desktop_set_provider_mode', { provider: 'mock' });
        setSnapshot(next);
        setApiToken(await invoke<string>('desktop_api_token'));
        const nextCatalog = await api.refreshModels();
        setModelCatalog(nextCatalog);
        onModelsChanged?.(nextCatalog);
        setSelectedProviderModel('mock:mock-default');
        setProviderConnectionStatus('Demo mode is connected. Replies are simulated; this is not a live AI model.');
      } catch (cause) {
        setProviderConnectionStatus(null);
        setError(cause instanceof Error ? cause.message : String(cause));
      } finally { setBusy(false); }
      return;
    }

    const saved = await saveProviderConnection(true, true);
    if (!saved) { setProviderConnectionStatus(null); return; }
    setBusy(true);
    try {
      const nextCatalog = await api.refreshModels();
      setModelCatalog(nextCatalog);
      onModelsChanged?.(nextCatalog);
      const connected = nextCatalog.providers.find((item) => item.id === 'openai' && item.available);
      if (!connected?.models.length) {
        setProviderConnectionStatus(null);
        setError('Could not connect to this provider. Check the API key and endpoint; your workspace data is unchanged.');
        return;
      }
      const nextChoice = `openai:${connected.models[0].id}`;
      setSelectedProviderModel(nextChoice);
      setModel(connected.models[0].id);
      setProviderConnectionStatus(`${connected.models.length} models discovered. Choose one to use in conversations.`);
    } catch (cause) {
      setProviderConnectionStatus(null);
      setError(cause instanceof Error ? cause.message : String(cause));
    } finally { setBusy(false); }
  };

  const forgetSelectedApiKey = async () => {
    if (connectionId === '__new__') return;
    setBusy(true);
    setError(null);
    try {
      setSnapshot(await invoke<RuntimeSnapshot>('desktop_forget_provider_key', { connectionId }));
      setProviderKey('');
      setError('The saved key for this API was removed from Windows Credential Manager.');
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : String(cause));
    } finally { setBusy(false); }
  };

  const phase = snapshot?.phase ?? 'starting';
  const phaseLabel = phase === 'ready' ? 'Ready' : phase === 'starting' ? 'Starting' : phase === 'stopping' ? 'Stopping' : phase === 'degraded' ? 'Degraded' : phase === 'error' ? 'Needs attention' : 'Stopped';
  const StatusIcon = phase === 'error' || phase === 'degraded' ? CircleAlert : phase === 'ready' ? Activity : Database;

  return (
    <>
      <button className={`desktop-runtime-pill desktop-runtime-pill--${phase}`} type="button" onClick={() => setOpen(true)} aria-label={`Kuractus Desktop runtime: ${phaseLabel}. Open runtime settings`}>
        <span className="desktop-runtime-pill__led" />
        <StatusIcon size={14} />
        <span>Kuractus · {phaseLabel}</span>
        <ChevronDown size={13} />
      </button>
      {open && typeof document !== 'undefined' ? createPortal(
        <div className="desktop-overlay" role="presentation" onMouseDown={(event) => { if (event.target === event.currentTarget) setOpen(false); }}>
          <section className="desktop-panel" role="dialog" aria-modal="true" aria-labelledby="desktop-runtime-title">
            <header className="desktop-panel__header">
              <div><span className="eyebrow">KURACTUS SETTINGS</span><h2 id="desktop-runtime-title">{settingsSection === 'provider' ? 'AI Provider' : 'Desktop Settings'}</h2><p>{settingsSection === 'provider' ? 'Connect a model provider for your conversations.' : 'Runtime and Windows app behavior.'}</p></div>
              <button className="icon-button" type="button" aria-label="Close desktop settings" onClick={() => setOpen(false)}><X size={17} /></button>
            </header>
            <nav className="desktop-settings-tabs" role="tablist" aria-label="Kuractus settings">
              <button type="button" role="tab" aria-selected={settingsSection === 'provider'} className={settingsSection === 'provider' ? 'is-active' : ''} onClick={() => setSettingsSection('provider')}>AI Provider</button>
              <button type="button" role="tab" aria-selected={settingsSection === 'desktop'} className={settingsSection === 'desktop' ? 'is-active' : ''} onClick={() => setSettingsSection('desktop')}>Desktop</button>
            </nav>
            {error ? <div className="desktop-panel-error" role="alert"><CircleAlert size={15} /><span>{error}</span></div> : null}
            {settingsSection === 'desktop' ? <>
            <div className={`desktop-runtime-summary desktop-runtime-summary--${phase}`}>
              <div><span className="desktop-runtime-summary__icon"><StatusIcon size={18} /></span><span><strong>{phaseLabel}</strong><small>{snapshot?.message ?? 'Checking the local runtime…'}</small></span></div>
            </div>
            <div className="desktop-runtime-actions">
              <button className="primary-soft-button" type="button" disabled={busy || phase === 'starting' || phase === 'stopping'} onClick={() => void start(phase === 'ready')}>{busy || phase === 'starting' ? <RefreshCw size={15} className="desktop-spin" /> : <Activity size={15} />}{phase === 'ready' ? 'Restart runtime' : 'Start runtime'}</button>
              <button className="secondary-button" type="button" disabled={busy || !['ready', 'degraded', 'error'].includes(phase)} onClick={() => void stop()}><Power size={14} /> Stop and preserve data</button>
            </div>
            <div className="desktop-backup-actions">
              <button className="secondary-button" type="button" disabled={busy || phase !== 'ready'} onClick={() => void createBackup()}><Archive size={14} /> Create local backup</button>
              <button className="secondary-button" type="button" disabled={busy || !snapshot?.dockerAvailable} onClick={() => void restoreBackup()}><FolderSync size={14} /> Restore backup</button>
              <small>Includes PostgreSQL, workspace files and checkpoints. Windows Credential Manager secrets are excluded.</small>
            </div>
            {phase === 'error' && !snapshot?.dockerAvailable ? <p className="desktop-prerequisite">Kuractus Desktop needs Docker Desktop with the Linux engine running. Open Docker Desktop, wait for “Engine running”, then choose Start runtime. Kuractus will not install Docker.</p> : null}
            <details className="desktop-log-disclosure"><summary>Runtime log</summary><pre>{snapshot?.logs.length ? snapshot.logs.join('\n') : 'No runtime log entries yet.'}</pre></details>
            </> : null}
            <form className="desktop-settings-form" onSubmit={(event) => { if (settingsSection === 'provider') event.preventDefault(); else void saveSettings(event); }}>
              {settingsSection === 'provider' ? <div className="desktop-settings-section desktop-provider-setup"><div><strong>Connect an AI provider</strong><small>Choose a provider, test the key, then select from the models it reports. You can keep using the workspace while a provider is not connected.</small></div>
                <label className="desktop-field"><span>Provider</span><select value={provider} onChange={(event) => { setProvider(event.target.value as 'unconfigured' | 'mock' | 'openai'); setProviderConnectionStatus(null); }}><option value="unconfigured">Discover local models</option><option value="openai">OpenAI</option><option value="mock">Demo mode · simulated replies</option></select></label>
                {provider === 'openai' ? <>
                  <label className="desktop-field"><span>API key {snapshot?.providerConnections?.find((item) => item.id === connectionId)?.hasApiKey ? '· saved key available' : ''}</span><input type="password" value={providerKey} onChange={(event) => setProviderKey(event.target.value)} placeholder={snapshot?.providerConnections?.find((item) => item.id === connectionId)?.hasApiKey ? 'Leave blank to keep the saved key' : 'Paste your OpenAI API key'} autoComplete="new-password" /></label>
                  <button className="primary-soft-button" type="button" disabled={busy} onClick={() => void connectAndDiscover()}>{busy ? 'Connecting…' : 'Connect and discover models'}</button>
                  {modelCatalog.providers.find((item) => item.id === 'openai' && item.available)?.models.length ? <>
                    <CustomSelect
                      ariaLabel="Provider model"
                      label="Available models"
                      value={selectedProviderModel || `openai:${modelCatalog.providers.find((item) => item.id === 'openai')?.models[0]?.id ?? ''}`}
                      options={modelCatalog.providers.find((item) => item.id === 'openai')!.models.map((item) => ({ value: `openai:${item.id}`, label: friendlyModelName(item.label || item.id) }))}
                      onChange={(value) => { setSelectedProviderModel(value); setModel(value.slice('openai:'.length)); }}
                    />
                    <button className="secondary-button" type="button" disabled={busy || !selectedProviderModel} onClick={() => void saveProviderConnection(true)}>Use selected model</button>
                  </> : null}
                </> : <button className="primary-soft-button" type="button" disabled={busy} onClick={() => void connectAndDiscover()}>{busy ? 'Checking…' : provider === 'mock' ? 'Use demo mode' : 'Discover local models'}</button>}
                {providerConnectionStatus ? <p className="desktop-provider-status" role="status">{providerConnectionStatus}</p> : null}
                {provider === 'unconfigured' ? <p className="desktop-prerequisite">Ollama and LM Studio models appear here when their local services are running. No cloud provider is needed to keep using the workspace.</p> : null}
                {provider === 'mock' ? <p className="desktop-prerequisite">Demo mode returns simulated responses; it is not a real model provider.</p> : null}
                <details className="desktop-advanced-provider"><summary>Advanced connection options</summary>
                  <div className="desktop-api-connections">
                    <label className="desktop-field"><span>Saved API connections</span><select value={connectionId} onChange={(event) => selectConnection(event.target.value)}><option value="__new__">Add another connection…</option>{(snapshot?.providerConnections ?? []).map((connection) => <option key={connection.id} value={connection.id}>{connection.name}{connection.id === snapshot?.activeProviderConnectionId ? ' · active' : ''}{connection.hasApiKey ? ' · key saved' : ''}</option>)}</select></label>
                    <label className="desktop-field"><span>Connection name</span><input value={providerName} onChange={(event) => setProviderName(event.target.value)} placeholder="OpenAI" autoComplete="off" /></label>
                    <label className="desktop-field"><span>Custom API endpoint</span><input value={baseUrl} onChange={(event) => setBaseUrl(event.target.value)} placeholder="https://api.openai.com/v1" autoComplete="url" /></label>
                    {snapshot?.providerConnections?.find((item) => item.id === connectionId)?.hasApiKey ? <button className="desktop-text-button" type="button" disabled={busy} onClick={() => void forgetSelectedApiKey()}>Remove saved API key</button> : null}
                    <div className="desktop-api-connections__actions"><button className="secondary-button" type="button" disabled={busy} onClick={() => void saveProviderConnection(false)}>Save connection</button></div>
                  </div>
                </details>
              </div>
              : <>
              {notifications ? <button className="desktop-text-button" type="button" onClick={() => notify('Kuractus Desktop test', 'Desktop notifications are working.')}>Send test notification</button> : null}
              <div className="desktop-settings-section desktop-settings-section--toggles">
                <label><span><strong>Close to tray</strong><small>Closing the window keeps the runtime running.</small></span><input type="checkbox" checked={closeToTray} onChange={(event) => setCloseToTray(event.target.checked)} /></label>
                <label><span><strong>Start with Windows</strong><small>Disabled by default.</small></span><input type="checkbox" checked={autostart} onChange={(event) => setAutostart(event.target.checked)} /></label>
                <label><span><strong>Desktop notifications</strong><small>Uses generic text; no chat content is included.</small></span><input type="checkbox" checked={notifications} onChange={(event) => setNotifications(event.target.checked)} /></label>
                <label><span><strong>Global shortcut</strong><small>Show the Kuractus window.</small></span><select value={globalShortcut} onChange={(event) => setGlobalShortcut(event.target.value)}><option value="CommandOrControl+Alt+A">Ctrl + Alt + A</option><option value="CommandOrControl+Shift+A">Ctrl + Shift + A</option><option value="none">Disabled</option></select></label>
              </div>
              <footer className="desktop-panel__footer"><span><Cog size={14} /> PostgreSQL data stays in its existing Docker volume.</span><button className="primary-button" type="submit" disabled={busy}>{busy ? 'Saving…' : 'Save desktop settings'}</button></footer>
              </>}
            </form>
          </section>
        </div>,
        document.body,
      ) : null}
    </>
  );
}
