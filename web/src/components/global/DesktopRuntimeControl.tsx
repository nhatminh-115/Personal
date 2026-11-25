import { getCurrentWindow } from '@tauri-apps/api/window';
import { invoke, isTauri } from '@tauri-apps/api/core';
import { listen } from '@tauri-apps/api/event';
import { disable as disableAutostart, enable as enableAutostart } from '@tauri-apps/plugin-autostart';
import { isPermissionGranted, requestPermission, sendNotification } from '@tauri-apps/plugin-notification';
import { register, unregister } from '@tauri-apps/plugin-global-shortcut';
import { confirm } from '@tauri-apps/plugin-dialog';
import { Activity, Archive, ChevronDown, CircleAlert, Cog, Database, FolderSync, Power, RefreshCw, X } from 'lucide-react';
import { useCallback, useEffect, useRef, useState, type FormEvent } from 'react';
import { invoke as tauriInvoke } from '@tauri-apps/api/core';
import { toDesktopDroppedFile, type DesktopDroppedFilePayload } from '../../lib/desktopDrop';
import { setApiToken } from '../../services/api';

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
  logs: string[];
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
  onDroppedFiles?: (files: File[]) => void | Promise<void>;
  onDropError?: (message: string) => void;
}

const isDesktop = isTauri();
const AUTO_RELOAD_KEY = 'aura:desktop-awaiting-api-ready';

