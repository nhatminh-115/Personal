/**
 * DemoLiveSeparation.test.tsx
 *
 * Invariant: demo threads (source: 'demo') MUST NOT silently call POST /v1/chat.
 * Invariant: new live threads are created by handleStartLiveChat, not by
 *            mutating a demo thread.
 * Invariant: clicking "Start live chat" from demo banner creates a brand-new
 *            thread with source: 'live'.
 */
import { render, screen, fireEvent, act } from '@testing-library/react';
import { describe, it, expect, vi, beforeEach } from 'vitest';
import App from '../App';

describe('Demo / Live Separation', () => {
  let postCalls: string[];

  beforeEach(() => {
    window.localStorage.clear();
    vi.restoreAllMocks();
    postCalls = [];

    global.fetch = vi.fn().mockImplementation((url: string, options?: RequestInit) => {
      if (options?.method === 'POST' && url.includes('/v1/chat')) {
        postCalls.push(url);
        return Promise.resolve({
          ok: true,
          json: () => Promise.resolve({ run_id: 'run-1', session_id: 'sess-1', status: 'completed', response: 'Reply', tool_results: [] }),
        });
      }
      if (url.includes('/v1/models')) return Promise.resolve({ ok: true, json: () => Promise.resolve({ providers: [] }) });
      if (url.includes('/v1/sessions')) return Promise.resolve({ ok: true, json: () => Promise.resolve([]) });
      if (url.includes('/v1/memory')) return Promise.resolve({ ok: true, json: () => Promise.resolve([]) });
      return Promise.resolve({ ok: true, json: () => Promise.resolve({}) });
    });
  });

  async function openStatefulChats() {
    await act(async () => { render(<App />); });
    const projectButton = screen.getAllByText(/Stateful Architecture/i)[0].closest('button')!;
    await act(async () => { fireEvent.click(projectButton); });
    const chatsBtn = screen.getByText(/Open project chats/i).closest('button')!;
    await act(async () => { fireEvent.click(chatsBtn); });
  }

  it('all seed threads are marked as demo', async () => {
    const { initialChatThreads } = await import('../data/workspaceData');
    const nonDemo = initialChatThreads.filter((t) => t.source !== 'demo');
    expect(nonDemo).toHaveLength(0);
  });

  it('sending text from a demo thread does NOT call POST /v1/chat', async () => {
    await openStatefulChats();

    // The active thread is a demo thread (Novelty & architecture)
    // Type in composer and press Enter
    const textarea = screen.getByPlaceholderText(/Ask AURA in this chat/i);
    await act(async () => {
      fireEvent.change(textarea, { target: { value: 'Test from demo' } });
      fireEvent.keyDown(textarea, { key: 'Enter', shiftKey: false });
    });

    // Wait for any potential async effects
    await act(async () => { await new Promise((r) => window.setTimeout(r, 100)); });

    expect(postCalls).toHaveLength(0);
  });

  it('demo thread shows a demo-mode banner', async () => {
    await openStatefulChats();
    expect(screen.getByText(/demo thread/i)).toBeInTheDocument();
  });

  it('newThread creates a live thread (source: live)', async () => {
    await openStatefulChats();

    // Click the new-thread button
    const newChatBtn = screen.getByTitle('New chat');
    await act(async () => { fireEvent.click(newChatBtn); });

    // The new thread's banner should NOT show "demo thread"
    // (it is live and should show the standard composer)
    const demoBanners = screen.queryAllByText(/demo thread/i);
    // If the new thread is live, the demo banner is gone
    expect(demoBanners).toHaveLength(0);
  });
});
