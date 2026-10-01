import { Lock, SlidersHorizontal, X } from 'lucide-react';
import type { EffectiveRouting, ModelCatalog, ReasoningEffort } from '../../types';

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
  const reasoningUnknown = Boolean(lockedModel && (!lockedModelInfo?.reasoning_support || lockedModelInfo.reasoning_support === 'unknown'));

  return (
    <div className="popover routing-popover" role="dialog" aria-label="Routing controls">
      <div className="popover__header">
        <div><span className="eyebrow">ROUTING</span><h3>{profile?.name ?? 'Loading routing…'}</h3></div>
        <button className="icon-button" type="button" onClick={onClose} aria-label="Close routing controls"><X size={16} /></button>
      </div>
      <div className="routing-scope-row"><span>Winning scope</span><strong>{effective?.winning_scope ?? '—'}</strong></div>
      {profile ? <div className="routing-scope-row"><span>Privacy · fallback</span><strong>{profile.global_privacy_policy} · {profile.global_fallback_policy}</strong></div> : null}
      {demoThread ? <p className="routing-note">Temporary controls apply only to live chats. Start a live chat before setting a model or reasoning override.</p> : null}
      <label className="routing-control-label" htmlFor="routing-model-lock">Temporary exact model lock</label>
      <select id="routing-model-lock" value={lockedModel ?? ''} disabled={demoThread} onChange={(event) => onSetModel(event.target.value || null)}>
        <option value="">Unlocked · follow profile</option>
        {availableModels.map((model) => <option key={model.value} value={model.value} disabled={model.disabled}>{model.label}{model.disabled ? ' · unavailable' : ''}</option>)}
      </select>
      {lockedModel ? <button type="button" className="secondary-button routing-clear-lock" disabled={demoThread} onClick={() => onSetModel(null)}><Lock size={14} /> Clear model lock</button> : null}
      <label className="routing-control-label" htmlFor="routing-reasoning">Temporary reasoning</label>
      <select id="routing-reasoning" value={reasoningOverride ?? ''} disabled={demoThread} onChange={(event) => onSetReasoning((event.target.value || null) as ReasoningEffort | null)}>
        <option value="">Profile</option>
        {fixedReasoning ? reasoningOverride ? <option value={reasoningOverride} disabled>{reasoningOverride} · unavailable for fixed-by-model control</option> : <option disabled>Fixed by model</option> : (['instant', 'low', 'medium', 'high', 'max'] as const).map((effort) => <option key={effort} value={effort}>{effort[0].toUpperCase() + effort.slice(1)}</option>)}
      </select>
      {reasoningUnknown ? <p className="routing-note">Reasoning support for this exact model is unknown; the backend may reject a temporary effort request.</p> : null}
      {!sessionAvailable ? <p className="routing-note">Session routing becomes available after this live chat has started.</p> : null}
      <div className="popover__actions">
        <button className="secondary-button" type="button" disabled={demoThread} onClick={() => onSetReasoning(null)}><SlidersHorizontal size={14} /> Reset reasoning</button>
        <button className="primary-button" type="button" onClick={onOpenStudio}>Open Routing Studio</button>
      </div>
    </div>
  );
}
