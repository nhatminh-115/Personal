import { act, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import App from '../App';

vi.mock('../lib/localFiles', () => ({
  deleteLocalFile: vi.fn().mockResolvedValue(undefined),
  getLocalFile: vi.fn().mockResolvedValue(null),
  putLocalFile: vi.fn().mockResolvedValue(undefined),
}));

describe('Workspace Library references', () => {
  beforeEach(() => {
    window.localStorage.clear();
    vi.restoreAllMocks();
    global.fetch = vi.fn().mockImplementation((input: RequestInfo | URL, init?: RequestInit) => {
      const url = String(input);
      if (url.endsWith('/v1/models')) return Promise.resolve({ ok: true, json: () => Promise.resolve({ providers: [] }) } as Response);
      if (url.includes('/v1/sessions?')) return Promise.resolve({ ok: true, json: () => Promise.resolve([]) } as Response);
      if (url.endsWith('/v1/memory')) return Promise.resolve({ ok: true, json: () => Promise.resolve([]) } as Response);
      if (url.endsWith('/v1/workspace/library') && init?.method === 'POST') {
        const body = JSON.parse(String(init.body));
        return Promise.resolve({ ok: true, json: () => Promise.resolve({
          ...body, created_at: '2026-10-02T00:00:00Z', updated_at: '2026-10-02T00:00:00Z',
        }) } as Response);
      }
      if (url.endsWith('/v1/workspace/library')) return Promise.resolve({ ok: true, json: () => Promise.resolve([]) } as Response);
      return Promise.resolve({ ok: true, json: () => Promise.resolve({}) } as Response);
    });
  });

  it('keeps bundled seeds local and syncs only imported file metadata', async () => {
    await act(async () => { render(<App />); });
    fireEvent.click(screen.getByRole('button', { name: /^Library$/i }));
    await screen.findByRole('heading', { name: 'Your files can stay where they already live.' });
    await waitFor(() => expect(global.fetch).toHaveBeenCalledWith('/v1/workspace/library'));
    expect(screen.getByText('TOEIC Progress')).toBeInTheDocument();
    expect(global.fetch).not.toHaveBeenCalledWith('/v1/workspace/library', expect.objectContaining({ method: 'POST' }));

    const file = new File(['private contents stay local'], 'methods.pdf', { type: 'application/pdf' });
    const input = document.querySelector('input[type="file"]') as HTMLInputElement;
    fireEvent.change(input, { target: { files: [file] } });

    await waitFor(() => expect(global.fetch).toHaveBeenCalledWith('/v1/workspace/library', expect.objectContaining({ method: 'POST' })));
    const submitted = (global.fetch as ReturnType<typeof vi.fn>).mock.calls
      .map(([url, init]) => [String(url), init] as const)
      .find(([url, init]) => url.endsWith('/v1/workspace/library') && init?.method === 'POST');
    const payload = JSON.parse(String(submitted?.[1]?.body));
    expect(payload).toMatchObject({ name: 'methods', kind: 'PDF', mime_type: 'application/pdf' });
    expect(payload.id).toMatch(/^[0-9a-f-]{36}$/i);
    expect(JSON.stringify(payload)).not.toContain('private contents stay local');
    expect(JSON.stringify(payload)).not.toContain('blobKey');
  });

  it('opens a workspace search match at its exact Library reference', async () => {
    const reference = {
      id: 'library-search-match', name: 'Methods paper', kind: 'PDF', collection: 'Research',
      detail: 'Imported local file · methods.pdf', tags: ['methods'], project_names: [], size: 2048,
      mime_type: 'application/pdf', created_at: '2026-10-02T00:00:00Z', updated_at: '2026-10-02T00:00:00Z',
    };
    global.fetch = vi.fn().mockImplementation((input: RequestInfo | URL) => {
      const url = String(input);
      if (url.includes('/v1/workspace/search')) return Promise.resolve({ ok: true, json: () => Promise.resolve([{
        object_id: reference.id, object_type: 'file_reference', title: reference.name, excerpt: reference.detail,
        project_name: null, created_by: 'user', updated_at: reference.updated_at,
      }]) } as Response);
      if (url.endsWith('/v1/workspace/library')) return Promise.resolve({ ok: true, json: () => Promise.resolve([reference]) } as Response);
      if (url.endsWith('/v1/models')) return Promise.resolve({ ok: true, json: () => Promise.resolve({ providers: [] }) } as Response);
      if (url.includes('/v1/sessions?') || url.endsWith('/v1/memory')) return Promise.resolve({ ok: true, json: () => Promise.resolve([]) } as Response);
      return Promise.resolve({ ok: true, json: () => Promise.resolve({}) } as Response);
    });
    await act(async () => { render(<App />); });

    const input = screen.getByPlaceholderText(/Search files, projects/i);
    fireEvent.change(input, { target: { value: 'methods paper' } });
    await act(async () => { fireEvent.submit(input.closest('form')!); });
    expect(await screen.findByText('Methods paper')).toBeInTheDocument();
    fireEvent.click(screen.getByRole('button', { name: 'Open in Library' }));

    expect(await screen.findByRole('heading', { name: 'Your files can stay where they already live.' })).toBeInTheDocument();
    await waitFor(() => expect(document.querySelector('[data-library-item-id="library-search-match"]')).toHaveClass('is-search-focused'));
  });
});

