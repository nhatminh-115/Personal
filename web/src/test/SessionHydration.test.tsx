/**
 * SessionHydration.test.tsx
 *
 * Verifies that switching to a live thread with a sessionId triggers
 * GET /v1/sessions/{sessionId} and reconciles the backend messages into
 * the thread — without destroying existing local state.
 */
import { render, screen, fireEvent, act, waitFor } from '@testing-library/react';
import { describe, it, expect, vi, beforeEach } from 'vitest';
import App from '../App';

const BACKEND_UUID = 'c0ffee00-dead-beef-cafe-000000000001';
const BACKEND_MESSAGE = {
  id: BACKEND_UUID,
  role: 'assistant' as const,
  content: 'Backend-hydrated response',
  branch: 'Root' as const,
  timestamp: '12:00',
  run_id: 'hydrated-run-1',
  context_manifest: {
    estimated_tokens: 96,
    objects: [{ object_id: 'hydrated-research-source', object_type: 'research_source', selected_by_user: true, source_object_ids: [] }],
  },
  routing_provenance: { provider: 'ollama', model: 'local-chat', role: 'root', reasoning_effort: 'medium' },
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
      if (url.includes('/v1/sessions?')) {
        return Promise.resolve({
          ok: true,
          headers: { get: () => null },
          json: () => Promise.resolve([{
            id: 'restored-session-1', title: 'Recovered conversation', project_name: 'Stateful Architecture',
            created_at: '2024-01-01', updated_at: '2024-01-02',
          }, {
            id: 'live-sess-1', title: 'Live', project_name: 'Stateful Architecture',
            created_at: '2024-01-01', updated_at: '2024-01-01',
          }]),
        });
      }
      if (url.endsWith('/v1/sessions/live-sess-1/state')) {
        return Promise.resolve({ ok: true, json: () => Promise.resolve({
          session_id: 'live-sess-1', run_id: 'hydrated-run-1', run_status: 'waiting_for_approval',
          approval: {
            id: 'approval-after-reload', run_id: 'hydrated-run-1', session_id: 'live-sess-1',
            tool_call_id: 'call-after-reload', tool_name: 'shell', tool_input: { command: 'inspect' },
            risk_level: 'HIGH', status: 'pending', created_at: '2024-01-01T00:00:00Z',
          },
        }) });
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
    const chatsBtn = (await screen.findByText(/Open project chats/i)).closest('button')!;
    await act(async () => { fireEvent.click(chatsBtn); });

    // Click the live thread
    const liveThreadBtn = screen.getByText('Live thread');
    await act(async () => { fireEvent.click(liveThreadBtn); });

    expect(await screen.findByRole('button', { name: /Research source.*hydrated-research-source/i })).toBeInTheDocument();
    expect(screen.getByText('0.1k context')).toBeInTheDocument();
    expect(screen.getByText('ollama:local-chat')).toBeInTheDocument();
    expect(screen.getByText('Reasoning · Medium')).toBeInTheDocument();
    expect(await screen.findByTestId('approval-banner')).toBeInTheDocument();

    // /v1/sessions/live-sess-1 was called
    // Fix 1: use type-safe call[0] extraction instead of tuple destructure
    const fetchCalls = (global.fetch as ReturnType<typeof vi.fn>).mock.calls.map(
      (call: unknown[]) => call[0] as string
    );
    const sessionDetailCalls = fetchCalls.filter((url: string) => url.includes('/v1/sessions/live-sess-1'));
    expect(sessionDetailCalls.length).toBeGreaterThanOrEqual(1);
  });

  it('polls a live running turn and hydrates its canonical messages after completion', async () => {
    let stateCalls = 0;
    let detailCalls = 0;
    global.fetch = vi.fn().mockImplementation((url: string) => {
      if (url.includes('/v1/models')) return Promise.resolve({ ok: true, json: () => Promise.resolve({ providers: [] }) });
      if (url.includes('/v1/memory')) return Promise.resolve({ ok: true, json: () => Promise.resolve([]) });
      if (/\/v1\/sessions(?:\?|$)/.test(url)) return Promise.resolve({ ok: true, json: () => Promise.resolve([]) });
      if (url.includes('/v1/sessions/live-sess-running/state')) {
        stateCalls += 1;
        return Promise.resolve({
          ok: true,
          json: () => Promise.resolve({
            session_id: 'live-sess-running',
            run_id: 'hydrated-run-1',
            run_status: stateCalls === 1 ? 'running' : 'completed',
          }),
        });
      }
      if (url.includes('/v1/sessions/live-sess-running')) {
        detailCalls += 1;
        return Promise.resolve({
          ok: true,
          json: () => Promise.resolve({
            id: 'live-sess-running',
            title: 'Recoverable live chat',
            created_at: '2024-01-01',
            updated_at: '2024-01-01',
            messages: detailCalls === 1 ? [] : [BACKEND_MESSAGE],
          }),
        });
      }
      return Promise.resolve({ ok: true, json: () => Promise.resolve({}) });
    });

    const liveThread = {
      id: 'stateful-live-running',
      projectId: 'stateful',
      title: 'Recoverable live chat',
      summary: 'A retried request is still executing',
      updated: 'now',
      messages: [],
      sessionId: 'live-sess-running',
      source: 'live',
      pinned: false,
    };
    const { initialChatThreads } = await import('../data/workspaceData');
    window.localStorage.setItem('aura-v7-chats', JSON.stringify([liveThread, ...initialChatThreads]));

    await act(async () => { render(<App />); });
    const projectButton = screen.getAllByText(/Stateful Architecture/i)[0].closest('button')!;
    await act(async () => { fireEvent.click(projectButton); });
    const chatsButton = (await screen.findByText(/Open project chats/i)).closest('button')!;
    await act(async () => { fireEvent.click(chatsButton); });
    await act(async () => { fireEvent.click(screen.getByText('Recoverable live chat')); });

    await waitFor(() => expect(screen.getByText('Backend-hydrated response')).toBeInTheDocument(), { timeout: 5000 });
    expect(stateCalls).toBeGreaterThanOrEqual(2);
  });

  it('restores backend sessions into the matching project chat rail', async () => {
    await act(async () => { render(<App />); });

    const projectButton = screen.getAllByText(/Stateful Architecture/i)[0].closest('button')!;
    await act(async () => { fireEvent.click(projectButton); });
    const chatsButton = (await screen.findByText(/Open project chats/i)).closest('button')!;
    await act(async () => { fireEvent.click(chatsButton); });

    expect(await screen.findByRole('button', { name: /Recovered conversation/ })).toBeInTheDocument();
    expect(global.fetch).toHaveBeenCalledWith(expect.stringContaining('/v1/sessions?page_size=25&project_name=Stateful+Architecture'));
  });

  it('opens the exact source run from project-memory provenance', async () => {
    global.fetch = vi.fn().mockImplementation((url: string) => {
      if (url.includes('/v1/models')) return Promise.resolve({ ok: true, json: () => Promise.resolve({ providers: [] }) });
      if (url.includes('/v1/memory')) return Promise.resolve({ ok: true, headers: { get: () => null }, json: () => Promise.resolve([{
        id: 'memory-source-run', memory_type: 'project', project_name: 'Stateful Architecture',
        key: 'runtime decision', content: 'Keep execution traceable.', confidence: 0.95, is_active: true,
        created_at: '2026-10-04T00:00:00Z',
        metadata_json: { source_session_id: 'source-session-1', source_run_id: 'source-run-1' },
      }]) });
      if (url.includes('/v1/sessions?')) return Promise.resolve({ ok: true, headers: { get: () => null }, json: () => Promise.resolve([]) });
      if (url.includes('/v1/routing/effective')) return Promise.resolve({ ok: true, json: () => Promise.resolve({ profile: { id: 'system-balanced', name: 'System Balanced', version: 1, routes: {} }, winning_scope: 'system' }) });
      if (url.includes('/v1/runs/source-run-1/routing')) return Promise.resolve({ ok: true, json: () => Promise.resolve({ run_id: 'source-run-1', decisions: [] }) });
      if (url.includes('/v1/runs/source-run-1')) return Promise.resolve({
        ok: true,
        headers: { get: () => null },
        json: () => Promise.resolve({
          id: 'source-run-1', session_id: 'source-session-1', status: 'completed',
          user_message: 'Explain the persisted route', final_response: 'The route was persisted.',
          created_at: '2026-10-04T00:00:00Z', updated_at: '2026-10-04T00:00:01Z',
          events: [{ id: 'source-run-event', event_type: 'model_selected', payload: { provider: 'ollama', model: 'local-chat' }, created_at: '2026-10-04T00:00:00Z' }],
        }),
      });
      if (url.includes('/v1/sessions/source-session-1')) return Promise.resolve({ ok: true, json: () => Promise.resolve({
        id: 'source-session-1', title: 'Originating chat', project_name: 'Stateful Architecture',
        created_at: '2026-10-04T00:00:00Z', updated_at: '2026-10-04T00:00:01Z', messages: [],
      }) });
      if (url.includes('/v1/sessions/source-session-1/state')) return Promise.resolve({ ok: true, json: () => Promise.resolve({ session_id: 'source-session-1', run_id: null, run_status: null, approval: null }) });
      return Promise.resolve({ ok: true, json: () => Promise.resolve({}) });
    });

    await act(async () => { render(<App />); });
    const projectButton = screen.getAllByText(/Stateful Architecture/i)[0].closest('button')!;
    await act(async () => { fireEvent.click(projectButton); });
    await act(async () => { fireEvent.click(screen.getByRole('button', { name: 'Chat' })); });
    await act(async () => { fireEvent.click(screen.getByRole('button', { name: 'Inspector' })); });
    await screen.findByTestId('inspector-panel');
    await act(async () => { fireEvent.click(screen.getByTestId('inspector-tab-memory')); });
    await act(async () => { fireEvent.click(await screen.findByRole('button', { name: 'Why AURA remembers this' })); });
    await act(async () => { fireEvent.click(screen.getByRole('button', { name: 'Open source run' })); });

    expect(await screen.findByTestId('inspector-execution')).toBeInTheDocument();
    expect(screen.getByText(/Run ID: source-run-1/)).toBeInTheDocument();
    expect(screen.getByText('model_selected')).toBeInTheDocument();
    expect(global.fetch).toHaveBeenCalledWith(expect.stringContaining('/v1/runs/source-run-1?page_size=100'));
    expect(global.fetch).toHaveBeenCalledWith(expect.stringContaining('/v1/runs/source-run-1/routing'));
    expect(global.fetch).toHaveBeenCalledWith(expect.stringContaining('/v1/sessions/source-session-1'));
  });

  it('loads older live messages with the next session cursor', async () => {
    const newerMessage = { ...BACKEND_MESSAGE, id: 'newer-message', content: 'Newest page message' };
    const olderMessage = { ...BACKEND_MESSAGE, id: 'older-message', content: 'Older page message' };
    global.fetch = vi.fn().mockImplementation((url: string) => {
      if (url.includes('/v1/models')) return Promise.resolve({ ok: true, json: () => Promise.resolve({ providers: [] }) });
      if (url.includes('/v1/memory')) return Promise.resolve({ ok: true, json: () => Promise.resolve([]) });
      if (url.includes('/v1/sessions?')) return Promise.resolve({ ok: true, headers: { get: () => null }, json: () => Promise.resolve([]) });
      if (url.includes('/v1/sessions/live-paged-session')) {
        const olderPage = url.includes('cursor=older-cursor');
        return Promise.resolve({ ok: true, json: () => Promise.resolve({
          id: 'live-paged-session', title: 'Paged thread', created_at: '2024-01-01', updated_at: '2024-01-01',
          messages: [olderPage ? olderMessage : newerMessage],
          messages_next_cursor: olderPage ? null : 'older-cursor',
        }) });
      }
      return Promise.resolve({ ok: true, json: () => Promise.resolve({}) });
    });

    const liveThread = {
      id: 'stateful-live-paged', projectId: 'stateful', title: 'Paged thread', summary: 'History pagination',
      updated: 'now', messages: [], sessionId: 'live-paged-session', source: 'live', pinned: false,
    };
    const { initialChatThreads } = await import('../data/workspaceData');
    window.localStorage.setItem('aura-v7-chats', JSON.stringify([liveThread, ...initialChatThreads]));

    await act(async () => { render(<App />); });
    const projectButton = screen.getAllByText(/Stateful Architecture/i)[0].closest('button')!;
    await act(async () => { fireEvent.click(projectButton); });
    const chatsBtn = (await screen.findByText(/Open project chats/i)).closest('button')!;
    await act(async () => { fireEvent.click(chatsBtn); });
    await act(async () => { fireEvent.click(screen.getByText('Paged thread')); });

    expect(await screen.findByText('Newest page message')).toBeInTheDocument();
    await act(async () => { fireEvent.click(screen.getByRole('button', { name: 'Load older messages' })); });
    expect(await screen.findByText('Older page message')).toBeInTheDocument();
    expect(screen.queryByRole('button', { name: 'Load older messages' })).not.toBeInTheDocument();
    expect((global.fetch as ReturnType<typeof vi.fn>).mock.calls.some(([url]) => String(url).includes('cursor=older-cursor'))).toBe(true);
  });

  it('clears stale older-message loading state restored from local storage', async () => {
    global.fetch = vi.fn().mockImplementation((url: string) => {
      if (url.includes('/v1/models')) return Promise.resolve({ ok: true, json: () => Promise.resolve({ providers: [] }) });
      if (url.includes('/v1/memory')) return Promise.resolve({ ok: true, json: () => Promise.resolve([]) });
      if (url.includes('/v1/sessions?')) return Promise.resolve({ ok: true, headers: { get: () => null }, json: () => Promise.resolve([]) });
      if (url.includes('/v1/sessions/stale-load-session')) return Promise.resolve({ ok: false, status: 503, text: () => Promise.resolve('Unavailable') });
      return Promise.resolve({ ok: true, json: () => Promise.resolve({}) });
    });
    const liveThread = {
      id: 'stateful-live-stale-load', projectId: 'stateful', title: 'Stale loading thread', summary: 'Reload recovery',
      updated: 'now', messages: [], sessionId: 'stale-load-session', source: 'live', pinned: false,
      messagesNextCursor: 'older-cursor', loadingOlderMessages: true,
    };
    const { initialChatThreads } = await import('../data/workspaceData');
    window.localStorage.setItem('aura-v7-chats', JSON.stringify([liveThread, ...initialChatThreads]));

    await act(async () => { render(<App />); });
    const projectButton = screen.getAllByText(/Stateful Architecture/i)[0].closest('button')!;
    await act(async () => { fireEvent.click(projectButton); });
    const chatsBtn = (await screen.findByText(/Open project chats/i)).closest('button')!;
    await act(async () => { fireEvent.click(chatsBtn); });
    await act(async () => { fireEvent.click(screen.getByText('Stale loading thread')); });

    const loadButton = await screen.findByRole('button', { name: 'Load older messages' });
    expect(loadButton).toBeEnabled();
  });

  it('recovers pending routing confirmation for the selected live session', async () => {
    global.fetch = vi.fn().mockImplementation((url: string) => {
      if (url.includes('/v1/models')) return Promise.resolve({ ok: true, json: () => Promise.resolve({ providers: [] }) });
      if (url.includes('/v1/memory')) return Promise.resolve({ ok: true, json: () => Promise.resolve([]) });
      if (url.includes('/v1/sessions?')) return Promise.resolve({ ok: true, headers: { get: () => null }, json: () => Promise.resolve([]) });
      if (url.includes('/v1/routing-confirmations/pending')) {
        const scoped = url.includes('session_id=confirm-session');
        return Promise.resolve({ ok: true, json: () => Promise.resolve(scoped ? [{
          id: 'pending-confirmation', root_run_id: 'pending-root-run', execution_run_id: 'pending-root-run',
          session_id: 'confirm-session', proposed_provider: 'cloud-provider', proposed_model: 'private-model',
          status: 'pending', created_at: '2026-01-01T00:00:00Z',
        }] : []) });
      }
      return Promise.resolve({ ok: true, json: () => Promise.resolve({}) });
    });
    const liveThread = {
      id: 'stateful-live-confirm', projectId: 'stateful', title: 'Confirmation thread', summary: 'Resume routing',
      updated: 'now', messages: [], sessionId: 'confirm-session', source: 'live', pinned: false,
    };
    const { initialChatThreads } = await import('../data/workspaceData');
    window.localStorage.setItem('aura-v7-chats', JSON.stringify([liveThread, ...initialChatThreads]));

    await act(async () => { render(<App />); });
    const projectButton = screen.getAllByText(/Stateful Architecture/i)[0].closest('button')!;
    await act(async () => { fireEvent.click(projectButton); });
    const chatsBtn = (await screen.findByText(/Open project chats/i)).closest('button')!;
    await act(async () => { fireEvent.click(chatsBtn); });
    await act(async () => { fireEvent.click(screen.getByText('Confirmation thread')); });

    expect(await screen.findByRole('heading', { name: 'Cloud routing requires confirmation' })).toBeInTheDocument();
    expect(screen.getByText('cloud-provider:private-model')).toBeInTheDocument();
    expect((global.fetch as ReturnType<typeof vi.fn>).mock.calls.some(([url]) => String(url).includes('session_id=confirm-session'))).toBe(true);
  });

  it('hydration failure does not destroy local thread messages', async () => {
    // Override fetch to fail the session detail call
    global.fetch = vi.fn().mockImplementation((url: string) => {
      if (url.includes('/v1/models')) return Promise.resolve({ ok: true, json: () => Promise.resolve({ providers: [] }) });
      if (url.includes('/v1/memory')) return Promise.resolve({ ok: true, json: () => Promise.resolve([]) });
      if (url.includes('/v1/sessions?')) return Promise.resolve({ ok: true, headers: { get: () => null }, json: () => Promise.resolve([]) });
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
    const chatsBtn = (await screen.findByText(/Open project chats/i)).closest('button')!;
    await act(async () => { fireEvent.click(chatsBtn); });

    const liveThreadBtn = screen.getByText('Live thread 2');
    await act(async () => { fireEvent.click(liveThreadBtn); });

    // Local message is still visible (hydration failure is silently swallowed)
    expect(screen.getByText('Local message preserved')).toBeInTheDocument();
  });

  it('locally-rendered turn is NOT duplicated after hydration reconciliation', async () => {
    // Scenario: the user sent a message before navigating away.
    // The message was optimistically rendered with a synthetic local ID.
    // When the user comes back and hydration fires, the backend returns the
    // same turn with its canonical UUID.  The reconciler MUST NOT duplicate it.

    const localOptimisticId = 'live-user-999999';
    const localMsg = {
      id: localOptimisticId,
      role: 'user' as const,
      content: 'Hello from user',
      branch: 'Root' as const,
      timestamp: '11:30',
    };

    // Backend returns the same content with canonical UUID
    const backendMsg = {
      id: BACKEND_UUID,
      role: 'user' as const,
      content: 'Hello from user',   // identical content
      branch: 'Root' as const,
      timestamp: '11:30',
    };

    global.fetch = vi.fn().mockImplementation((url: string) => {
      if (url.includes('/v1/models')) return Promise.resolve({ ok: true, json: () => Promise.resolve({ providers: [] }) });
      if (url.includes('/v1/memory')) return Promise.resolve({ ok: true, json: () => Promise.resolve([]) });
      if (url.includes('/v1/sessions?')) return Promise.resolve({ ok: true, headers: { get: () => null }, json: () => Promise.resolve([]) });
      if (url.includes('/v1/sessions/live-dedup-sess')) {
        return Promise.resolve({ ok: true, json: () => Promise.resolve({ id: 'live-dedup-sess', messages: [backendMsg] }) });
      }
      return Promise.resolve({ ok: true, json: () => Promise.resolve({}) });
    });

    const liveThread = {
      id: 'stateful-live-dedup',
      projectId: 'stateful',
      title: 'Live dedup thread',
      summary: 'Dedup test',
      updated: 'now',
      messages: [localMsg],
      sessionId: 'live-dedup-sess',
      source: 'live',
      pinned: false,
    };

    const { initialChatThreads } = await import('../data/workspaceData');
    window.localStorage.setItem('aura-v7-chats', JSON.stringify([liveThread, ...initialChatThreads]));

    await act(async () => { render(<App />); });

    const projectButton = screen.getAllByText(/Stateful Architecture/i)[0].closest('button')!;
    await act(async () => { fireEvent.click(projectButton); });
    const chatsBtn = (await screen.findByText(/Open project chats/i)).closest('button')!;
    await act(async () => { fireEvent.click(chatsBtn); });

    const liveThreadBtn = screen.getByText('Live dedup thread');
    await act(async () => { fireEvent.click(liveThreadBtn); });

    // Wait for hydration async
    await act(async () => { await new Promise((r) => window.setTimeout(r, 50)); });

    // "Hello from user" must appear exactly once — not duplicated
    const allMatches = screen.getAllByText('Hello from user');
    expect(allMatches).toHaveLength(1);
  });
});
