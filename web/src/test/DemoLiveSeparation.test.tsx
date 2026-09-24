/**
 * DemoLiveSeparation.test.tsx
 *
 * Invariant: demo threads (source: 'demo') MUST NOT silently call POST /v1/chat.
 * Invariant: new live threads are created by handleStartLiveChat, not by
 *            mutating a demo thread.
 * Invariant: clicking "Start live chat" from demo banner creates a brand-new
 *            thread with source: 'live'.
 * Invariant: CTA with draft text sends that exact text; CTA with empty draft
 *            creates thread only without backend call.
 */
import { render, screen, fireEvent, act } from '@testing-library/react';
import { describe, it, expect, vi, beforeEach } from 'vitest';
import App from '../App';

describe('Demo / Live Separation', () => {
  let postCalls: { url: string; body: string }[];

  beforeEach(() => {
    window.localStorage.clear();
    vi.restoreAllMocks();
    postCalls = [];

    global.fetch = vi.fn().mockImplementation((url: string, options?: RequestInit) => {
      if (options?.method === 'POST' && url.includes('/v1/chat')) {
        postCalls.push({ url, body: typeof options.body === 'string' ? options.body : '' });
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

    // The active thread is a demo thread — type and press Enter
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

    // The new thread is live — demo banner must be gone
    const demoBanners = screen.queryAllByText(/demo thread/i);
    expect(demoBanners).toHaveLength(0);
  });

  it('CTA with non-empty draft creates live thread AND sends exact draft text to backend', async () => {
    await openStatefulChats();

    // Type a draft message
    const textarea = screen.getByPlaceholderText(/Ask AURA in this chat/i);
    const draftText = 'Explain the architecture';
    await act(async () => {
      fireEvent.change(textarea, { target: { value: draftText } });
    });

    // Click "Start live chat" CTA button
    const ctaBtn = screen.getByText('Start live chat');
    await act(async () => { fireEvent.click(ctaBtn); });

    // Wait for async backend call
    await act(async () => { await new Promise((r) => window.setTimeout(r, 100)); });

    // Backend was called exactly once
    expect(postCalls).toHaveLength(1);
    // The exact draft text was sent — NOT literal "Start live chat"
    expect(postCalls[0].body).toContain(draftText);
    expect(postCalls[0].body).not.toContain('Start live chat');
  });

  it('CTA with empty draft creates live thread WITHOUT calling backend', async () => {
    await openStatefulChats();

    // Ensure textarea is empty
    const textarea = screen.getByPlaceholderText(/Ask AURA in this chat/i);
    await act(async () => {
      fireEvent.change(textarea, { target: { value: '' } });
    });

    // Click CTA
    const ctaBtn = screen.getByText('Start live chat');
    await act(async () => { fireEvent.click(ctaBtn); });

    // Wait for any potential async
    await act(async () => { await new Promise((r) => window.setTimeout(r, 100)); });

    // No backend call — thread was created only
    expect(postCalls).toHaveLength(0);

    // Demo banner is gone — we switched to the new live thread
    expect(screen.queryAllByText(/demo thread/i)).toHaveLength(0);
  });
});
