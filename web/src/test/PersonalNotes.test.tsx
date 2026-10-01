import { act, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import App from '../App';

const durableNote = {
  id: 'note-remote-1', title: 'Durable note', body: 'User-authored text stays exact.',
  tags: ['aura'], project_ids: ['aura'], pinned: true,
  created_at: '2026-09-30T12:00:00Z', updated_at: '2026-10-01T08:00:00Z',
};

describe('Personal Notes persistence', () => {
  beforeEach(() => {
    window.localStorage.clear();
    vi.restoreAllMocks();
  });

  it('hydrates notes from the backend and persists edits without changing authored text shape', async () => {
    const requests: Array<{ url: string; init?: RequestInit }> = [];
    global.fetch = vi.fn().mockImplementation((input: RequestInfo | URL, init?: RequestInit) => {
      const url = String(input);
      requests.push({ url, init });
      if (url === '/v1/notes' && !init?.method) {
        return Promise.resolve({ ok: true, json: () => Promise.resolve([durableNote]) } as Response);
      }
      if (url === '/v1/notes' && init?.method === 'POST') {
        return Promise.resolve({ ok: true, json: () => Promise.resolve({ ...JSON.parse(String(init.body)), ...durableNote }) } as Response);
      }
      if (url.endsWith('/v1/notes/note-remote-1') && init?.method === 'PUT') {
        return Promise.resolve({ ok: true, json: () => Promise.resolve({ ...durableNote, ...JSON.parse(String(init.body)), updated_at: '2026-10-01T09:00:00Z' }) } as Response);
      }
      if (url.includes('/v1/models')) return Promise.resolve({ ok: true, json: () => Promise.resolve({ providers: [] }) } as Response);
      if (url.includes('/v1/sessions')) return Promise.resolve({ ok: true, json: () => Promise.resolve([]) } as Response);
      if (url.includes('/v1/memory')) return Promise.resolve({ ok: true, json: () => Promise.resolve([]) } as Response);
      return Promise.resolve({ ok: true, json: () => Promise.resolve({}) } as Response);
    });

    await act(async () => { render(<App />); });
    fireEvent.click(screen.getByRole('button', { name: 'Notes' }));
    expect(await screen.findByDisplayValue('Durable note')).toBeInTheDocument();
    expect(screen.getByDisplayValue('User-authored text stays exact.')).toBeInTheDocument();

    fireEvent.change(screen.getByDisplayValue('Durable note'), { target: { value: 'Durable note edited' } });
    await waitFor(() => expect(requests.some(({ url, init }) =>
      url.endsWith('/v1/notes/note-remote-1') && init?.method === 'PUT'
      && String(init.body).includes('Durable note edited'))).toBe(true), { timeout: 2500 });

    expect(requests.some(({ url }) => url === '/v1/notes')).toBe(true);
  });
});