export function DesktopRuntimeControl({ runEvents = [], automationRuns = [], settingsRequest = 0, onDroppedFiles, onDropError }: DesktopRuntimeControlProps) {
  const [snapshot, setSnapshot] = useState<RuntimeSnapshot | null>(null);
  const [open, setOpen] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [provider, setProvider] = useState<'unconfigured' | 'mock' | 'openai'>('unconfigured');
  const [baseUrl, setBaseUrl] = useState('');
  const [model, setModel] = useState('');
  const [providerKey, setProviderKey] = useState('');
  const [closeToTray, setCloseToTray] = useState(true);
  const [autostart, setAutostart] = useState(false);
  const [notifications, setNotifications] = useState(false);
  const [globalShortcut, setGlobalShortcut] = useState('CommandOrControl+Alt+A');
  const previousReady = useRef(false);
  const previousRunEvents = useRef(new Map<string, { status: string; approvalPending: boolean }>());
  const previousAutomationRuns = useRef(new Map<string, string>());

  useEffect(() => {
    if (settingsRequest > 0) setOpen(true);
  }, [settingsRequest]);

  const notify = useCallback((title: string, body: string) => {
    if (!snapshot?.notifications) return;
    void isPermissionGranted().then((granted) => {
      if (granted) sendNotification({ title, body });
    }).catch(() => {});
  }, [snapshot?.notifications]);

  const refresh = useCallback(async () => {
    const next = await invoke<RuntimeSnapshot>('desktop_status');
    setSnapshot(next);
    setProvider(next.provider);
    setBaseUrl(next.baseUrl ?? 'https://api.openai.com/v1');
    setModel(next.model);
    setCloseToTray(next.closeToTray);
    setAutostart(next.autostart);
    setNotifications(next.notifications);
    setGlobalShortcut(next.globalShortcut ?? 'CommandOrControl+Alt+A');

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
    void listen('desktop:open-settings', () => setOpen(true)).then((unlisten) => {
      unlistenOpen = unlisten;
      if (!active) unlisten();
    });
    void listen('desktop:files-dropped', () => void consumeDroppedFiles()).then((unlisten) => {
      unlistenDrop = unlisten;
      if (!active) unlisten();
      else void consumeDroppedFiles();
    });
    void listen('desktop:file-drop-rejected', () => {
      onDropError?.('AURA is still processing earlier dropped files. Try again in a moment.');
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
        notify('AURA approval requested', 'Open AURA to review the pending approval.');
      } else if (event.approvalPending && !previous.approvalPending && event.status !== 'waiting_for_approval') {
        notify('AURA approval requested', 'Open AURA to review the pending approval.');
      } else if (event.status === 'completed' && ['running', 'cancellation_requested', 'resuming_routing'].includes(previous.status)) {
        notify('AURA run completed', 'A local AURA run finished.');
      } else if (event.status === 'failed' && ['running', 'cancellation_requested', 'resuming_routing'].includes(previous.status)) {
        notify('AURA run failed', 'Open AURA to review the runtime status.');
      }
    }
    previousRunEvents.current = currentRunEvents;

    const currentAutomationRuns = new Map(automationRuns.map((event) => [event.eventId, event.status]));
    for (const event of automationRuns) {
      const previousStatus = previousAutomationRuns.current.get(event.eventId);
      if ((previousStatus === 'queued' || previousStatus === 'running') && event.status !== previousStatus) {
        if (event.status === 'completed') notify('AURA automation completed', 'An automation run finished.');
        if (event.status === 'failed') notify('AURA automation failed', 'Open AURA to review the automation status.');
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
      'Restoring replaces the AURA database, workspace files and checkpoints with the selected backup. AURA creates a safety backup first. Continue?',
      { title: 'Restore AURA Desktop backup', kind: 'warning' },
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
    if (provider === 'openai' && (!baseUrl.trim() || !model.trim())) {
      setError('Enter the endpoint URL and exact model ID reported by that endpoint.');
      return;
    }
    setBusy(true);
    setError(null);
    try {
      if (autostart) await enableAutostart(); else await disableAutostart();
      if (notifications) {
        const granted = await isPermissionGranted();
        if (!granted && await requestPermission() !== 'granted') throw new Error('Allow AURA notifications in Windows Settings to enable this option.');
      }
      window.sessionStorage.setItem(AUTO_RELOAD_KEY, '1');
      const next = await invoke<RuntimeSnapshot>('desktop_save_preferences', {
        provider,
        baseUrl,
        model,
        closeToTray,
        autostart,
        notifications,
        globalShortcut,
        providerApiKey: providerKey || null,
      });
      setApiToken(await invoke<string>('desktop_api_token'));
      setProviderKey('');
      setSnapshot(next);
      if (notifications) {
        const granted = await isPermissionGranted();
        if (granted) sendNotification({ title: 'AURA', body: 'AURA Desktop notifications are enabled.' });
      }
    } catch (cause) {
      window.sessionStorage.removeItem(AUTO_RELOAD_KEY);
      setError(cause instanceof Error ? cause.message : String(cause));
      try { await refresh(); } catch { /* Keep the settings error visible. */ }
    } finally { setBusy(false); }
  };

  const forgetProviderKey = async () => {
    setBusy(true);
    try {
      setSnapshot(await invoke<RuntimeSnapshot>('desktop_forget_provider_key'));
      setError('Provider key removed from Windows Credential Manager. Save settings to restart with the change.');
    } catch (cause) { setError(cause instanceof Error ? cause.message : String(cause)); }
    finally { setBusy(false); }
  };

  const phase = snapshot?.phase ?? 'starting';
  const phaseLabel = phase === 'ready' ? 'Ready' : phase === 'starting' ? 'Starting' : phase === 'stopping' ? 'Stopping' : phase === 'degraded' ? 'Degraded' : phase === 'error' ? 'Needs attention' : 'Stopped';
  const StatusIcon = phase === 'error' || phase === 'degraded' ? CircleAlert : phase === 'ready' ? Activity : Database;

  return (
    <>
      <button className={`desktop-runtime-pill desktop-runtime-pill--${phase}`} type="button" onClick={() => setOpen(true)} aria-label={`AURA Desktop runtime: ${phaseLabel}. Open runtime settings`}>
        <span className="desktop-runtime-pill__led" />
        <StatusIcon size={14} />
        <span>AURA · {phaseLabel}</span>
        <ChevronDown size={13} />
      </button>
      {open ? (
        <div className="desktop-overlay" role="presentation" onMouseDown={(event) => { if (event.target === event.currentTarget) setOpen(false); }}>
          <section className="desktop-panel" role="dialog" aria-modal="true" aria-labelledby="desktop-runtime-title">
            <header className="desktop-panel__header">
              <div><span className="eyebrow">WINDOWS APP</span><h2 id="desktop-runtime-title">AURA Desktop</h2><p>Local runtime, data and Windows settings</p></div>
              <button className="icon-button" type="button" aria-label="Close desktop settings" onClick={() => setOpen(false)}><X size={17} /></button>
            </header>
            <div className={`desktop-runtime-summary desktop-runtime-summary--${phase}`}>
              <div><span className="desktop-runtime-summary__icon"><StatusIcon size={18} /></span><span><strong>{phaseLabel}</strong><small>{snapshot?.message ?? 'Checking the local runtime…'}</small></span></div>
              <span className="desktop-runtime-address">127.0.0.1:17890</span>
            </div>
            {error ? <div className="desktop-panel-error" role="alert"><CircleAlert size={15} /><span>{error}</span></div> : null}
            <div className="desktop-runtime-actions">
              <button className="primary-soft-button" type="button" disabled={busy || phase === 'starting' || phase === 'stopping'} onClick={() => void start(phase === 'ready')}>{busy || phase === 'starting' ? <RefreshCw size={15} className="desktop-spin" /> : <Activity size={15} />}{phase === 'ready' ? 'Restart runtime' : 'Start runtime'}</button>
              <button className="secondary-button" type="button" disabled={busy || !['ready', 'degraded', 'error'].includes(phase)} onClick={() => void stop()}><Power size={14} /> Stop and preserve data</button>
            </div>
            <div className="desktop-backup-actions">
              <button className="secondary-button" type="button" disabled={busy || phase !== 'ready'} onClick={() => void createBackup()}><Archive size={14} /> Create local backup</button>
              <button className="secondary-button" type="button" disabled={busy || !snapshot?.dockerAvailable} onClick={() => void restoreBackup()}><FolderSync size={14} /> Restore backup</button>
              <small>Includes PostgreSQL, workspace files and checkpoints. Windows Credential Manager secrets are excluded.</small>
            </div>
            {phase === 'error' && !snapshot?.dockerAvailable ? <p className="desktop-prerequisite">AURA Desktop needs Docker Desktop with the Linux engine running. Open Docker Desktop, wait for “Engine running”, then choose Start runtime. AURA will not install Docker.</p> : null}
            <details className="desktop-log-disclosure"><summary>Runtime log</summary><pre>{snapshot?.logs.length ? snapshot.logs.join('\n') : 'No runtime log entries yet.'}</pre></details>
            <form className="desktop-settings-form" onSubmit={(event) => void saveSettings(event)}>
              <div className="desktop-settings-section"><div><strong>Model provider</strong><small>No model is assumed on first launch. Mock returns deterministic demo answers; API keys are kept in Windows Credential Manager.</small></div>
                <label className="desktop-field"><span>Provider</span><select value={provider} onChange={(event) => setProvider(event.target.value as 'unconfigured' | 'mock' | 'openai')}><option value="unconfigured">Not configured</option><option value="mock">Offline demo · Mock</option><option value="openai">OpenAI-compatible cloud endpoint</option></select></label>
                {provider === 'unconfigured' ? <p className="desktop-prerequisite">Auto routing stays disabled until a provider is selected. Local Ollama and LM Studio models can be discovered and selected in Routing Studio.</p> : null}
                {provider === 'openai' ? <>
                  <label className="desktop-field"><span>Endpoint URL</span><input value={baseUrl} onChange={(event) => setBaseUrl(event.target.value)} placeholder="https://provider.example/v1" autoComplete="url" /></label>
                  <label className="desktop-field"><span>Exact model ID</span><input value={model} onChange={(event) => setModel(event.target.value)} placeholder="Copy the ID reported by your provider" autoComplete="off" /></label>
                  <label className="desktop-field"><span>API key {snapshot?.hasProviderKey ? '· already stored' : '· optional for endpoints that need none'}</span><input type="password" value={providerKey} onChange={(event) => setProviderKey(event.target.value)} placeholder={snapshot?.hasProviderKey ? 'Leave blank to keep the saved key' : 'Paste provider key if required'} autoComplete="new-password" /></label>
                  {snapshot?.hasProviderKey ? <button className="desktop-text-button" type="button" disabled={busy} onClick={() => void forgetProviderKey()}>Forget saved provider key</button> : null}
                </> : null}
              </div>
              {notifications ? <button className="desktop-text-button" type="button" onClick={() => notify('AURA Desktop test', 'Desktop notifications are working.')}>Send test notification</button> : null}
              <div className="desktop-settings-section desktop-settings-section--toggles">
                <label><span><strong>Close to tray</strong><small>Closing the window keeps the runtime running.</small></span><input type="checkbox" checked={closeToTray} onChange={(event) => setCloseToTray(event.target.checked)} /></label>
                <label><span><strong>Start with Windows</strong><small>Disabled by default.</small></span><input type="checkbox" checked={autostart} onChange={(event) => setAutostart(event.target.checked)} /></label>
                <label><span><strong>Desktop notifications</strong><small>Uses generic text; no chat content is included.</small></span><input type="checkbox" checked={notifications} onChange={(event) => setNotifications(event.target.checked)} /></label>
                <label><span><strong>Global shortcut</strong><small>Show the AURA window.</small></span><select value={globalShortcut} onChange={(event) => setGlobalShortcut(event.target.value)}><option value="CommandOrControl+Alt+A">Ctrl + Alt + A</option><option value="CommandOrControl+Shift+A">Ctrl + Shift + A</option><option value="none">Disabled</option></select></label>
              </div>
              <footer className="desktop-panel__footer"><span><Cog size={14} /> Postgres data is stored in a dedicated Docker volume.</span><button className="primary-button" type="submit" disabled={busy}>{busy ? 'Applying…' : 'Save settings & restart'}</button></footer>
            </form>
          </section>
        </div>
      ) : null}
    </>
  );
}
