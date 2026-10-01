import { ChevronDown, Command, Files, LayoutDashboard, PanelRightOpen, Sparkles } from 'lucide-react';
import type { CSSProperties } from 'react';
import type { EffectiveRouting, ModelCatalog, ReasoningEffort, WorkspaceMode } from '../../types';
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
  effectiveRouting: EffectiveRouting | null;
  catalog: ModelCatalog;
  sessionAvailable: boolean;
  lockedModel: string | null;
  reasoningOverride: ReasoningEffort | null;
  onSetModelLock: (value: string | null) => void;
  onSetReasoningOverride: (value: ReasoningEffort | null) => void;
  onOpenRoutingStudio: () => void;
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
  effectiveRouting,
  catalog,
  sessionAvailable,
  lockedModel,
  reasoningOverride,
  onSetModelLock,
  onSetReasoningOverride,
  onOpenRoutingStudio,
  inspectorOpen,
  onToggleInspector,
  onOpenAura,
}: TopbarProps) {
  const activeIndex = modes.indexOf(mode);
  const inProject = Boolean(projectName);
  const lockedParts = lockedModel?.split(':');
  const lockedModelInfo = lockedParts?.length === 2
    ? catalog.providers.find((provider) => provider.id === lockedParts[0])?.models.find((model) => model.id === lockedParts[1])
    : undefined;
  const fixedReasoning = lockedModelInfo?.reasoning_support === 'fixed_by_model';

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
        {inProject ? (
          <div className="routing-trigger-wrap">
            <button
              className={`soft-pill ${routingOpen ? 'is-active' : ''}`}
              type="button"
              onClick={() => onRoutingOpenChange(!routingOpen)}
            >
              <span>{effectiveRouting?.profile?.name ? `${effectiveRouting.profile.name} · ${effectiveRouting.winning_scope}` : 'Routing…'}</span>
              <ChevronDown size={13} />
            </button>
            {routingOpen ? <RoutingPopover
              effective={effectiveRouting}
              catalog={catalog}
              sessionAvailable={sessionAvailable}
              lockedModel={lockedModel}
              reasoningOverride={reasoningOverride}
              onSetModel={onSetModelLock}
              onSetReasoning={onSetReasoningOverride}
              onOpenStudio={onOpenRoutingStudio}
              onClose={() => onRoutingOpenChange(false)}
            /> : null}
          </div>
        ) : null}

        {inProject ? (
          <select aria-label="Temporary reasoning override" className="topbar-reasoning-select" value={reasoningOverride ?? ''} title={fixedReasoning ? 'The locked model controls reasoning internally.' : undefined} onChange={(event) => onSetReasoningOverride((event.target.value || null) as ReasoningEffort | null)}>
            <option value="">Reasoning: Profile</option>
            {fixedReasoning ? reasoningOverride ? <option value={reasoningOverride} disabled>Reasoning: {reasoningOverride} · unavailable</option> : <option disabled>Reasoning: fixed by model</option> : (['instant', 'low', 'medium', 'high', 'max'] as const).map((value) => <option key={value} value={value}>Reasoning: {value[0].toUpperCase() + value.slice(1)}</option>)}
          </select>
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
