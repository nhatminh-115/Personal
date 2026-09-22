import { ChevronDown, Command, Files, LayoutDashboard, LockKeyhole, PanelRightOpen, Sparkles } from 'lucide-react';
import type { CSSProperties } from 'react';
import type { WorkspaceMode } from '../../types';
import { RoutingPopover } from '../ui/RoutingPopover';

interface TopbarProps {
  projectName: string | null;
  projectSection: 'overview' | 'workspace' | 'files' | null;
  globalTitle: string;
  mode: WorkspaceMode;
  onModeChange: (mode: WorkspaceMode) => void;
  onOpenProjectOverview: () => void;
  onOpenProjectFiles: () => void;
  routingOpen: boolean;
  onRoutingOpenChange: (open: boolean) => void;
  locked: boolean;
  onToggleLock: () => void;
  inspectorOpen: boolean;
  onToggleInspector: () => void;
  onOpenAura: () => void;
}

const modes: WorkspaceMode[] = ['chat', 'board', 'split'];

export function Topbar({
  projectName,
  projectSection,
  globalTitle,
  mode,
  onModeChange,
  onOpenProjectOverview,
  onOpenProjectFiles,
  routingOpen,
  onRoutingOpenChange,
  locked,
  onToggleLock,
  inspectorOpen,
  onToggleInspector,
  onOpenAura,
}: TopbarProps) {
  const activeIndex = modes.indexOf(mode);
  const inProject = Boolean(projectName);

  return (
    <header className="topbar">
      <div className="topbar__project">
        <span className="topbar__label">{inProject ? 'Project' : 'Personal workspace'}</span>
        <strong>{projectName ?? globalTitle}</strong>
      </div>

      {inProject ? (
        <div className="project-topnav" aria-label="Project navigation">
          <button className={projectSection === 'overview' ? 'is-active' : ''} type="button" onClick={onOpenProjectOverview}><LayoutDashboard size={13} /> Overview</button>
          <div className={`view-switch view-switch--tubelight ${projectSection !== 'workspace' ? 'view-switch--idle' : ''}`} role="group" aria-label="Workspace mode" style={{ '--active-index': activeIndex } as CSSProperties}>
            <span className="view-switch__lamp" aria-hidden="true" />
            {modes.map((value) => (
              <button
                type="button"
                key={value}
                className={projectSection === 'workspace' && mode === value ? 'is-active' : ''}
                aria-pressed={projectSection === 'workspace' && mode === value}
                onClick={() => onModeChange(value)}
              >
                {value[0].toUpperCase() + value.slice(1)}
              </button>
            ))}
          </div>
          <button className={projectSection === 'files' ? 'is-active' : ''} type="button" onClick={onOpenProjectFiles}><Files size={13} /> Files</button>
        </div>
      ) : <div className="topbar__global-spacer" />}

      <div className="topbar__actions">
        <button className="soft-pill aura-quick-trigger" type="button" onClick={onOpenAura} title="Ask AURA · Ctrl/⌘ K">
          <Sparkles size={13} />
          <span>Ask AURA</span>
          <Command size={11} />
        </button>
        {inProject && locked ? (
          <button className="lock-pill" type="button" onClick={onToggleLock}>
            <LockKeyhole size={13} />
            <span>LOCKED · Model C</span>
          </button>
        ) : null}

        {inProject ? (
          <div className="routing-trigger-wrap">
            <button
              className={`soft-pill ${routingOpen ? 'is-active' : ''}`}
              type="button"
              onClick={() => onRoutingOpenChange(!routingOpen)}
            >
              <span>Balanced · Session</span>
              <ChevronDown size={13} />
            </button>
            {routingOpen ? <RoutingPopover locked={locked} onToggleLock={onToggleLock} onClose={() => onRoutingOpenChange(false)} /> : null}
          </div>
        ) : null}

        {inProject ? (
          <button className="soft-pill" type="button">
            <Sparkles size={13} />
            <span>Reasoning: Profile</span>
          </button>
        ) : null}

        {inProject && projectSection === 'workspace' ? (
          <button
            className={`soft-pill inspector-toggle inspector-toggle--labeled ${inspectorOpen ? 'is-active' : ''}`}
            type="button"
            onClick={onToggleInspector}
            title="Toggle inspector"
          >
            <PanelRightOpen size={15} />
            <span>Inspector</span>
          </button>
        ) : null}
      </div>
    </header>
  );
}
