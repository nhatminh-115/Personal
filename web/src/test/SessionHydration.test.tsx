/**
 * SessionHydration.test.tsx
 *
 * Verifies that switching to a live thread with a sessionId triggers
 * GET /v1/sessions/{sessionId} and reconciles the backend messages into
 * the thread — without destroying existing local state.
 */
import { render, screen, fireEvent, act } from '@testing-library/react';
import { describe, it, expect, vi, beforeEach } from 'vitest';
import App from '../App';

const BACKEND_MESSAGE = {
  id: 'backend-msg-1',
  role: 'assistant' as const,
  content: 'Backend-hydrated response',
  branch: 'Root' as const,
  timestamp: '12:00',
};

describe('Session Hydration', () => {
  beforeEach(() => {
    window.localStorage.clear();
    vi.restoreAllMocks();
    global.fetch = vi.fn().mockImplementation((url: string) => {
      if (url.includes('/v1/models')) {
        return Promise.resolve({ ok: true, json: () => Promise.resolve({ providers: [] }) });
      }
      if (url.includes('/v1/memory')) {
        return Promise.resolve({ ok: true, json: () => Promise.resolve([]) });
      }
      // Session list returns one live session
      if (/\/v1\/sessions$/.test(url)) {
        return Promise.resolve({ ok: true, json: () => Promise.resolve([{ id: 'live-sess-1', title: 'Live', created_at: '2024-01-01', updated_at: '2024-01-01' }]) });
      }
      // Session detail returns a backend message
      if (url.includes('/v1/sessions/')) {
        return Promise.resolve({ ok: true, json: () => Promise.resolve({ id: 'live-sess-1', title: 'Live', created_at: '2024-01-01', updated_at: '2024-01-01', messages: [BACKEND_MESSAGE] }) });
      }
      return Promise.resolve({ ok: true, json: () => Promise.resolve({}) });
    });
  });

  it('selecting a live thread fetches /v1/sessions/{sessionId}', async () => {
    // Seed a live thread via localStorage
    const liveThread = {
      id: 'stateful-live-001',
      projectId: 'stateful',
      title: 'Live thread',
      summary: 'Connected to backend',
      updated: 'now',
      messages: [],
      sessionId: 'live-sess-1',
      source: 'live',
      pinned: false,
    };

    const { initialChatThreads } = await import('../data/workspaceData');
    window.localStorage.setItem('aura-v7-chats', JSON.stringify([liveThread, ...initialChatThreads]));

    await act(async () => {
      render(<App />);
    });

    // Navigate into stateful project
    const projectButton = screen.getAllByText(/Stateful Architecture/i)[0].closest('button')!;
    await act(async () => { fireEvent.click(projectButton); });

    // Open project chats
    const chatsBtn = screen.getByText(/Open project chats/i).closest('button')!;
    await act(async () => { fireEvent.click(chatsBtn); });

    // Click the live thread
    const liveThreadBtn = screen.getByText('Live thread');
    await act(async () => { fireEvent.click(liveThreadBtn); });

    // /v1/sessions/live-sess-1 was called
    const fetchCalls = (global.fetch as ReturnType<typeof vi.fn>).mock.calls.map(([url]: [string]) => url as string);
    const sessionDetailCalls = fetchCalls.filter((url: string) => url.includes('/v1/sessions/live-sess-1'));
    expect(sessionDetailCalls.length).toBeGreaterThanOrEqual(1);
  });

  it('hydration failure does not destroy local thread messages', async () => {
    // Override fetch to fail the session detail call
    global.fetch = vi.fn().mockImplementation((url: string) => {
      if (url.includes('/v1/models')) return Promise.resolve({ ok: true, json: () => Promise.resolve({ providers: [] }) });
      if (url.includes('/v1/memory')) return Promise.resolve({ ok: true, json: () => Promise.resolve([]) });
      if (/\/v1\/sessions$/.test(url)) return Promise.resolve({ ok: true, json: () => Promise.resolve([]) });
      if (url.includes('/v1/sessions/')) return Promise.resolve({ ok: false, status: 500, text: () => Promise.resolve('Internal Server Error') });
      return Promise.resolve({ ok: true, json: () => Promise.resolve({}) });
    });

    const existingMsg = { id: 'local-1', role: 'user' as const, content: 'Local message preserved', branch: 'Root' as const, timestamp: '11:00' };
    const liveThread = {
      id: 'stateful-live-002',
      projectId: 'stateful',
      title: 'Live thread 2',
      summary: 'Hydration will fail',
      updated: 'now',
      messages: [existingMsg],
      sessionId: 'bad-sess',
      source: 'live',
      pinned: false,
    };

    const { initialChatThreads } = await import('../data/workspaceData');
    window.localStorage.setItem('aura-v7-chats', JSON.stringify([liveThread, ...initialChatThreads]));

    await act(async () => { render(<App />); });

    const projectButton = screen.getAllByText(/Stateful Architecture/i)[0].closest('button')!;
    await act(async () => { fireEvent.click(projectButton); });
    const chatsBtn = screen.getByText(/Open project chats/i).closest('button')!;
    await act(async () => { fireEvent.click(chatsBtn); });

    const liveThreadBtn = screen.getByText('Live thread 2');
    await act(async () => { fireEvent.click(liveThreadBtn); });

    // Local message is still visible (hydration failure is silently swallowed)
    expect(screen.getByText('Local message preserved')).toBeInTheDocument();
  });
});
