import { ArrowRight, KeyRound, MonitorCog, ShieldCheck, Sparkles } from 'lucide-react';

interface PreferencesViewProps {
  apiTokenConfigured: boolean;
  desktop: boolean;
  onOpenApiAccess: () => void;
  onOpenAIProvider: () => void;
  onOpenDesktopSettings: () => void;
}

export function PreferencesView({ apiTokenConfigured, desktop, onOpenApiAccess, onOpenAIProvider, onOpenDesktopSettings }: PreferencesViewProps) {
  return (
    <section className="preferences-v16" aria-labelledby="preferences-v16-title">
      <header className="preferences-v16__intro">
        <span className="eyebrow">YOUR WORKSPACE</span>
        <h1 id="preferences-v16-title">Preferences</h1>
        <p>Manage AI providers, desktop behavior, and general access for Kuractus.</p>
      </header>

      <div className="preferences-v16__grid">
        <section className="preferences-card-v16">
          <span className="preferences-card-v16__icon"><Sparkles size={17} /></span>
          <div><span className="eyebrow">AI PROVIDER</span><h2>Models and API keys</h2><p>Connect a supported provider, test access, and choose the models available to your conversations.</p></div>
          <button type="button" onClick={onOpenAIProvider}>{desktop ? 'Manage AI providers' : 'View provider status'} <ArrowRight size={14} /></button>
        </section>

        {desktop ? (
          <section className="preferences-card-v16">
            <span className="preferences-card-v16__icon"><MonitorCog size={17} /></span>
            <div><span className="eyebrow">DESKTOP</span><h2>Runtime and app behavior</h2><p>Manage the local runtime, backups, startup, notifications, and desktop shortcuts.</p></div>
            <button type="button" onClick={onOpenDesktopSettings}>Desktop settings <ArrowRight size={14} /></button>
          </section>
        ) : null}

        {!desktop ? (
          <section className="preferences-card-v16">
            <span className="preferences-card-v16__icon"><KeyRound size={17} /></span>
            <div><span className="eyebrow">SERVER ACCESS</span><h2>Server API token</h2><p>{apiTokenConfigured ? 'A shared token is saved for this browser session.' : 'Set the shared access token required by this Kuractus server.'}</p></div>
            <button type="button" onClick={onOpenApiAccess}>{apiTokenConfigured ? 'Manage server token' : 'Set up server access'} <ArrowRight size={14} /></button>
          </section>
        ) : null}

        <section className="preferences-card-v16 preferences-card-v16--wide preferences-card-v16--privacy">
          <span className="preferences-card-v16__icon"><ShieldCheck size={17} /></span>
          <div><span className="eyebrow">GENERAL</span><h2>Privacy stays explicit</h2><p>Notes keep their own privacy classification. Local file contents are included only when you choose them for a message; workspace files and the database remain in their configured storage.</p></div>
          <ShieldCheck size={16} aria-hidden="true" />
        </section>
      </div>
    </section>
  );
}
