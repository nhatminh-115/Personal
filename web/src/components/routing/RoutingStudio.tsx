import { useEffect, useMemo, useState } from 'react';
import { api, ApiError } from '../../services/api';
import type { EffectiveRouting, ModelCatalog, ReasoningEffort, RoutingDecision, RoutingFallback, RoutingPrivacy, RoutingProfile, RoutingRoute, RoutingProfileValidation } from '../../types';

const ROLES = ['root', 'research', 'coding', 'writing'];
const PRIVACY: RoutingPrivacy[] = ['public', 'internal', 'confidential', 'local_only'];
const FALLBACK: RoutingFallback[] = ['none', 'same_provider_only', 'local_only', 'cloud_allowed', 'ask_before_cloud'];
const EFFORTS: ReasoningEffort[] = ['instant', 'low', 'medium', 'high', 'max'];

function emptyRoute(): RoutingRoute {
  return { model_override: null, provider_override: null, reasoning: { policy: 'adaptive', effort: 'medium', min_effort: 'low', max_effort: 'high' }, privacy_policy: null, fallback_policy: null };
}

function newProfile(): RoutingProfile {
  return { name: 'New profile', version: 1, is_active: true, is_default: false, global_privacy_policy: 'internal', global_fallback_policy: 'ask_before_cloud', cost_preference: 'normal', latency_preference: 'normal', routes: Object.fromEntries(ROLES.map((role) => [role, emptyRoute()])) };
}

interface RoutingStudioProps {
  open: boolean;
  projectName: string;
  sessionId?: string;
  sessionAvailable: boolean;
  demoThread: boolean;
  effective: EffectiveRouting | null;
  catalog: ModelCatalog;
  onClose: () => void;
  onSaved: () => void;
  onSetModelLock: (model: string | null) => void;
  onRefreshModels: () => Promise<void>;
}

