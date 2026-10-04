import { act, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import App from '../App';

describe('Persistent personal workspace Notes', () => {
  beforeEach(() => {
    window.localStorage.clear();
    vi.restoreAllMocks();
    global.fetch = vi.fn().mockImplementation((input: RequestInfo | URL, init?: RequestInit) => {
      const url = String(input);
      if (url.endsWith('/v1/models')) return Promise.resolve({ ok: true, json: () => Promise.resolve({ providers: [] }) } as Response);
      if (url.includes('/v1/sessions?')) return Promise.resolve({ ok: true, json: () => Promise.resolve([]) } as Response);
      if (url.endsWith('/v1/memory')) return Promise.resolve({ ok: true, json: () => Promise.resolve([]) } as Response);
      if (url.endsWith('/v1/workspace/notes') && init?.method === 'POST') {
        const body = JSON.parse(String(init.body));
        return Promise.resolve({ ok: true, json: () => Promise.resolve({
          id: 'personal-note-1', ...body, created_at: '2026-10-02T00:00:00Z', updated_at: '2026-10-02T00:00:00Z',
        }) } as Response);
      }
      if (url.endsWith('/v1/workspace/notes/personal-note-1') && init?.method === 'PUT') {
        const body = JSON.parse(String(init.body));
        return Promise.resolve({ ok: true, json: () => Promise.resolve({
          id: 'personal-note-1', ...body, created_at: '2026-10-02T00:00:00Z', updated_at: '2026-10-02T00:01:00Z',
        }) } as Response);
      }
      if (url.endsWith('/v1/workspace/notes') || url.startsWith('/v1/workspace/notes?')) return Promise.resolve({ ok: true, json: () => Promise.resolve([]) } as Response);
      return Promise.resolve({ ok: true, json: () => Promise.resolve({}) } as Response);
    });
  });

  it('hydrates Notes from the graph API and syncs new user-authored notes without uploading demo seeds', async () => {
    await act(async () => { render(<App />); });
    fireEvent.click(screen.getByRole('button', { name: /Notes/i }));
    await waitFor(() => expect(global.fetch).toHaveBeenCalledWith('/v1/workspace/notes?page_size=50'));

    await screen.findByRole('heading', { name: 'Personal notes' });
    expect(screen.getByText('Novelty framing')).toBeInTheDocument();
    expect(global.fetch).not.toHaveBeenCalledWith('/v1/workspace/notes', expect.objectContaining({ method: 'POST' }));

    fireEvent.click(screen.getByTitle('New note'));
    fireEvent.click(screen.getByText('Create blank note'));
    const title = screen.getByDisplayValue('Untitled note');
    const body = screen.getByPlaceholderText('Write anything…');
    fireEvent.change(title, { target: { value: 'Rollback plan' } });
    fireEvent.change(body, { target: { value: 'Keep the migration reversible.' } });

    await waitFor(() => expect(global.fetch).toHaveBeenCalledWith('/v1/workspace/notes', expect.objectContaining({ method: 'POST' })));
    await waitFor(() => expect(global.fetch).toHaveBeenCalledWith('/v1/workspace/notes/personal-note-1', expect.objectContaining({ method: 'PUT' })), { timeout: 2000 });
    const savedUpdate = (global.fetch as ReturnType<typeof vi.fn>).mock.calls
      .map(([url, init]) => [String(url), init] as const)
      .find(([url, init]) => url.endsWith('/v1/workspace/notes/personal-note-1') && init?.method === 'PUT');
    expect(JSON.parse(String(savedUpdate?.[1]?.body))).toMatchObject({
      title: 'Rollback plan',
      body: 'Keep the migration reversible.',
      project_names: [],
    });
  });

  it('opens a personal workspace search result directly in its saved note', async () => {
    const note = {
      id: 'searchable-note-1', title: 'Privacy boundary', body: 'Connected files stay on this device.',
      tags: ['privacy'], project_names: [], pinned: false,
      created_at: '2026-10-02T00:00:00Z', updated_at: '2026-10-02T00:00:00Z',
    };
    global.fetch = vi.fn().mockImplementation((input: RequestInfo | URL) => {
      const url = String(input);
      if (url.includes('/v1/workspace/search')) return Promise.resolve({ ok: true, json: () => Promise.resolve([{
        object_id: note.id, object_type: 'manual_note', title: note.title, excerpt: note.body,
        project_name: null, created_by: 'user', updated_at: note.updated_at,
      }]) } as Response);
      if (url.endsWith('/v1/workspace/notes') || url.startsWith('/v1/workspace/notes?')) return Promise.resolve({ ok: true, json: () => Promise.resolve([note]) } as Response);
      if (url.endsWith('/v1/models')) return Promise.resolve({ ok: true, json: () => Promise.resolve({ providers: [] }) } as Response);
      if (url.includes('/v1/sessions?') || url.endsWith('/v1/memory')) return Promise.resolve({ ok: true, json: () => Promise.resolve([]) } as Response);
      return Promise.resolve({ ok: true, json: () => Promise.resolve({}) } as Response);
    });
    await act(async () => { render(<App />); });

    const input = screen.getByPlaceholderText(/Search files, projects/i);
    fireEvent.change(input, { target: { value: 'privacy boundary' } });
    await act(async () => { fireEvent.submit(input.closest('form')!); });
    expect(await screen.findByText('Privacy boundary')).toBeInTheDocument();
    fireEvent.click(screen.getByRole('button', { name: 'Open note' }));

    expect(await screen.findByRole('heading', { name: 'Personal notes' })).toBeInTheDocument();
    expect(await screen.findByDisplayValue('Privacy boundary')).toBeInTheDocument();
    expect(await screen.findByDisplayValue('Connected files stay on this device.')).toBeInTheDocument();

    fireEvent.click(screen.getByRole('button', { name: /Novelty framing/i }));
    fireEvent.change(screen.getByPlaceholderText('Write anything…'), { target: { value: 'Updated a different note.' } });
    expect(screen.getByDisplayValue('Novelty framing')).toBeInTheDocument();
  });

  it('restores a saved Note privacy classification after an unsuccessful update', async () => {
    const note = {
      id: 'note-privacy', title: 'Private note', body: 'Keep this on device.', tags: [], project_names: [],
      pinned: false, privacy_policy: 'confidential', created_at: '2026-10-02T00:00:00Z', updated_at: '2026-10-02T00:00:00Z',
    };
    global.fetch = vi.fn().mockImplementation((input: RequestInfo | URL, init?: RequestInit) => {
      const url = String(input);
      if (url.endsWith('/v1/models')) return Promise.resolve({ ok: true, json: () => Promise.resolve({ providers: [] }) } as Response);
      if (url.includes('/v1/sessions?')) return Promise.resolve({ ok: true, json: () => Promise.resolve([]) } as Response);
      if (url.endsWith('/v1/memory')) return Promise.resolve({ ok: true, json: () => Promise.resolve([]) } as Response);
      if (url.startsWith('/v1/workspace/notes?')) return Promise.resolve({ ok: true, json: () => Promise.resolve([note]) } as Response);
      if (url === '/v1/workspace/notes/note-privacy' && init?.method === 'PUT') {
        return Promise.resolve({ ok: false, status: 503, json: () => Promise.resolve({ detail: 'offline' }) } as Response);
      }
      return Promise.resolve({ ok: true, json: () => Promise.resolve({}) } as Response);
    });
    await act(async () => { render(<App />); });
    fireEvent.click(screen.getByRole('button', { name: /Notes/i }));

    await screen.findByRole('heading', { name: 'Personal notes' });
    fireEvent.click(await screen.findByRole('button', { name: /Private note/i }));
    expect(await screen.findByDisplayValue('Private note')).toBeInTheDocument();
    const privacy = screen.getByRole('combobox', { name: 'Note privacy classification' });
    expect(privacy).toHaveValue('confidential');
    fireEvent.change(privacy, { target: { value: 'local_only' } });

    await waitFor(() => expect(global.fetch).toHaveBeenCalledWith('/v1/workspace/notes/note-privacy', expect.objectContaining({ method: 'PUT' })), { timeout: 3000 });
    await waitFor(() => expect(privacy).toHaveValue('confidential'), { timeout: 3000 });
    expect(await screen.findByText(/Note was not saved/)).toBeInTheDocument();
  });
});

