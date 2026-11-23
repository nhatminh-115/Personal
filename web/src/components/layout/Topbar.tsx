import { ChevronDown, Command, Files, KeyRound, LayoutDashboard, PanelRightOpen, Sparkles } from 'lucide-react';
import type { CSSProperties } from 'react';
import type { EffectiveRouting, ModelCatalog, ReasoningEffort, WorkspaceMode } from '../../types';
import { RoutingPopover } from '../ui/RoutingPopover';
import { CustomSelect } from '../ui/CustomSelect';

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
  demoThread: boolean;
  lockedModel: string | null;
  reasoningOverride: ReasoningEffort | null;
  onSetModelLock: (value: string | null) => void;
  onSetReasoningOverride: (value: ReasoningEffort | null) => void;
  onOpenRoutingStudio: () => void;
  inspectorOpen: boolean;
  onToggleInspector: () => void;
  onOpenAura: () => void;
  apiTokenConfigured: boolean;
  onOpenApiAccess: () => void;
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
  demoThread,
  lockedModel,
  reasoningOverride,
  onSetModelLock,
  onSetReasoningOverride,
  onOpenRoutingStudio,
  inspectorOpen,
  onToggleInspector,
  onOpenAura,
  apiTokenConfigured,
  onOpenApiAccess,
}: TopbarProps) {
  const activeIndex = modes.indexOf(mode);
  const inProject = Boolean(projectName);
  const lockedParts = lockedModel?.split(':');
  const lockedModelInfo = lockedParts?.length === 2
    ? catalog.providers.find((provider) => provider.id === lockedParts[0])?.models.find((model) => model.id === lockedParts[1])
    : undefined;
  const fixedReasoning = lockedModelInfo?.reasoning_support === 'fixed_by_model';
  const unsupportedReasoning = lockedModelInfo?.reasoning_support === 'unsupported';
  const reasoningUnknown = Boolean(lockedModel && (!lockedModelInfo?.reasoning_support || lockedModelInfo.reasoning_support === 'unknown'));
  const reasoningOptions = [
    {
      value: '',
      label: fixedReasoning ? 'Fixed by model' : unsupportedReasoning ? 'Unsupported' : 'Profile',
      description: fixedReasoning
        ? 'The selected model controls its own reasoning.'
        : unsupportedReasoning
          ? 'This model does not expose a reasoning control.'
          : 'Use the project routing profile',
    },
    ...(fixedReasoning || unsupportedReasoning
      ? reasoningOverride ? [{ value: reasoningOverride, label: `${reasoningOverride} · unavailable`, disabled: true }] : []
      : (['instant', 'low', 'medium', 'high', 'max'] as const).map((value) => ({
        value,
        label: value[0].toUpperCase() + value.slice(1),
        description: value === 'instant' ? 'Prioritize response speed' : value === 'max' ? 'Use the maximum available effort' : `Use ${value} reasoning effort`,
      }))),
  ];

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
        <button className="soft-pill aura-quick-trigger" type="button" onClick={onOpenAura} title="Search workspace · Ctrl/⌘ K">
          <Sparkles size={13} />
          <span>Search</span>
          <Command size={11} />
        </button>
        <button
          className={`soft-pill api-access-trigger ${apiTokenConfigured ? 'is-active' : ''}`}
          type="button"
          onClick={onOpenApiAccess}
          title={apiTokenConfigured ? 'Replace the API token saved for this tab' : 'Enter an API token if this server requires one'}
        >
          <KeyRound size={13} />
          <span>{apiTokenConfigured ? 'API key set' : 'API access'}</span>
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
              demoThread={demoThread}
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
        <CustomSelect
          ariaLabel="Temporary reasoning override"
          label="Reasoning"
          variant="topbar"
          value={reasoningOverride ?? ''}
          disabled={demoThread || fixedReasoning || unsupportedReasoning}
          title={demoThread
            ? 'Start a live chat to use temporary reasoning overrides.'
            : fixedReasoning
              ? 'The locked model controls reasoning internally.'
              : unsupportedReasoning
                ? 'The locked model does not support reasoning controls.'
                : reasoningUnknown
                  ? 'Reasoning support for this exact model is unknown; the backend may reject an override.'
                  : undefined}
          onChange={(value) => onSetReasoningOverride((value || null) as ReasoningEffort | null)}
          options={reasoningOptions}
        />
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
