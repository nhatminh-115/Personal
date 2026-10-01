import { act, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import App from '../App';

describe('Persistent workspace projects', () => {
  beforeEach(() => {
    window.localStorage.clear();
    vi.restoreAllMocks();
    global.fetch = vi.fn().mockImplementation((input: RequestInfo | URL, init?: RequestInit) => {
      const url = String(input);
      if (url.endsWith('/v1/workspace/projects') && init?.method === 'POST') {
        const body = JSON.parse(String(init.body));
        return Promise.resolve({ ok: true, json: () => Promise.resolve({
          ...body, created_at: '2026-10-02T00:00:00Z', updated_at: '2026-10-02T00:00:00Z',
        }) } as Response);
      }
      if (url.endsWith('/v1/workspace/projects')) return Promise.resolve({ ok: true, json: () => Promise.resolve([]) } as Response);
      if (url.endsWith('/v1/models')) return Promise.resolve({ ok: true, json: () => Promise.resolve({ providers: [] }) } as Response);
      if (url.endsWith('/v1/sessions')) return Promise.resolve({ ok: true, json: () => Promise.resolve([]) } as Response);
      if (url.endsWith('/v1/memory')) return Promise.resolve({ ok: true, json: () => Promise.resolve([]) } as Response);
      return Promise.resolve({ ok: true, json: () => Promise.resolve({}) } as Response);
    });
  });

  it('creates a durable project and opens it in one reusable project tab', async () => {
    await act(async () => { render(<App />); });
    fireEvent.click(screen.getByTitle('All projects'));
    await screen.findByRole('heading', { name: 'Separate contexts, one personal workspace.' });
    fireEvent.click(screen.getAllByRole('button', { name: /New project/i }).at(-1)!);
    fireEvent.change(screen.getByLabelText(/Project name/i), { target: { value: 'Field Notes' } });
    fireEvent.change(screen.getByLabelText(/Description/i), { target: { value: 'A durable project context' } });
    fireEvent.click(screen.getByRole('button', { name: 'Create project' }));

    await screen.findByRole('heading', { name: 'Field Notes' });
    await waitFor(() => expect(global.fetch).toHaveBeenCalledWith('/v1/workspace/projects', expect.objectContaining({ method: 'POST' })));
    const createCall = (global.fetch as ReturnType<typeof vi.fn>).mock.calls
      .map(([url, init]) => [String(url), init] as const)
      .find(([url, init]) => url.endsWith('/v1/workspace/projects') && init?.method === 'POST');
    expect(JSON.parse(String(createCall?.[1]?.body))).toMatchObject({ name: 'Field Notes', subtitle: 'A durable project context' });
    expect(screen.getAllByRole('button').filter((button) => button.closest('.workspace-chrome') && button.textContent?.includes('Field Notes'))).toHaveLength(1);
    expect(screen.getByTitle('Field Notes')).toBeInTheDocument();
    expect(screen.getByText('Your project is ready.')).toBeInTheDocument();
  });
});
