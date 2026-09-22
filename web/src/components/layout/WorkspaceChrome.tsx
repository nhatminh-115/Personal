import { ArrowLeft, ArrowRight, Globe2, Home, Library, Search, X } from 'lucide-react';
import { useEffect, useRef, useState } from 'react';

export type AuraTabKind = 'home' | 'library' | 'project' | 'folder' | 'file' | 'workspace';

export interface AuraTab {
  id: string;
  title: string;
  subtitle?: string;
  kind: AuraTabKind;
  closable?: boolean;
}

interface WorkspaceChromeProps {
  tabs: AuraTab[];
  activeTabId: string;
  locationValue: string;
  canGoBack: boolean;
  canGoForward: boolean;
  onGoBack: () => void;
  onGoForward: () => void;
  onSelectTab: (id: string) => void;
  onCloseTab: (id: string) => void;
  onSubmitLocation: (value: string) => void;
}

function tabIcon(kind: AuraTabKind) {
  if (kind === 'home') return Home;
  if (kind === 'library' || kind === 'folder') return Library;
  return Globe2;
}

export function WorkspaceChrome({
  tabs,
  activeTabId,
  locationValue,
  canGoBack,
  canGoForward,
  onGoBack,
  onGoForward,
  onSelectTab,
  onCloseTab,
  onSubmitLocation,
}: WorkspaceChromeProps) {
  const [draft, setDraft] = useState(locationValue);
  const inputRef = useRef<HTMLInputElement | null>(null);

  useEffect(() => setDraft(locationValue), [locationValue]);

  useEffect(() => {
    const onKey = (event: KeyboardEvent) => {
      if ((event.metaKey || event.ctrlKey) && event.key.toLowerCase() === 'l') {
        event.preventDefault();
        inputRef.current?.focus();
        inputRef.current?.select();
      }
    };
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, []);

  return (
    <div className="workspace-chrome">
      <div className="workspace-tab-strip" role="tablist" aria-label="AURA tabs">
        {tabs.map((tab) => {
          const Icon = tabIcon(tab.kind);
          return (
            <div key={tab.id} className={`workspace-tab ${tab.id === activeTabId ? 'is-active' : ''}`} role="tab" aria-selected={tab.id === activeTabId}>
              <button className="workspace-tab__main" type="button" onClick={() => onSelectTab(tab.id)} title={tab.subtitle ?? tab.title}>
                <Icon size={15} />
                <span>{tab.title}</span>
              </button>
              {tab.closable !== false && tabs.length > 1 ? <button className="workspace-tab__close" type="button" onClick={() => onCloseTab(tab.id)} title="Close tab"><X size={13} /></button> : null}
            </div>
          );
        })}
      </div>

      <div className="workspace-location-row">
        <div className="workspace-history-buttons">
          <button className="icon-button icon-button--lg" type="button" disabled={!canGoBack} onClick={onGoBack} title="Back"><ArrowLeft size={18} /></button>
          <button className="icon-button icon-button--lg" type="button" disabled={!canGoForward} onClick={onGoForward} title="Forward"><ArrowRight size={18} /></button>
        </div>
        <form className="workspace-location-bar" onSubmit={(event) => { event.preventDefault(); onSubmitLocation(draft); }}>
          <Search size={16} />
          <input ref={inputRef} value={draft} onChange={(event) => setDraft(event.target.value)} placeholder="Search files, projects, chats, notes or enter a URL…" />
          <kbd>Ctrl L</kbd>
        </form>
      </div>
    </div>
  );
}
