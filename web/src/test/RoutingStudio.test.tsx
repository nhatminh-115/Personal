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
      else if (url.includes('/v1/routing/assignments')) value = { project_name: 'Project', routing_profile_id: null };
      else if (url.includes('/v1/routing/sessions/')) value = { session_id: 'session', routing_profile_id: null };
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
      body: JSON.stringify({ profile_id: 'custom-profile' }),
    })));
    expect(onSaved).toHaveBeenCalled();
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
    await waitFor(() => expect(global.fetch).toHaveBeenCalledWith('/v1/routing/assignments/Stateful%20Architecture?profile_id=created-profile', expect.objectContaining({ method: 'POST' })));
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

  it('offers cloud routing cancellation or settings changes without a fake continue action', () => {
    render(<RoutingConfirmationNotice proposal={{ provider: 'cloud', model: 'model-x' }} onCancel={vi.fn()} onOpenStudio={vi.fn()} onChangeRouting={vi.fn()} />);
    expect(screen.getByText(/Cloud routing requires confirmation/i)).toBeInTheDocument();
    expect(screen.getByText('Proposed:')).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Cancel' })).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Change routing' })).toBeInTheDocument();
    expect(screen.queryByRole('button', { name: /approve and continue/i })).not.toBeInTheDocument();
  });
});