export function RoutingStudio({ open, projectName, sessionId, sessionAvailable, demoThread, effective, catalog, onClose, onSaved, onSetModelLock, onRefreshModels }: RoutingStudioProps) {
  const [profiles, setProfiles] = useState<RoutingProfile[]>([]);
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [draft, setDraft] = useState<RoutingProfile | null>(null);
  const [scope, setScope] = useState<'project' | 'session' | 'default'>('project');
  const [scopeProfileId, setScopeProfileId] = useState<string>('system-balanced');
  const [initialAssignment, setInitialAssignment] = useState('system-balanced');
  const [sessionProfileId, setSessionProfileId] = useState('system-balanced');
  const [initialSessionProfileId, setInitialSessionProfileId] = useState('system-balanced');
  const [defaultProfileId, setDefaultProfileId] = useState('system-balanced');
  const [initialDefaultProfileId, setInitialDefaultProfileId] = useState('system-balanced');
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const [previewRole, setPreviewRole] = useState('root');
  const [previewTask, setPreviewTask] = useState('');
  const [previewComplexity, setPreviewComplexity] = useState<'simple' | 'medium' | 'complex'>('medium');
  const [previewTools, setPreviewTools] = useState(false);
  const [previewVision, setPreviewVision] = useState(false);
  const [previewStructured, setPreviewStructured] = useState(false);
  const [previewLong, setPreviewLong] = useState(false);
  const [previewCapabilities, setPreviewCapabilities] = useState('');
  const [previewModelLock, setPreviewModelLock] = useState('');
  const [previewReasoning, setPreviewReasoning] = useState<ReasoningEffort | ''>('');
  const [preview, setPreview] = useState<RoutingDecision | null>(null);
  const [validation, setValidation] = useState<RoutingProfileValidation | null>(null);
  const [modelBrowser, setModelBrowser] = useState(false);
  const [probeResults, setProbeResults] = useState<Record<string, string>>({});

  const dirty = useMemo(() => Boolean(draft && JSON.stringify(draft) !== JSON.stringify(profiles.find((item) => item.id === selectedId) ?? null)), [draft, profiles, selectedId]);
  const effortOrder = ['instant', 'low', 'medium', 'high', 'max'];
  const profileErrors = Object.entries(draft?.routes ?? {}).flatMap(([role, route]) => {
    if (route.reasoning.policy !== 'adaptive') return [];
    const min = route.reasoning.min_effort;
    const max = route.reasoning.max_effort;
    if (!min || !max) return [`${role}: adaptive reasoning needs both minimum and maximum effort.`];
    return effortOrder.indexOf(min) > effortOrder.indexOf(max)
      ? [`${role}: minimum effort must be at or below maximum effort.`]
      : [];
  });
  const assignmentDirty = scope === 'project'
    ? scopeProfileId !== initialAssignment
    : scope === 'session'
      ? sessionProfileId !== initialSessionProfileId
      : defaultProfileId !== initialDefaultProfileId;
  const readOnly = draft?.id === 'system-balanced';

  useEffect(() => {
    if (!open) return;
    let active = true;
    setError('');
    const sessionRequest = sessionAvailable && sessionId
      ? api.fetchSessionRouting(sessionId).catch(() => ({ session_id: sessionId, routing_profile_id: null }))
      : Promise.resolve({ session_id: '', routing_profile_id: null });
    void Promise.all([api.fetchRoutingProfiles(), api.fetchProjectRouting(projectName), sessionRequest]).then(([items, assignment, sessionAssignment]) => {
      if (!active) return;
      const validProfiles = Array.isArray(items) ? items : [];
      setProfiles(validProfiles);
      const currentId = effective?.profile?.id ?? validProfiles[0]?.id ?? null;
      setSelectedId(currentId ?? null);
      setDraft(validProfiles.find((profile) => profile.id === currentId) ?? validProfiles[0] ?? null);
      setScopeProfileId(assignment.routing_profile_id ?? 'system-balanced');
      setInitialAssignment(assignment.routing_profile_id ?? 'system-balanced');
      const selectedDefault = validProfiles.find((profile) => profile.is_default)?.id ?? 'system-balanced';
      setDefaultProfileId(selectedDefault);
      setInitialDefaultProfileId(selectedDefault);
      const selectedSession = sessionAssignment.routing_profile_id ?? 'system-balanced';
      setSessionProfileId(selectedSession);
      setInitialSessionProfileId(selectedSession);
    }).catch((err: Error) => { if (active) setError(err.message); });
    return () => { active = false; };
  }, [open, projectName, effective?.profile?.id]);

  if (!open) return null;
  const update = (patch: Partial<RoutingProfile>) => setDraft((value) => value ? { ...value, ...patch } : value);
  const updateRoute = (role: string, patch: Partial<RoutingRoute>) => setDraft((value) => value ? {
    ...value,
    routes: { ...value.routes, [role]: { ...emptyRoute(), ...value.routes[role], ...patch, reasoning: { ...emptyRoute().reasoning, ...value.routes[role]?.reasoning, ...patch.reasoning } } },
  } : value);
  const selectProfile = (id: string | null, value?: RoutingProfile) => {
    if (dirty && !window.confirm('Discard unsaved routing profile changes?')) return;
    const next = value ?? profiles.find((profile) => profile.id === id) ?? newProfile();
    setSelectedId(id);
    setDraft(next);
    setScopeProfileId(next.id ?? 'system-balanced');
    setError('');
  };

  async function save() {
    if (!draft) return;
    if (profileErrors.length) {
      setValidation({ valid: false, profile_id: draft.id ?? 'draft', errors: profileErrors });
      return;
    }
    setBusy(true); setError('');
    try {
      const saved = dirty ? await api.saveRoutingProfile(draft) : draft;
      const next = dirty ? [...profiles.filter((item) => item.id !== saved.id), saved].sort((a, b) => a.name.localeCompare(b.name)) : profiles;
      let updatedProfiles = next;
      if (scope === 'default') {
        const chosenDefault = defaultProfileId === 'draft' ? saved.id ?? null : defaultProfileId;
        await api.setDefaultRoutingProfile(chosenDefault === 'system-balanced' ? null : chosenDefault);
        updatedProfiles = next.map((item) => ({ ...item, is_default: item.id === chosenDefault }));
        setDefaultProfileId(chosenDefault ?? 'system-balanced');
        setInitialDefaultProfileId(chosenDefault ?? 'system-balanced');
      }
      setProfiles(updatedProfiles); setSelectedId(saved.id ?? null); setDraft(updatedProfiles.find((item) => item.id === saved.id) ?? saved);
      const assignedId = !selectedId ? saved.id ?? '' : scopeProfileId;
      if (scope === 'project') await api.assignProjectRouting(projectName, assignedId);
      if (scope === 'session' && sessionAvailable && sessionId) {
        const sessionChoice = sessionProfileId === 'draft' ? saved.id ?? null : sessionProfileId;
        await api.assignSessionRouting(sessionId, sessionChoice === 'system-balanced' ? null : sessionChoice);
        setSessionProfileId(sessionChoice ?? 'system-balanced');
        setInitialSessionProfileId(sessionChoice ?? 'system-balanced');
      }
      if (scope === 'project') setInitialAssignment(assignedId);
      setValidation(null);
      onSaved();
    } catch (err) { setError(err instanceof ApiError ? `${err.code ? `${err.code}: ` : ''}${err.message}` : (err as Error).message); }
    finally { setBusy(false); }
  }

  async function validateSavedProfile() {
    if (!draft?.id || dirty) return;
    setBusy(true); setError('');
    try { setValidation(await api.validateRoutingProfile(draft.id)); }
    catch (err) { setError(err instanceof ApiError ? `${err.code ? `${err.code}: ` : ''}${err.message}` : (err as Error).message); }
    finally { setBusy(false); }
  }

  async function duplicate() {
    if (!draft?.id) return;
    setBusy(true); setError('');
    try { const copy = await api.duplicateRoutingProfile(draft.id); setProfiles((items) => [...items, copy]); setSelectedId(copy.id ?? null); setDraft(copy); }
    catch (err) { setError((err as Error).message); } finally { setBusy(false); }
  }

  async function remove() {
    if (!draft?.id || readOnly || !window.confirm(`Delete “${draft.name}”?`)) return;
    setBusy(true); setError('');
    try { await api.deleteRoutingProfile(draft.id); const next = profiles.filter((item) => item.id !== draft.id); setProfiles(next); selectProfile(next[0]?.id ?? null, next[0]); onSaved(); }
    catch (err) { setError((err as Error).message); } finally { setBusy(false); }
  }

  async function previewRoute() {
    if (!draft) return;
    setBusy(true); setError(''); setPreview(null);
    try {
      setPreview(await api.fetchRoutingPreview({
        role: previewRole,
        profile_draft: draft,
        message_override: previewModelLock || null,
        reasoning_override: previewReasoning || null,
        context: {
          task_type: previewTask || null,
          complexity: previewComplexity,
          requires_tools: previewTools,
          requires_vision: previewVision,
          requires_structured_output: previewStructured,
          requires_long_context: previewLong,
          required_capabilities: previewCapabilities.split(',').map((value) => value.trim()).filter(Boolean),
        },
      }));
    } catch (err) { const e = err as ApiError; setError(`${e.code ? `${e.code}: ` : ''}${e.message}`); }
    finally { setBusy(false); }
  }

  async function probeTools(providerId: string, modelId: string) {
    const key = `${providerId}:${modelId}`;
    setBusy(true); setError('');
    try {
      const result = await api.probeModel(providerId, modelId);
      setProbeResults((current) => ({ ...current, [key]: result.tool_support }));
    } catch (err) { setError((err as Error).message); }
    finally { setBusy(false); }
  }

  return <div className="routing-studio-backdrop" role="presentation" onMouseDown={(event) => { if (event.target === event.currentTarget) onClose(); }}>
    <section className="routing-studio" role="dialog" aria-modal="true" aria-label="Routing Studio">
      <header className="routing-studio__header"><div><span className="eyebrow">AURA · ROUTING STUDIO</span><h2>Model routing</h2></div><button className="icon-button" type="button" onClick={onClose} aria-label="Close Routing Studio">×</button></header>
      {error ? <div className="routing-error" role="alert">{error}</div> : null}
      <div className="routing-studio__layout">
        <aside className="routing-profile-list"><div className="routing-section-head"><h3>Profiles</h3><button type="button" onClick={() => selectProfile(null, newProfile())}>New</button></div>
          {profiles.map((profile) => <button key={profile.id} type="button" className={selectedId === profile.id ? 'is-active' : ''} onClick={() => selectProfile(profile.id ?? null)}><strong>{profile.name}</strong><small>{profile.id === 'system-balanced' ? 'Built-in · read-only' : profile.is_default ? 'Default profile' : `v${profile.version}`}</small></button>)}
        </aside>
        <main className="routing-profile-editor">
          {draft ? <>
            <div className="routing-section-head"><h3>{readOnly ? 'System Balanced' : 'Profile settings'}</h3><span>v{draft.version}</span></div>
            <fieldset disabled={readOnly}>
              <label>Profile name<input value={draft.name} onChange={(e) => update({ name: e.target.value })} /></label>
              <div className="routing-form-grid">
                <label>Privacy<select value={draft.global_privacy_policy} onChange={(e) => update({ global_privacy_policy: e.target.value as RoutingPrivacy })}>{PRIVACY.map((v) => <option key={v} value={v}>{v}</option>)}</select></label>
                <label>Fallback<select value={draft.global_fallback_policy} onChange={(e) => update({ global_fallback_policy: e.target.value as RoutingFallback })}>{FALLBACK.map((v) => <option key={v} value={v}>{v}</option>)}</select></label>
                <label>Cost<select value={draft.cost_preference} onChange={(e) => update({ cost_preference: e.target.value as 'low' | 'normal' })}><option value="low">Low</option><option value="normal">Normal</option></select></label>
                <label>Latency<select value={draft.latency_preference} onChange={(e) => update({ latency_preference: e.target.value as 'low' | 'normal' })}><option value="low">Low</option><option value="normal">Normal</option></select></label>
              </div>
              <label className="routing-checkbox"><input type="checkbox" checked={draft.is_default} onChange={(e) => update({ is_default: e.target.checked })} /> Use as default profile</label>
              <div className="routing-section-head"><h3>Profile validation</h3><button type="button" disabled={busy || !draft.id || dirty} onClick={() => void validateSavedProfile()}>Validate saved profile</button></div>
              {validation ? <div className={`routing-validation ${validation.valid ? 'is-valid' : 'has-errors'}`} role="status">
                <strong>{validation.valid ? 'Profile is valid' : 'Profile needs changes'}</strong>
                {validation.errors.map((item, index) => <p key={`${item}-${index}`}>{item}</p>)}
                {!validation.errors.length ? <p>Backend semantic validation passed.</p> : null}
              </div> : null}
              {profileErrors.length ? <div className="routing-validation has-errors" role="alert"><strong>Fix adaptive reasoning bounds before saving</strong>{profileErrors.map((item) => <p key={item}>{item}</p>)}</div> : null}
              <div className="routing-route-matrix"><div className="routing-section-head"><h3>Route matrix</h3><div><button type="button" onClick={() => setModelBrowser((value) => !value)}>Model browser</button> <button type="button" disabled={busy} onClick={() => void onRefreshModels()}>Refresh models</button></div></div>
                {ROLES.map((role) => { const route = { ...emptyRoute(), ...draft.routes[role], reasoning: { ...emptyRoute().reasoning, ...draft.routes[role]?.reasoning } }; const parts = route.model_override?.split(':'); const modelInfo = parts?.length === 2 ? catalog.providers.find((provider) => provider.id === parts[0])?.models.find((model) => model.id === parts[1]) : undefined; const modelProvider = parts?.length === 2 ? catalog.providers.find((provider) => provider.id === parts[0]) : undefined; const unavailableConfigured = Boolean(route.model_override && route.model_override !== 'auto' && (!modelInfo || !modelProvider?.available)); const boundsInvalid = Boolean(route.reasoning.policy === 'adaptive' && route.reasoning.min_effort && route.reasoning.max_effort && effortOrder.indexOf(route.reasoning.min_effort) > effortOrder.indexOf(route.reasoning.max_effort)); return <section className="routing-route-row" key={role}>
                  <strong>{role === 'root' ? 'Root / General' : role[0].toUpperCase() + role.slice(1)}</strong>
                  <label>Model<select value={route.model_override ?? (route.provider_override ? `provider:${route.provider_override}` : 'auto')} onChange={(e) => { const value = e.target.value; if (value.startsWith('provider:')) updateRoute(role, { model_override: null, provider_override: value.slice('provider:'.length) }); else updateRoute(role, { model_override: value === 'auto' ? null : value, provider_override: null }); }}><option value="auto">Auto</option>{route.provider_override ? <option value={`provider:${route.provider_override}`}>Provider default · {route.provider_override}</option> : null}{unavailableConfigured ? <option value={route.model_override!}>Configured · currently unavailable — {route.model_override}</option> : null}{catalog.providers.flatMap((provider) => provider.models.map((model) => <option key={`${provider.id}:${model.id}`} value={`${provider.id}:${model.id}`} disabled={!provider.available}>{provider.id}:{model.id}</option>))}</select>{unavailableConfigured ? <small>Configured · currently unavailable. This exact setting is preserved.</small> : null}</label>
                  {modelInfo?.reasoning_support === 'fixed_by_model' ? <label>Reasoning control<input value="Fixed by model" disabled /></label> : <><label>Reasoning<select value={route.reasoning.policy} onChange={(e) => updateRoute(role, { reasoning: { ...route.reasoning, policy: e.target.value as 'fixed' | 'adaptive' } })}><option value="fixed">Fixed</option><option value="adaptive">Adaptive</option></select>{modelInfo?.reasoning_support == null || modelInfo.reasoning_support === 'unknown' ? <small>Model reasoning control is unknown; profile policy is retained without claiming provider control.</small> : null}</label>
                  {route.reasoning.policy === 'fixed' ? <label>Effort<select value={route.reasoning.effort} onChange={(e) => updateRoute(role, { reasoning: { ...route.reasoning, effort: e.target.value as ReasoningEffort } })}>{EFFORTS.map((v) => <option key={v} value={v}>{v}</option>)}</select></label> : <div className="routing-range"><label>Min<select value={route.reasoning.min_effort ?? 'low'} onChange={(e) => updateRoute(role, { reasoning: { ...route.reasoning, min_effort: e.target.value as ReasoningEffort } })}>{EFFORTS.map((v) => <option key={v}>{v}</option>)}</select></label><label>Max<select value={route.reasoning.max_effort ?? 'high'} onChange={(e) => updateRoute(role, { reasoning: { ...route.reasoning, max_effort: e.target.value as ReasoningEffort } })}>{EFFORTS.map((v) => <option key={v}>{v}</option>)}</select></label>{boundsInvalid ? <small role="alert">Minimum effort cannot exceed maximum effort.</small> : null}</div>}</>}
                  <label>Privacy override<select value={route.privacy_policy ?? ''} onChange={(e) => updateRoute(role, { privacy_policy: (e.target.value || null) as RoutingPrivacy | null })}><option value="">Inherit global</option>{PRIVACY.map((v) => <option key={v} value={v}>{v}</option>)}</select></label>
                  <label>Fallback override<select value={route.fallback_policy ?? ''} onChange={(e) => updateRoute(role, { fallback_policy: (e.target.value || null) as RoutingFallback | null })}><option value="">Inherit global</option>{FALLBACK.map((v) => <option key={v} value={v}>{v}</option>)}</select></label>
                </section>; })}
              </div>
            </fieldset>
            {modelBrowser ? <div className="routing-model-browser"><h3>Available models</h3>{demoThread ? <p className="routing-note">Temporary model locks are only active in live chat. Start a live chat before locking a model.</p> : null}{catalog.providers.map((provider) => <section key={provider.id}><strong>{provider.label} · {provider.available ? 'available' : 'unavailable'} · {provider.privacy_status}</strong>{provider.models.map((model) => { const key = `${provider.id}:${model.id}`; return <div key={model.id}><span>{model.label} <small>({key})</small></span><small>reasoning {model.reasoning_support ?? 'unknown'} · tools {probeResults[key] ?? model.tool_support} · vision {model.vision_support == null ? 'unknown' : model.vision_support ? 'yes' : 'no'} · context {model.context_window ?? 'unknown'}</small><span className="routing-model-actions"><button type="button" disabled={!provider.available || demoThread} onClick={() => { onSetModelLock(key); }}>Lock</button><button type="button" disabled={!provider.available || busy} onClick={() => void probeTools(provider.id, model.id)}>Probe tools</button></span></div>; })}</section>)}</div> : null}
            <div className="routing-scope-editor"><div className="routing-section-head"><h3>Assignment</h3><span>Effective now: {effective?.profile.name ?? '—'} · {effective?.winning_scope ?? '—'}</span></div>
            <div className="routing-form-grid"><label>Scope<select value={scope} onChange={(e) => { const value = e.target.value as 'project' | 'session' | 'default'; setScope(value); if (value === 'default') setDefaultProfileId(draft.id ?? 'draft'); if (value === 'session') setSessionProfileId(draft.id ?? sessionProfileId); }}><option value="project">Project · {projectName}</option><option value="session" disabled={!sessionAvailable}>Session</option><option value="default">Default</option></select></label><label>Assigned profile<select value={scope === 'default' ? defaultProfileId : scope === 'session' ? sessionProfileId : scopeProfileId} onChange={(e) => { if (scope === 'default') setDefaultProfileId(e.target.value); else if (scope === 'session') setSessionProfileId(e.target.value); else setScopeProfileId(e.target.value); }}><option value="system-balanced">System Balanced</option>{profiles.filter((p) => p.id !== 'system-balanced').map((p) => <option key={p.id} value={p.id ?? ''}>{p.name}</option>)}{draft.id == null ? <option value="draft">{draft.name} · unsaved</option> : null}</select></label></div>
              {!sessionAvailable ? <p className="routing-note">Session routing becomes available after this live chat has started.</p> : null}
            </div>
            <div className="routing-preview"><div className="routing-section-head"><h3>Routing preview</h3><button type="button" disabled={busy} onClick={() => void previewRoute()}>Preview (no model call)</button></div>
              <div className="routing-form-grid"><label>Role<select value={previewRole} onChange={(e) => setPreviewRole(e.target.value)}>{ROLES.map((r) => <option key={r}>{r}</option>)}</select></label><label>Task type<select value={previewTask} onChange={(e) => setPreviewTask(e.target.value)}><option value="">General</option>{ROLES.slice(1).map((r) => <option key={r} value={r}>{r}</option>)}</select></label><label>Complexity<select value={previewComplexity} onChange={(e) => setPreviewComplexity(e.target.value as typeof previewComplexity)}><option>simple</option><option>medium</option><option>complex</option></select></label><label>Required capabilities<input value={previewCapabilities} onChange={(e) => setPreviewCapabilities(e.target.value)} placeholder="code, long_context" /></label><label>Exact model lock<select value={previewModelLock} onChange={(e) => setPreviewModelLock(e.target.value)}><option value="">None</option>{catalog.providers.flatMap((provider) => provider.models.map((model) => <option key={`${provider.id}:${model.id}`} value={`${provider.id}:${model.id}`} disabled={!provider.available}>{provider.id}:{model.id}</option>))}</select></label><label>Reasoning override<select value={previewReasoning} onChange={(e) => setPreviewReasoning(e.target.value as ReasoningEffort | '')}><option value="">Profile</option>{EFFORTS.map((value) => <option key={value}>{value}</option>)}</select></label></div>
              <div className="routing-checkboxes">{[['Tools', previewTools, setPreviewTools], ['Vision', previewVision, setPreviewVision], ['Structured output', previewStructured, setPreviewStructured], ['Long context', previewLong, setPreviewLong]].map(([label, value, setter]) => <label key={String(label)}><input type="checkbox" checked={value as boolean} onChange={(e) => (setter as (v: boolean) => void)(e.target.checked)} />{label as string}</label>)}</div>
              {preview ? <div className="routing-preview-card" aria-label="Routing preview result"><div className="routing-section-head"><strong>{preview.provider}:{preview.model}</strong><span>{preview.profile_name} · v{preview.profile_version}</span></div><dl><div><dt>Reason</dt><dd>{preview.reason}</dd></div><div><dt>Reasoning</dt><dd>{preview.reasoning_effort ?? 'Unknown / provider fixed'}</dd></div><div><dt>Scope</dt><dd>{preview.winning_scope}</dd></div><div><dt>Route</dt><dd>{preview.role} · {preview.task_route ?? 'general'}</dd></div><div><dt>Privacy / fallback</dt><dd>{preview.privacy} / {preview.fallback}</dd></div></dl>{preview.warnings.map((warning) => <p className="routing-note" key={warning}>{warning}</p>)}</div> : null}
            </div>
            <footer className="routing-studio__footer"><button type="button" className="secondary-button" disabled={busy || !draft.id} onClick={() => void duplicate()}>Duplicate</button><button type="button" className="secondary-button" disabled={busy || readOnly || !draft.id} onClick={() => void remove()}>Delete</button><span />{dirty ? <button type="button" className="secondary-button" disabled={busy} onClick={() => selectProfile(selectedId)}>Discard</button> : null}<button type="button" className="primary-button" disabled={busy || profileErrors.length > 0 || (readOnly && !assignmentDirty) || (!dirty && !assignmentDirty)} onClick={() => void save()}>{busy ? 'Saving…' : assignmentDirty && !dirty ? 'Save assignment' : 'Save changes'}</button></footer>
          </> : <p>Loading routing profiles…</p>}
        </main>
      </div>
    </section>
  </div>;
}
