import { act, fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import App from '../App';
import { RoutingConfirmationNotice } from '../components/routing/RoutingConfirmationNotice';
import { RoutingStudio } from '../components/routing/RoutingStudio';
import type { RoutingProfile } from '../types';

const profile: RoutingProfile = {
  id: 'system-balanced', name: 'System Balanced', version: 1, is_active: true, is_default: false,
  global_privacy_policy: 'public', global_fallback_policy: 'cloud_allowed', cost_preference: 'normal', latency_preference: 'normal',
  routes: { root: { reasoning: { policy: 'adaptive', effort: 'low', min_effort: 'low', max_effort: 'medium' } } },
};
const customProfile: RoutingProfile = {
  ...profile,
  id: 'custom-profile', name: 'Custom profile', version: 3, is_default: true,
  routes: { root: { model_override: 'offline:kept-model', reasoning: { policy: 'adaptive', effort: 'medium', min_effort: 'low', max_effort: 'low' } } },
};

describe('Routing Studio v2', () => {
  beforeEach(() => {
    window.localStorage.clear();
    vi.restoreAllMocks();
    global.fetch = vi.fn().mockImplementation((input: RequestInfo | URL, init?: RequestInit) => {
      const url = String(input);
      let value: any = {};
      if (url.includes('/v1/models')) value = { providers: [{ id: 'local', label: 'Local', kind: 'local', available: true, base_url: 'local', privacy_status: 'local', models: [{ id: 'installed-model', label: 'Installed model', capabilities: [], tool_support: 'unknown', reasoning_support: 'unknown' }] }] };
      else if (url.endsWith('/duplicate')) value = { ...profile, id: 'copy-profile', name: 'System Balanced (Copy)' };
      else if (url.endsWith('/validate')) value = { valid: true, profile_id: 'custom-profile', errors: [] };
      else if (url.endsWith('/v1/routing/profiles') && init?.method === 'POST') value = { ...profile, ...JSON.parse(String(init.body)), id: 'created-profile' };
      else if (url.includes('/v1/routing/profiles')) value = [profile, customProfile];
      else if (url.includes('/v1/routing/effective')) value = { profile, winning_scope: 'system' };
      else if (url.includes('/v1/routing/assignments')) value = { project_name: 'Project', routing_profile_id: null, revision: 0 };
      else if (url.includes('/v1/routing/sessions/')) value = { session_id: 'session', routing_profile_id: null, revision: 1 };
      else if (url.endsWith('/v1/routing/default')) value = { status: 'success', routing_profile_id: null };
      else if (url.endsWith('/v1/routing/preview')) value = { provider: 'local', model: 'installed-model', reason: 'profile_match', reasoning_effort: 'medium', profile_id: 'system-balanced', profile_name: 'System Balanced', profile_version: 1, winning_scope: 'draft', privacy: 'public', fallback: 'cloud_allowed', role: 'root', task_route: 'root', warnings: [] };
      else if (url.includes('/v1/sessions')) value = [];
      else if (url.includes('/v1/memory')) value = [];
      return Promise.resolve({ ok: true, json: () => Promise.resolve(value) } as Response);
    });
  });

  async function openProject() {
    await act(async () => { render(<App />); });
    const projectButton = screen.getAllByText(/Stateful Architecture/i)[0].closest('button')!;
    await act(async () => { fireEvent.click(projectButton); });
    await waitFor(() => expect(screen.getByText(/System Balanced · system/i)).toBeInTheDocument());
  }

  it('shows live effective routing and starts without a model lock', async () => {
    await openProject();
    fireEvent.click(screen.getByText(/System Balanced · system/i));
    const modelSelect = screen.getByLabelText('Temporary exact model lock') as HTMLSelectElement;
    expect(modelSelect.value).toBe('');
    expect(screen.queryByText(/Model C/i)).not.toBeInTheDocument();
    expect(screen.getByLabelText('Temporary reasoning')).toBeInTheDocument();
  });

  it('opens Routing Studio as an overlay and uses catalog model identity', async () => {
    await openProject();
    fireEvent.click(screen.getByText(/System Balanced · system/i));
    fireEvent.click(screen.getByRole('button', { name: 'Open Routing Studio' }));
    expect(await screen.findByRole('dialog', { name: 'Routing Studio' })).toBeInTheDocument();
    fireEvent.click(screen.getByRole('button', { name: 'Model browser' }));
    await waitFor(() => expect(screen.getByText('Installed model')).toBeInTheDocument());
    expect(screen.queryByText('Routing Studio', { selector: '.workspace-tab' })).not.toBeInTheDocument();
  });

  it('disables temporary overrides on demo threads while keeping profile controls available', async () => {
    await openProject();
    fireEvent.click(screen.getByText(/System Balanced · system/i));
    expect(screen.getByLabelText('Temporary exact model lock')).toBeDisabled();
    expect(screen.getByLabelText('Temporary reasoning')).toBeDisabled();
    expect(screen.getByText(/Temporary controls apply only to live chats/i)).toBeInTheDocument();
    fireEvent.click(screen.getByRole('button', { name: 'Open Routing Studio' }));
    expect(await screen.findByRole('dialog', { name: 'Routing Studio' })).toBeInTheDocument();
  });

  it('preserves an unavailable exact model configuration and guards invalid adaptive bounds', async () => {
    await openProject();
    fireEvent.click(screen.getByText(/System Balanced · system/i));
    fireEvent.click(screen.getByRole('button', { name: 'Open Routing Studio' }));
    fireEvent.click(await screen.findByRole('button', { name: /Custom profile/i }));
    expect(screen.getByText(/Configured · currently unavailable\. This exact setting is preserved/i)).toBeInTheDocument();
    const minSelect = screen.getAllByLabelText('Min')[0];
    fireEvent.change(minSelect, { target: { value: 'high' } });
    expect(screen.getByText(/Minimum effort cannot exceed maximum effort/i)).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Save changes' })).toBeDisabled();
  });

  it('calls backend profile validation and renders a structured validation result', async () => {
    await openProject();
    fireEvent.click(screen.getByText(/System Balanced · system/i));
    fireEvent.click(screen.getByRole('button', { name: 'Open Routing Studio' }));
    fireEvent.click(await screen.findByRole('button', { name: /Custom profile/i }));
    fireEvent.click(screen.getByRole('button', { name: 'Validate saved profile' }));
    expect(await screen.findByText('Profile is valid')).toBeInTheDocument();
    expect(screen.getByText('Backend semantic validation passed.')).toBeInTheDocument();
  });

  it('requires profile edits to be saved or discarded before duplication', async () => {
    await openProject();
    fireEvent.click(screen.getByText(/System Balanced · system/i));
    fireEvent.click(screen.getByRole('button', { name: 'Open Routing Studio' }));
    fireEvent.click(await screen.findByRole('button', { name: /Custom profile/i }));

    fireEvent.change(screen.getByLabelText('Profile name'), { target: { value: 'Edited profile' } });

    expect(screen.getByRole('button', { name: 'Duplicate' })).toBeDisabled();
    expect(screen.getByRole('button', { name: 'Duplicate' })).toHaveAttribute(
      'title', 'Save or discard profile edits before duplicating.',
    );
  });

  it('deletes a dirty profile with one explicit confirmation and clears the discarded draft', async () => {
    const confirm = vi.spyOn(window, 'confirm').mockReturnValue(true);
    await openProject();
    fireEvent.click(screen.getByText(/System Balanced · system/i));
    fireEvent.click(screen.getByRole('button', { name: 'Open Routing Studio' }));
    fireEvent.click(await screen.findByRole('button', { name: /Custom profile/i }));
    fireEvent.change(screen.getByLabelText('Profile name'), { target: { value: 'Unsaved rename' } });

    fireEvent.click(screen.getByRole('button', { name: 'Delete' }));

    expect(confirm).toHaveBeenCalledTimes(1);
    expect(confirm).toHaveBeenCalledWith(expect.stringContaining('Unsaved profile edits will also be discarded.'));
    await waitFor(() => expect(global.fetch).toHaveBeenCalledWith(
      '/v1/routing/profiles/custom-profile?expected_version=3',
      expect.objectContaining({ method: 'DELETE' }),
    ));
    expect(await screen.findByLabelText('Profile name')).toHaveValue('System Balanced');
    expect(screen.queryByRole('button', { name: /Custom profile/i })).not.toBeInTheDocument();
  });

  it('can reset the custom default to System Balanced transactionally', async () => {
    await openProject();
    fireEvent.click(screen.getByText(/System Balanced · system/i));
    fireEvent.click(screen.getByRole('button', { name: 'Open Routing Studio' }));
    await screen.findByRole('dialog', { name: 'Routing Studio' });
    fireEvent.change(screen.getByLabelText('Scope'), { target: { value: 'default' } });
    fireEvent.change(screen.getByLabelText('Assigned profile'), { target: { value: 'system-balanced' } });
    fireEvent.click(screen.getByRole('button', { name: 'Save assignment' }));
    await waitFor(() => expect(global.fetch).toHaveBeenCalledWith('/v1/routing/default', expect.objectContaining({ method: 'PUT', body: JSON.stringify({ profile_id: null }) })));
  });

  it('shows the saved default assignment when switching scope instead of replacing it with the open profile', async () => {
    await openProject();
    fireEvent.click(screen.getByText(/System Balanced · system/i));
    fireEvent.click(screen.getByRole('button', { name: 'Open Routing Studio' }));
    await screen.findByRole('dialog', { name: 'Routing Studio' });

    const scopeSelect = screen.getByLabelText('Scope');
    const assignmentSelect = screen.getByLabelText('Assigned profile') as HTMLSelectElement;
    expect(assignmentSelect).toHaveValue('system-balanced');

    fireEvent.change(scopeSelect, { target: { value: 'default' } });

    expect(assignmentSelect).toHaveValue('custom-profile');
    expect(screen.getByRole('button', { name: 'Save changes' })).toBeDisabled();
  });

  it('preserves the loaded session assignment when switching from another profile', async () => {
    render(<RoutingStudio
      open projectName="Project" sessionId="live-session" sessionAvailable demoThread={false}
      effective={{ profile: customProfile, winning_scope: 'project' }}
      catalog={{ providers: [] }}
      onClose={vi.fn()} onSaved={vi.fn()} onSetModelLock={vi.fn()}
      onRefreshModels={vi.fn().mockResolvedValue(undefined)}
    />);

    await screen.findByRole('dialog', { name: 'Routing Studio' });
    const assignmentSelect = screen.getByLabelText('Assigned profile') as HTMLSelectElement;
    fireEvent.change(screen.getByLabelText('Scope'), { target: { value: 'session' } });

    expect(assignmentSelect).toHaveValue('system-balanced');
    expect(screen.getByRole('button', { name: 'Save changes' })).toBeDisabled();
  });

  it('keeps session assignment unavailable before a live session exists', async () => {
    const onClose = vi.fn();
    render(<RoutingStudio
      open
      projectName="Project"
      sessionId="local-only-session"
      sessionAvailable={false}
      demoThread={false}
      effective={{ profile: customProfile, winning_scope: 'project' }}
      catalog={{ providers: [] }}
      onClose={onClose}
      onSaved={vi.fn()}
      onSetModelLock={vi.fn()}
      onRefreshModels={vi.fn().mockResolvedValue(undefined)}
    />);

    await screen.findByRole('dialog', { name: 'Routing Studio' });
    expect(within(screen.getByLabelText('Scope')).getByRole('option', { name: 'Session' })).toBeDisabled();
    expect(screen.getByText('Session routing becomes available after this live chat has started.')).toBeInTheDocument();
    expect(global.fetch).not.toHaveBeenCalledWith(expect.stringContaining('/v1/routing/sessions/local-only-session'), expect.objectContaining({ method: 'PUT' }));
  });

  it('persists a session assignment only when a live session is available', async () => {
    const onSaved = vi.fn();
    render(<RoutingStudio
      open
      projectName="Project"
      sessionId="live-session"
      sessionAvailable
      demoThread={false}
      effective={{ profile: customProfile, winning_scope: 'project' }}
      catalog={{ providers: [] }}
      onClose={vi.fn()}
      onSaved={onSaved}
      onSetModelLock={vi.fn()}
      onRefreshModels={vi.fn().mockResolvedValue(undefined)}
    />);

    await screen.findByRole('dialog', { name: 'Routing Studio' });
    fireEvent.change(screen.getByLabelText('Scope'), { target: { value: 'session' } });
    fireEvent.change(screen.getByLabelText('Assigned profile'), { target: { value: 'custom-profile' } });
    fireEvent.click(screen.getByRole('button', { name: 'Save assignment' }));

    await waitFor(() => expect(global.fetch).toHaveBeenCalledWith('/v1/routing/sessions/live-session', expect.objectContaining({
      method: 'PUT',
      body: JSON.stringify({ profile_id: 'custom-profile', expected_revision: 1 }),
    })));
    expect(onSaved).toHaveBeenCalled();
  });

  it('resets project assignment to System Balanced so routing inherits', async () => {
    const defaultFetch = global.fetch as ReturnType<typeof vi.fn>;
    const calls: Array<{ url: string; init?: RequestInit }> = [];
    global.fetch = vi.fn().mockImplementation((input: RequestInfo | URL, init?: RequestInit) => {
      const url = String(input);
      calls.push({ url, init });
      if (url === '/v1/routing/assignments/Project') {
        return Promise.resolve({ ok: true, json: () => Promise.resolve({ project_name: 'Project', routing_profile_id: 'custom-profile', revision: 1 }) } as Response);
      }
      return defaultFetch(input, init);
    });

    const onSaved = vi.fn();
    render(<RoutingStudio
      open projectName="Project" sessionAvailable={false} demoThread={false}
      effective={{ profile: customProfile, winning_scope: 'project' }}
      catalog={{ providers: [] }}
      onClose={vi.fn()} onSaved={onSaved} onSetModelLock={vi.fn()}
      onRefreshModels={vi.fn().mockResolvedValue(undefined)}
    />);

    await screen.findByRole('dialog', { name: 'Routing Studio' });
    fireEvent.change(screen.getByLabelText('Assigned profile'), { target: { value: 'system-balanced' } });
    fireEvent.click(screen.getByRole('button', { name: 'Save assignment' }));

    await waitFor(() => expect(calls.some(({ url, init }) =>
      url === '/v1/routing/assignments/Project?profile_id=system-balanced&expected_revision=1' && init?.method === 'POST',
    )).toBe(true));
    expect(onSaved).toHaveBeenCalled();
  });

  it('resets a live session assignment to inheritance with a null profile', async () => {
    const defaultFetch = global.fetch as ReturnType<typeof vi.fn>;
    const calls: Array<{ url: string; init?: RequestInit }> = [];
    global.fetch = vi.fn().mockImplementation((input: RequestInfo | URL, init?: RequestInit) => {
      const url = String(input);
      calls.push({ url, init });
      if (url === '/v1/routing/sessions/live-session' && !init?.method) {
        return Promise.resolve({ ok: true, json: () => Promise.resolve({ session_id: 'live-session', routing_profile_id: 'custom-profile', revision: 2 }) } as Response);
      }
      return defaultFetch(input, init);
    });

    const onSaved = vi.fn();
    render(<RoutingStudio
      open projectName="Project" sessionId="live-session" sessionAvailable demoThread={false}
      effective={{ profile: customProfile, winning_scope: 'session' }}
      catalog={{ providers: [] }}
      onClose={vi.fn()} onSaved={onSaved} onSetModelLock={vi.fn()}
      onRefreshModels={vi.fn().mockResolvedValue(undefined)}
    />);

    await screen.findByRole('dialog', { name: 'Routing Studio' });
    fireEvent.change(screen.getByLabelText('Scope'), { target: { value: 'session' } });
    fireEvent.change(screen.getByLabelText('Assigned profile'), { target: { value: 'system-balanced' } });
    fireEvent.click(screen.getByRole('button', { name: 'Save assignment' }));

    await waitFor(() => expect(calls.some(({ url, init }) =>
      url === '/v1/routing/sessions/live-session'
      && init?.method === 'PUT'
      && init.body === JSON.stringify({ profile_id: null, expected_revision: 2 }),
    )).toBe(true));
    expect(onSaved).toHaveBeenCalled();
  });

  it('shows fixed-by-model controls truthfully and keeps unknown reasoning explicit', async () => {
    const fixedProfile: RoutingProfile = {
      ...customProfile,
      id: 'fixed-profile',
      name: 'Fixed model profile',
      routes: {
        root: {
          model_override: 'local:fixed-model',
          reasoning: { policy: 'fixed', effort: 'medium', min_effort: 'low', max_effort: 'high' },
        },
      },
    };
    const defaultFetch = global.fetch as ReturnType<typeof vi.fn>;
    global.fetch = vi.fn().mockImplementation((input: RequestInfo | URL, init?: RequestInit) => {
      const url = String(input);
      if (url === '/v1/routing/profiles') {
        return Promise.resolve({ ok: true, json: () => Promise.resolve([fixedProfile]) } as Response);
      }
      return defaultFetch(input, init);
    });
    render(<RoutingStudio
      open projectName="Project" sessionAvailable={false} demoThread={false}
      effective={{ profile: fixedProfile, winning_scope: 'project' }}
      catalog={{ providers: [{
        id: 'local', label: 'Local', kind: 'local', available: true, base_url: 'local', privacy_status: 'local',
        models: [
          { id: 'fixed-model', label: 'Fixed model', capabilities: [], tool_support: 'unknown', reasoning_support: 'fixed_by_model' },
          { id: 'unknown-model', label: 'Unknown model', capabilities: [], tool_support: 'unknown', reasoning_support: 'unknown' },
        ],
      }] }}
      onClose={vi.fn()} onSaved={vi.fn()} onSetModelLock={vi.fn()}
      onRefreshModels={vi.fn().mockResolvedValue(undefined)}
    />);

    await screen.findByRole('dialog', { name: 'Routing Studio' });
    expect(screen.getByLabelText('Reasoning control')).toHaveValue('Fixed by model');
    expect(screen.queryByLabelText('Reasoning')).not.toBeInTheDocument();

    fireEvent.change(screen.getAllByLabelText('Model')[0], { target: { value: 'local:unknown-model' } });
    const unknownReasoningNote = screen.getAllByText(/reasoning control is unknown/i)[0];
    expect(unknownReasoningNote.closest('label')?.querySelector('select')).not.toBeNull();
  });

  it('renders preview fields instead of raw JSON', async () => {
    await openProject();
    fireEvent.click(screen.getByText(/System Balanced · system/i));
    fireEvent.click(screen.getByRole('button', { name: 'Open Routing Studio' }));
    fireEvent.click(await screen.findByRole('button', { name: 'Preview (no model call)' }));
    expect(await screen.findByLabelText('Routing preview result')).toBeInTheDocument();
    expect(within(screen.getByLabelText('Routing preview result')).getByText('local:installed-model')).toBeInTheDocument();
    expect(screen.queryByText(/"provider"\s*:/)).not.toBeInTheDocument();
  });

  it('shows actionable guidance for structured routing preview errors without exposing raw details', async () => {
    await openProject();
    fireEvent.click(screen.getByText(/System Balanced · system/i));
    fireEvent.click(screen.getByRole('button', { name: 'Open Routing Studio' }));
    await screen.findByRole('dialog', { name: 'Routing Studio' });

    const normalFetch = global.fetch as ReturnType<typeof vi.fn>;
    global.fetch = vi.fn().mockImplementation((input: RequestInfo | URL, init?: RequestInit) => {
      if (String(input).endsWith('/v1/routing/preview')) {
        return Promise.resolve({
          ok: false,
          status: 403,
          text: () => Promise.resolve(JSON.stringify({
            error: 'PrivacyBoundaryViolation',
            message: 'No local model is eligible.',
            details: { raw: 'private router internals' },
          })),
        } as Response);
      }
      return normalFetch(input, init);
    });

    fireEvent.click(screen.getByRole('button', { name: 'Preview (no model call)' }));

    const alert = await screen.findByRole('alert');
    expect(alert).toHaveTextContent('No local model is eligible.');
    expect(alert).toHaveTextContent('Review the profile scope and select a route that meets its privacy boundary.');
    expect(alert).not.toHaveTextContent('PrivacyBoundaryViolation');
    expect(alert).not.toHaveTextContent('private router internals');
  });

  it('keeps System Balanced read-only, duplicable, and protected from deletion', async () => {
    await openProject();
    fireEvent.click(screen.getByText(/System Balanced · system/i));
    fireEvent.click(screen.getByRole('button', { name: 'Open Routing Studio' }));
    const nameField = await screen.findByLabelText('Profile name');
    expect(nameField).toBeDisabled();
    expect(screen.getByRole('button', { name: 'Delete' })).toBeDisabled();
    expect(screen.getByRole('button', { name: 'Duplicate' })).toBeEnabled();
  });

  it('creates a profile draft and assigns the saved profile to the project', async () => {
    await openProject();
    fireEvent.click(screen.getByText(/System Balanced · system/i));
    fireEvent.click(screen.getByRole('button', { name: 'Open Routing Studio' }));
    await screen.findByRole('dialog', { name: 'Routing Studio' });
    fireEvent.click(screen.getByRole('button', { name: 'New' }));
    fireEvent.change(screen.getByLabelText('Profile name'), { target: { value: 'Project profile' } });
    fireEvent.click(screen.getByRole('button', { name: 'Save changes' }));
    await waitFor(() => expect(global.fetch).toHaveBeenCalledWith('/v1/routing/profiles', expect.objectContaining({ method: 'POST' })));
    await waitFor(() => expect(global.fetch).toHaveBeenCalledWith('/v1/routing/assignments/Stateful%20Architecture?profile_id=created-profile&expected_revision=0', expect.objectContaining({ method: 'POST' })));
  });

  it('updates a saved profile through its backend resource and refreshes the draft', async () => {
    await openProject();
    fireEvent.click(screen.getByText(/System Balanced · system/i));
    fireEvent.click(screen.getByRole('button', { name: 'Open Routing Studio' }));
    fireEvent.click(await screen.findByRole('button', { name: /Custom profile/i }));

    const normalFetch = global.fetch as ReturnType<typeof vi.fn>;
    let updatedPayload: Record<string, unknown> | null = null;
    global.fetch = vi.fn().mockImplementation((input: RequestInfo | URL, init?: RequestInit) => {
      const url = String(input);
      if (url.endsWith('/v1/routing/profiles/custom-profile') && init?.method === 'PUT') {
        updatedPayload = JSON.parse(String(init.body));
        return Promise.resolve({ ok: true, json: () => Promise.resolve({ ...customProfile, ...updatedPayload, version: 4 }) } as Response);
      }
      return normalFetch(input, init);
    });

    fireEvent.change(screen.getByLabelText('Profile name'), { target: { value: 'Updated profile' } });
    fireEvent.click(screen.getByRole('button', { name: 'Save changes' }));

    await waitFor(() => expect(updatedPayload).toEqual(expect.objectContaining({ id: 'custom-profile', name: 'Updated profile' })));
    expect(await screen.findByLabelText('Profile name')).toHaveValue('Updated profile');
  });

  it('shows an actionable message when a stale profile draft conflicts', async () => {
    await openProject();
    fireEvent.click(screen.getByText(/System Balanced · system/i));
    fireEvent.click(screen.getByRole('button', { name: 'Open Routing Studio' }));
    fireEvent.click(await screen.findByRole('button', { name: /Custom profile/i }));

    const normalFetch = global.fetch as ReturnType<typeof vi.fn>;
    global.fetch = vi.fn().mockImplementation((input: RequestInfo | URL, init?: RequestInit) => {
      if (String(input).endsWith('/v1/routing/profiles/custom-profile') && init?.method === 'PUT') {
        return Promise.resolve({
          ok: false,
          status: 409,
          text: () => Promise.resolve(JSON.stringify({
            detail: {
              code: 'RoutingProfileVersionConflict',
              message: 'Routing profile changed since it was loaded.',
              current_version: 4,
            },
          })),
        } as Response);
      }
      return normalFetch(input, init);
    });

    fireEvent.change(screen.getByLabelText('Profile name'), { target: { value: 'Stale edit' } });
    fireEvent.click(screen.getByRole('button', { name: 'Save changes' }));

    const alert = await screen.findByRole('alert');
    expect(alert).toHaveTextContent('This routing profile changed elsewhere.');
    expect(alert).toHaveTextContent('Reload the profile in Routing Studio');
    expect(alert).not.toHaveTextContent('current_version');
    expect(screen.getByLabelText('Profile name')).toHaveValue('Stale edit');
  });

  it('keeps a routing profile in place when its confirmed delete is stale', async () => {
    vi.spyOn(window, 'confirm').mockReturnValue(true);
    await openProject();
    fireEvent.click(screen.getByText(/System Balanced · system/i));
    fireEvent.click(screen.getByRole('button', { name: 'Open Routing Studio' }));
    fireEvent.click(await screen.findByRole('button', { name: /Custom profile/i }));

    const normalFetch = global.fetch as ReturnType<typeof vi.fn>;
    global.fetch = vi.fn().mockImplementation((input: RequestInfo | URL, init?: RequestInit) => {
      if (String(input).includes('/v1/routing/profiles/custom-profile?expected_version=3') && init?.method === 'DELETE') {
        return Promise.resolve({
          ok: false,
          status: 409,
          text: () => Promise.resolve(JSON.stringify({
            detail: {
              code: 'RoutingProfileVersionConflict',
              message: 'Routing profile changed since it was loaded.',
              current_version: 4,
            },
          })),
        } as Response);
      }
      return normalFetch(input, init);
    });

    fireEvent.click(screen.getByRole('button', { name: 'Delete' }));

    const alert = await screen.findByRole('alert');
    expect(alert).toHaveTextContent('This routing profile changed elsewhere.');
    expect(screen.getByRole('button', { name: /Custom profile/i })).toBeInTheDocument();
    expect(screen.getByLabelText('Profile name')).toHaveValue('Custom profile');
  });

  it('duplicates a saved profile and selects the persisted copy', async () => {
    await openProject();
    fireEvent.click(screen.getByText(/System Balanced · system/i));
    fireEvent.click(screen.getByRole('button', { name: 'Open Routing Studio' }));
    fireEvent.click(await screen.findByRole('button', { name: /Custom profile/i }));

    const normalFetch = global.fetch as ReturnType<typeof vi.fn>;
    let duplicateRequested = false;
    global.fetch = vi.fn().mockImplementation((input: RequestInfo | URL, init?: RequestInit) => {
      const url = String(input);
      if (url.endsWith('/v1/routing/profiles/custom-profile/duplicate') && init?.method === 'POST') {
        duplicateRequested = true;
        return Promise.resolve({ ok: true, json: () => Promise.resolve({ ...customProfile, id: 'copy-profile', name: 'Custom profile (copy)', is_default: false }) } as Response);
      }
      return normalFetch(input, init);
    });

    fireEvent.click(screen.getByRole('button', { name: 'Duplicate' }));

    await waitFor(() => expect(duplicateRequested).toBe(true));
    expect(await screen.findByLabelText('Profile name')).toHaveValue('Custom profile (copy)');
  });

  it('asks before switching away from a dirty profile draft', async () => {
    const confirm = vi.spyOn(window, 'confirm').mockReturnValue(false);
    await openProject();
    fireEvent.click(screen.getByText(/System Balanced · system/i));
    fireEvent.click(screen.getByRole('button', { name: 'Open Routing Studio' }));
    fireEvent.click(await screen.findByRole('button', { name: /Custom profile/i }));
    fireEvent.change(screen.getByLabelText('Profile name'), { target: { value: 'Edited draft' } });
    fireEvent.click(screen.getByRole('button', { name: /System Balanced.*Built-in/i }));
    expect(confirm).toHaveBeenCalledWith('Discard unsaved routing profile changes?');
    expect(screen.getByLabelText('Profile name')).toHaveValue('Edited draft');
  });

  it('discards profile and assignment drafts directly and restores their saved values', async () => {
    const confirm = vi.spyOn(window, 'confirm').mockReturnValue(false);
    await openProject();
    fireEvent.click(screen.getByText(/System Balanced · system/i));
    fireEvent.click(screen.getByRole('button', { name: 'Open Routing Studio' }));
    await screen.findByRole('dialog', { name: 'Routing Studio' });
    fireEvent.click(await screen.findByRole('button', { name: /Custom profile/i }));
    fireEvent.change(screen.getByLabelText('Profile name'), { target: { value: 'Unsaved rename' } });
    fireEvent.change(screen.getByLabelText('Assigned profile'), { target: { value: 'custom-profile' } });

    fireEvent.click(screen.getByRole('button', { name: 'Discard' }));

    expect(confirm).not.toHaveBeenCalled();
    expect(screen.getByLabelText('Profile name')).toHaveValue('Custom profile');
    expect(screen.getByLabelText('Assigned profile')).toHaveValue('system-balanced');
    expect(screen.getByRole('button', { name: 'Save changes' })).toBeDisabled();
  });

  it('asks before closing Routing Studio with unsaved changes', async () => {
    const confirm = vi.spyOn(window, 'confirm').mockReturnValue(false);
    await openProject();
    fireEvent.click(screen.getByText(/System Balanced · system/i));
    fireEvent.click(screen.getByRole('button', { name: 'Open Routing Studio' }));
    await screen.findByRole('dialog', { name: 'Routing Studio' });
    fireEvent.click(await screen.findByRole('button', { name: /Custom profile/i }));
    fireEvent.change(screen.getByLabelText('Profile name'), { target: { value: 'Unsaved rename' } });

    fireEvent.click(screen.getByRole('button', { name: 'Close Routing Studio' }));
    expect(confirm).toHaveBeenCalledWith('Discard unsaved routing profile changes?');
    expect(screen.getByRole('dialog', { name: 'Routing Studio' })).toBeInTheDocument();

    confirm.mockReturnValue(true);
    fireEvent.click(screen.getByRole('button', { name: 'Close Routing Studio' }));
    expect(screen.queryByRole('dialog', { name: 'Routing Studio' })).not.toBeInTheDocument();
  });

  it('submits approve and reject decisions for a durable cloud routing confirmation', () => {
    const onConfirm = vi.fn();
    const onCancel = vi.fn();
    render(<RoutingConfirmationNotice proposal={{ provider: 'cloud', model: 'model-x' }} onConfirm={onConfirm} onCancel={onCancel} />);
    expect(screen.getByText(/Cloud routing requires confirmation/i)).toBeInTheDocument();
    expect(screen.getByText(/cloud:model-x/i)).toBeInTheDocument();
    fireEvent.click(screen.getByRole('button', { name: 'Approve and continue' }));
    fireEvent.click(screen.getByRole('button', { name: 'Cancel run' }));
    expect(onConfirm).toHaveBeenCalledOnce();
    expect(onCancel).toHaveBeenCalledOnce();
  });
});
