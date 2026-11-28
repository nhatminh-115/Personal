import { Lock, SlidersHorizontal, X } from 'lucide-react';
import type { EffectiveRouting, ModelCatalog, ReasoningEffort } from '../../types';
import { CustomSelect } from './CustomSelect';

interface RoutingPopoverProps {
  effective: EffectiveRouting | null;
  catalog: ModelCatalog;
  sessionAvailable: boolean;
  demoThread: boolean;
  lockedModel: string | null;
  reasoningOverride: ReasoningEffort | null;
  onSetModel: (value: string | null) => void;
  onSetReasoning: (value: ReasoningEffort | null) => void;
  onOpenStudio: () => void;
  onClose: () => void;
}

export function RoutingPopover({
  effective, catalog, sessionAvailable, demoThread, lockedModel, reasoningOverride,
  onSetModel, onSetReasoning, onOpenStudio, onClose,
}: RoutingPopoverProps) {
  const profile = effective?.profile;
  const availableModels = catalog.providers.flatMap((provider) => provider.models.map((model) => ({
    value: `${provider.id}:${model.id}`,
    label: `${provider.label} · ${model.label}`,
    disabled: !provider.available,
  })));
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
        ? 'The model controls reasoning internally.'
        : unsupportedReasoning
          ? 'This model has no reasoning control.'
          : 'Use the project profile',
    },
    ...(fixedReasoning || unsupportedReasoning
      ? reasoningOverride ? [{ value: reasoningOverride, label: `${reasoningOverride} · unavailable`, disabled: true }] : []
      : (['instant', 'low', 'medium', 'high', 'max'] as const).map((effort) => ({
        value: effort,
        label: effort[0].toUpperCase() + effort.slice(1),
        description: effort === 'instant' ? 'Prioritize response speed' : effort === 'max' ? 'Use the maximum available effort' : `Use ${effort} reasoning effort`,
      }))),
  ];

  return (
    <div className="popover routing-popover" role="dialog" aria-label="Routing controls">
      <div className="popover__header">
        <div><span className="eyebrow">ROUTING</span><h3>{profile?.name ?? 'Loading routing…'}</h3></div>
        <button className="icon-button" type="button" onClick={onClose} aria-label="Close routing controls"><X size={16} /></button>
      </div>
      <div className="routing-scope-row"><span>Winning scope</span><strong>{effective?.winning_scope ?? '—'}</strong></div>
      {profile ? <div className="routing-scope-row"><span>Privacy · fallback</span><strong>{profile.global_privacy_policy} · {profile.global_fallback_policy}</strong></div> : null}
      {demoThread ? <p className="routing-note">Temporary controls apply only to live chats. Start a live chat before setting a model or reasoning override.</p> : null}
      <span className="routing-control-label">Temporary exact model lock</span>
      <CustomSelect
        ariaLabel="Temporary exact model lock"
        value={lockedModel ?? ''}
        disabled={demoThread}
        className="routing-popover-select"
        onChange={(value) => onSetModel(value || null)}
        options={[
          { value: '', label: 'Unlocked · follow profile', description: 'Let the project profile select the model.' },
          ...availableModels.map((model) => ({
            ...model,
            label: model.disabled ? `${model.label} · unavailable` : model.label,
            description: model.disabled ? 'This provider is currently unavailable.' : 'Available for a temporary model lock',
          })),
        ]}
      />
      {lockedModel ? <button type="button" className="secondary-button routing-clear-lock" disabled={demoThread} onClick={() => onSetModel(null)}><Lock size={14} /> Clear model lock</button> : null}
      <span className="routing-control-label">Temporary reasoning</span>
      <CustomSelect
        ariaLabel="Temporary reasoning"
        value={reasoningOverride ?? ''}
        disabled={demoThread || fixedReasoning || unsupportedReasoning}
        className="routing-popover-select"
        onChange={(value) => onSetReasoning((value || null) as ReasoningEffort | null)}
        options={reasoningOptions}
      />
      {fixedReasoning ? <p className="routing-note">This exact model controls reasoning internally; temporary effort overrides are unavailable.</p> : null}
      {unsupportedReasoning ? <p className="routing-note">This exact model does not support reasoning controls.</p> : null}
      {reasoningUnknown ? <p className="routing-note">Reasoning support for this exact model is unknown; the backend may reject a temporary effort request.</p> : null}
      {!sessionAvailable ? <p className="routing-note">Session routing becomes available after this live chat has started.</p> : null}
      <div className="popover__actions">
        <button className="secondary-button" type="button" disabled={demoThread} onClick={() => onSetReasoning(null)}><SlidersHorizontal size={14} /> Reset reasoning</button>
        <button className="primary-button" type="button" onClick={onOpenStudio}>Open Routing Studio</button>
      </div>
    </div>
  );
}
