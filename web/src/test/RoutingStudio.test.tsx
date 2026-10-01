import { act, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import App from '../App';

const profile = {
  id: 'system-balanced', name: 'System Balanced', version: 1, is_active: true, is_default: false,
  global_privacy_policy: 'public', global_fallback_policy: 'cloud_allowed', cost_preference: 'normal', latency_preference: 'normal',
  routes: { root: { reasoning: { policy: 'adaptive', effort: 'low', min_effort: 'low', max_effort: 'medium' } } },
};

describe('Routing Studio v2', () => {
  beforeEach(() => {
    window.localStorage.clear();
    vi.restoreAllMocks();
    global.fetch = vi.fn().mockImplementation((input: RequestInfo | URL) => {
      const url = String(input);
      let value: any = {};
      if (url.includes('/v1/models')) value = { providers: [{ id: 'local', label: 'Local', kind: 'local', available: true, base_url: 'local', privacy_status: 'local', models: [{ id: 'installed-model', label: 'Installed model', capabilities: [], tool_support: 'unknown', reasoning_support: 'unknown' }] }] };
      else if (url.includes('/v1/routing/profiles')) value = [profile];
      else if (url.includes('/v1/routing/effective')) value = { profile, winning_scope: 'system' };
      else if (url.includes('/v1/routing/assignments')) value = { project_name: 'Project', routing_profile_id: null };
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
});
