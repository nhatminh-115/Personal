import { ChevronDown, Command, LockKeyhole, PanelRightOpen, Plus, Search, Sparkles } from 'lucide-react';
import type { EffectiveRouting, ModelCatalog, ReasoningEffort } from '../../types';
import { RoutingPopover } from '../ui/RoutingPopover';
import { CustomSelect } from '../ui/CustomSelect';

interface TopbarProps {
  projectName: string | null;
  globalTitle: string;
  projectWorkspace: boolean;
  createLabel: string;
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
  onOpenSearch: () => void;
  onCreate: () => void;
  onOpenPreferences: () => void;
}

export function Topbar({
  projectName,
  globalTitle,
  projectWorkspace,
  createLabel,
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
  onOpenSearch,
  onCreate,
  onOpenPreferences,
}: TopbarProps) {
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

        {projectWorkspace ? (
          <>
            <div className="routing-trigger-wrap">
              <button className={`soft-pill ${routingOpen ? 'is-active' : ''}`} type="button" onClick={() => onRoutingOpenChange(!routingOpen)}>
                <Sparkles size={13} /><span>{effectiveRouting?.profile?.name ? `${effectiveRouting.profile.name} · ${effectiveRouting.winning_scope}` : 'Routing…'}</span><ChevronDown size={13} />
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
            <button className={`soft-pill inspector-toggle inspector-toggle--labeled ${inspectorOpen ? 'is-active' : ''}`} type="button" onClick={onToggleInspector} title="Toggle inspector">
              <PanelRightOpen size={14} /><span>Context</span>
            </button>
          </>
        ) : null}
      </div>
    </header>
  );
}
