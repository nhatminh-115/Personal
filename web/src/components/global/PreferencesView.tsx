import { ArrowRight, KeyRound, LockKeyhole, MonitorCog, Route, ShieldCheck } from 'lucide-react';

interface PreferencesViewProps {
  apiTokenConfigured: boolean;
  onOpenApiAccess: () => void;
  onOpenDesktopSettings: () => void;
  onOpenRouting: () => void;
}

export function PreferencesView({ apiTokenConfigured, onOpenApiAccess, onOpenDesktopSettings, onOpenRouting }: PreferencesViewProps) {
  return (
    <section className="preferences-v16" aria-labelledby="preferences-v16-title">
      <header className="preferences-v16__intro">
        <span className="eyebrow">YOUR WORKSPACE</span>
        <h1 id="preferences-v16-title">Preferences</h1>
        <p>Connection, privacy, and desktop behavior for this AURA workspace.</p>
      </header>

      <div className="preferences-v16__grid">
        <section className="preferences-card-v16">
          <span className="preferences-card-v16__icon"><KeyRound size={17} /></span>
          <div><span className="eyebrow">CONNECTION</span><h2>API access</h2><p>{apiTokenConfigured ? 'A server token is saved for this browser session.' : 'Connect to an AURA server that requires a shared API token.'}</p></div>
          <button type="button" onClick={onOpenApiAccess}>{apiTokenConfigured ? 'Manage token' : 'Set up access'} <ArrowRight size={14} /></button>
        </section>

        <section className="preferences-card-v16">
          <span className="preferences-card-v16__icon"><Route size={17} /></span>
          <div><span className="eyebrow">MODELS</span><h2>Routing</h2><p>Review provider discovery, routing profiles, and model choices for the active project.</p></div>
          <button type="button" onClick={onOpenRouting}>Open routing studio <ArrowRight size={14} /></button>
        </section>

        <section className="preferences-card-v16 preferences-card-v16--wide">
          <span className="preferences-card-v16__icon"><MonitorCog size={17} /></span>
          <div><span className="eyebrow">WINDOWS DESKTOP</span><h2>Desktop and local runtime</h2><p>Configure the local provider, Docker runtime, startup behavior, notifications, and global shortcut. API keys remain in Windows Credential Manager.</p></div>
          <button type="button" onClick={onOpenDesktopSettings}>Open desktop settings <ArrowRight size={14} /></button>
        </section>

        <section className="preferences-card-v16 preferences-card-v16--wide preferences-card-v16--privacy">
          <span className="preferences-card-v16__icon"><ShieldCheck size={17} /></span>
          <div><span className="eyebrow">PRIVACY</span><h2>Privacy stays explicit</h2><p>Notes keep their own privacy classification. Local file contents are included only when you choose them for a message; workspace files and the database remain in their configured storage.</p></div>
          <LockKeyhole size={16} aria-hidden="true" />
        </section>
      </div>
    </section>
  );
}
