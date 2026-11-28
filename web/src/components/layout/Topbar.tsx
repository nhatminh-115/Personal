import { Command, LockKeyhole, PanelRightOpen, Plus, Search } from 'lucide-react';

interface TopbarProps {
  projectName: string | null;
  globalTitle: string;
  projectWorkspace: boolean;
  createLabel: string;
  inspectorOpen: boolean;
  onToggleInspector: () => void;
  onOpenSearch: () => void;
  onCreate: () => void;
  onOpenPreferences: () => void;
}

export function Topbar({
  projectName,
  globalTitle,
  projectWorkspace,
  createLabel,
  inspectorOpen,
  onToggleInspector,
  onOpenSearch,
  onCreate,
  onOpenPreferences,
}: TopbarProps) {
  return (
    <header className="topbar">
      <div className="topbar__breadcrumb" aria-label="Current location">
        <span>Kuractus</span><span className="topbar__separator">/</span>
        {projectName ? <><span>{projectName}</span><span className="topbar__separator">/</span></> : null}
        <strong>{globalTitle}</strong>
      </div>

      <div className="topbar__actions">
        <button className="topbar-v16__search" type="button" onClick={onOpenSearch} title="Search anything · Ctrl+K">
          <Search size={14} /><span>Search anything</span><kbd><Command size={10} /> K</kbd>
        </button>
        <button className="topbar-v16__icon" type="button" onClick={onCreate} title={createLabel} aria-label={createLabel}><Plus size={17} /></button>
        <button className="topbar-v16__icon topbar-v16__privacy" type="button" onClick={onOpenPreferences} title="Privacy and preferences" aria-label="Privacy and preferences"><LockKeyhole size={15} /></button>

        {projectWorkspace ? <button className={`soft-pill inspector-toggle inspector-toggle--labeled ${inspectorOpen ? 'is-active' : ''}`} type="button" onClick={onToggleInspector} title="Toggle inspector"><PanelRightOpen size={14} /><span>Context</span></button> : null}
      </div>
    </header>
  );
}
