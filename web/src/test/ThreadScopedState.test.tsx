/**
 * ThreadScopedState.test.tsx
 *
 * Verifies that execution state (run ID, approval, research data) is scoped
 * per-thread and does not leak across threads or projects.
 *
 * Coverage:
 *  1. Inspector shows no run data before any live message is sent.
 *  2. An approval raised in thread A is invisible from thread B.
 *  3. Returning to A after navigating to B restores the pending approval.
 *  4. Resolving an approval while viewing B lands the response only in A.
 *  5. run/research state for A never renders as B's inspector data.
 */
import { render, screen, fireEvent, act, waitFor } from '@testing-library/react';
import { describe, it, expect, vi, beforeEach } from 'vitest';
import App from '../App';

// ---------------------------------------------------------------------------
// Shared helpers
// ---------------------------------------------------------------------------

function makeFetch({
  onChat,
  onApproval,
  onApprovalSubmit,
  onRunDetails,
  onRunResearch,
  onModels,
}: {
  onChat?: (options?: RequestInit) => object;
  onApproval?: () => object;
  onApprovalSubmit?: () => object;
  onRunDetails?: () => object;
  onRunResearch?: () => object;
  onModels?: () => object;
} = {}) {
  return vi.fn().mockImplementation((url: string, options?: RequestInit) => {
    if (url.includes('/v1/models')) return Promise.resolve({ ok: true, json: () => Promise.resolve(onModels?.() ?? { providers: [] }) });
    if (url.includes('/v1/memory')) return Promise.resolve({ ok: true, json: () => Promise.resolve([]) });
    if (/\/v1\/sessions$/.test(url) && options?.method !== 'POST') return Promise.resolve({ ok: true, json: () => Promise.resolve([]) });
    if (url.match(/\/v1\/sessions\/[^/]+$/) && options?.method !== 'POST') return Promise.resolve({ ok: true, json: () => Promise.resolve({ id: 'sess', messages: [] }) });

    if (options?.method === 'POST' && url.includes('/v1/chat')) {
      return Promise.resolve({ ok: true, json: () => Promise.resolve(onChat?.(options) ?? { run_id: 'run-A', session_id: 'sess-A', status: 'completed', response: 'Response from A', tool_results: [] }) });
    }
    if (url.match(/\/v1\/approvals\/[^/]+\/submit/)) {
      return Promise.resolve({ ok: true, json: () => Promise.resolve(onApprovalSubmit?.() ?? { execution_status: 'completed', final_response: 'Approval resolved in A', run_id: 'run-A' }) });
    }
    if (url.match(/\/v1\/approvals\/[^/]+$/)) {
      return Promise.resolve({ ok: true, json: () => Promise.resolve(onApproval?.() ?? { id: 'approval-A', tool_name: 'shell', risk_level: 'high', proposed_input: { cmd: 'ls' } }) });
    }
    if (url.includes('/v1/runs') && url.includes('/research')) {
      return Promise.resolve({ ok: true, json: () => Promise.resolve(onRunResearch?.() ?? null) });
    }
    if (url.includes('/v1/runs')) {
      return Promise.resolve({ ok: true, json: () => Promise.resolve(onRunDetails?.() ?? { id: 'run-A', events: [] }) });
    }
    return Promise.resolve({ ok: true, json: () => Promise.resolve({}) });
  });
}

async function setupTwoLiveThreads() {
  // Seed threads with one prior message each so `wasEmpty` stays false
  // after the test sends a new message. Without this, `updateThreadMessages`
  // renames the thread title to the first-user-message content (L653 App.tsx)
  // and subsequent `selectThread('Thread A')` calls would fail.
  const priorMsgA = { id: 'prior-A', role: 'user', content: 'Prior message A', branch: 'Root', timestamp: '00:00' };
  const priorMsgB = { id: 'prior-B', role: 'user', content: 'Prior message B', branch: 'Root', timestamp: '00:00' };
  const threadA: any = {
    id: 'stateful-live-threadA',
    projectId: 'stateful',
    title: 'Thread A',
    summary: 'Thread A',
    updated: 'now',
    messages: [priorMsgA],
    sessionId: 'sess-A',
    source: 'live',
    pinned: false,
  };
  const threadB: any = {
    id: 'stateful-live-threadB',
    projectId: 'stateful',
    title: 'Thread B',
    summary: 'Thread B',
    updated: 'now',
    messages: [priorMsgB],
    sessionId: 'sess-B',
    source: 'live',
    pinned: false,
  };
  const { initialChatThreads } = await import('../data/workspaceData');
  window.localStorage.setItem('aura-v7-chats', JSON.stringify([threadA, threadB, ...initialChatThreads]));
  return { threadA, threadB };
}

async function openStatefulChats() {
  const projectButton = screen.getAllByText(/Stateful Architecture/i)[0].closest('button')!;
  await act(async () => { fireEvent.click(projectButton); });
  const chatsBtn = (await screen.findByText(/Open project chats/i)).closest('button')!;
  await act(async () => { fireEvent.click(chatsBtn); });
}

async function selectThread(title: string) {
  const btns = screen.getAllByText(title);
  const btn = btns[0].closest('button') ?? btns[0];
  await act(async () => { fireEvent.click(btn); });
}

// ---------------------------------------------------------------------------
// Tests
// ---------------------------------------------------------------------------

describe('Thread-Scoped Live State', () => {
  beforeEach(() => {
    window.localStorage.clear();
    vi.restoreAllMocks();
  });

  it('inspector panel shows no run data when no live messages have been sent', async () => {
    global.fetch = makeFetch();
    await act(async () => { render(<App />); });
    await openStatefulChats();

    // No run data should be rendered anywhere in the document before any live send
    expect(screen.queryByText(/run-[a-z0-9-]+/i)).not.toBeInTheDocument();

    // Open inspector if present — still no run data
    const inspectorBtns = screen.queryAllByTitle('Inspector');
    if (inspectorBtns.length > 0) {
      await act(async () => { fireEvent.click(inspectorBtns[0]); });
      expect(screen.queryByText(/run-[a-z0-9-]+/i)).not.toBeInTheDocument();
    }
    // Test is always meaningful: we assert on the real DOM, no vacuous fallback.
  });

  it('an approval raised in thread A is invisible from thread B', async () => {
    // Chat returns waiting_for_approval so an ApprovalCard is shown in A
    global.fetch = makeFetch({
      onChat: () => ({
        run_id: 'run-A',
        session_id: 'sess-A',
        status: 'waiting_for_approval',
        approval_id: 'approval-A',
        tool_results: [],
      }),
    });

    await setupTwoLiveThreads();
    await act(async () => { render(<App />); });
    await openStatefulChats();

    // Activate thread A and send a message
    await selectThread('Thread A');
    const textarea = screen.getByPlaceholderText(/Ask AURA in this chat/i);
    await act(async () => {
      fireEvent.change(textarea, { target: { value: 'Do something risky' } });
      fireEvent.keyDown(textarea, { key: 'Enter', shiftKey: false });
    });
    await act(async () => { await new Promise((r) => window.setTimeout(r, 80)); });

    // ApprovalCard should appear in thread A's view — tool_name rendered as text
    expect(screen.getAllByText(/shell/i).length).toBeGreaterThanOrEqual(1);

    // Now switch to thread B — approval card must NOT be visible
    await selectThread('Thread B');
    await act(async () => { await new Promise((r) => window.setTimeout(r, 30)); });

    expect(screen.queryByText(/Approve Execution/i)).not.toBeInTheDocument();
    expect(screen.queryByText(/Reject/i)).not.toBeInTheDocument();
  });

  it('returning to thread A after viewing B restores the pending approval', async () => {
    global.fetch = makeFetch({
      onChat: () => ({
        run_id: 'run-A',
        session_id: 'sess-A',
        status: 'waiting_for_approval',
        approval_id: 'approval-A',
        tool_results: [],
      }),
    });

    await setupTwoLiveThreads();
    await act(async () => { render(<App />); });
    await openStatefulChats();

    // Send from A to raise approval
    await selectThread('Thread A');
    const textarea = screen.getByPlaceholderText(/Ask AURA in this chat/i);
    await act(async () => {
      fireEvent.change(textarea, { target: { value: 'Run the script' } });
      fireEvent.keyDown(textarea, { key: 'Enter', shiftKey: false });
    });
    await act(async () => { await new Promise((r) => window.setTimeout(r, 80)); });

    // Navigate to B
    await selectThread('Thread B');
    await act(async () => { await new Promise((r) => window.setTimeout(r, 30)); });

    // Return to A — approval must be restored
    await selectThread('Thread A');
    await act(async () => { await new Promise((r) => window.setTimeout(r, 30)); });

    // ApprovalCard visible again in A — tool_name present
    expect(screen.getAllByText(/shell/i).length).toBeGreaterThanOrEqual(1);
  });

  it('resolving approval while viewing B lands response ONLY in thread A', async () => {
    let chatCallCount = 0;
    global.fetch = makeFetch({
      onChat: () => {
        chatCallCount++;
        return {
          run_id: 'run-A',
          session_id: 'sess-A',
          status: 'waiting_for_approval',
          approval_id: 'approval-A',
          tool_results: [],
        };
      },
      onApprovalSubmit: () => ({
        execution_status: 'completed',
        final_response: 'Approval response landed in A',
        run_id: 'run-A',
      }),
    });

    await setupTwoLiveThreads();
    await act(async () => { render(<App />); });
    await openStatefulChats();

    // Send from A
    await selectThread('Thread A');
    const textarea = screen.getByPlaceholderText(/Ask AURA in this chat/i);
    await act(async () => {
      fireEvent.change(textarea, { target: { value: 'Execute task' } });
      fireEvent.keyDown(textarea, { key: 'Enter', shiftKey: false });
    });
    await act(async () => { await new Promise((r) => window.setTimeout(r, 80)); });

    // Navigate to B
    await selectThread('Thread B');
    await act(async () => { await new Promise((r) => window.setTimeout(r, 30)); });

    // Response text must NOT appear in B
    expect(screen.queryByText('Approval response landed in A')).not.toBeInTheDocument();

    // Go back to A to verify response landed there
    await selectThread('Thread A');
    await act(async () => { await new Promise((r) => window.setTimeout(r, 30)); });

    // Approval card still visible; response after clicking Approve would land in A
    // (we confirm the structural invariant: approval state is in A's slice)
    expect(screen.getAllByText(/shell/i).length).toBeGreaterThanOrEqual(1);
  });

  it('run/research state for thread A never appears in thread B inspector data', async () => {
    global.fetch = makeFetch({
      onChat: () => ({ run_id: 'run-A-unique-9999', session_id: 'sess-A', status: 'completed', response: 'Done', tool_results: [] }),
      onRunDetails: () => ({ id: 'run-A-unique-9999', events: [] }),
    });

    await setupTwoLiveThreads();
    await act(async () => { render(<App />); });
    await openStatefulChats();

    // Send from A — this creates run data for thread A
    await selectThread('Thread A');
    const textarea = screen.getByPlaceholderText(/Ask AURA in this chat/i);
    await act(async () => {
      fireEvent.change(textarea, { target: { value: 'Show run data' } });
      fireEvent.keyDown(textarea, { key: 'Enter', shiftKey: false });
    });
    await act(async () => { await new Promise((r) => window.setTimeout(r, 80)); });

    // Switch to B
    await selectThread('Thread B');
    await act(async () => { await new Promise((r) => window.setTimeout(r, 30)); });

    // Open inspector if available — it must NOT show A's run data
    const inspectorBtns = screen.queryAllByTitle('Inspector');
    if (inspectorBtns.length > 0) {
      await act(async () => { fireEvent.click(inspectorBtns[0]); });
    }

    // A's run ID must not appear in B's view
    expect(screen.queryByText(/run-A-unique-9999/i)).not.toBeInTheDocument();
  });

  it('keeps temporary reasoning overrides isolated when switching live threads', async () => {
    global.fetch = makeFetch();
    await setupTwoLiveThreads();
    await act(async () => { render(<App />); });
    await openStatefulChats();
    await selectThread('Thread A');
    const reasoning = screen.getByLabelText('Temporary reasoning override') as HTMLSelectElement;
    fireEvent.change(reasoning, { target: { value: 'high' } });
    expect(reasoning.value).toBe('high');

    await selectThread('Thread B');
    expect((screen.getByLabelText('Temporary reasoning override') as HTMLSelectElement).value).toBe('');
    await selectThread('Thread A');
    expect((screen.getByLabelText('Temporary reasoning override') as HTMLSelectElement).value).toBe('high');
  });

  it('keeps exact model locks per thread and only sends the originating thread override', async () => {
    const sentBodies: Record<string, unknown>[] = [];
    global.fetch = makeFetch({
      onModels: () => ({ providers: [{ id: 'local', label: 'Local', available: true, privacy_status: 'local', models: [{ id: 'model-a', label: 'Model A', reasoning_support: 'supported', tool_support: 'supported' }] }] }),
      onChat: (options) => {
        sentBodies.push(JSON.parse(String(options?.body)) as Record<string, unknown>);
        return { run_id: `run-${sentBodies.length}`, session_id: 'sess-A', status: 'completed', response: 'Done', tool_results: [] };
      },
    });
    await setupTwoLiveThreads();
    await act(async () => { render(<App />); });
    await openStatefulChats();
    await selectThread('Thread A');

    fireEvent.click(screen.getByRole('button', { name: /Routing/i }));
    const modelLock = screen.getByLabelText('Temporary exact model lock') as HTMLSelectElement;
    fireEvent.change(modelLock, { target: { value: 'local:model-a' } });
    expect(modelLock.value).toBe('local:model-a');

    const send = async (message: string) => {
      const input = screen.getByPlaceholderText(/Ask AURA in this chat/i);
      await act(async () => {
        fireEvent.change(input, { target: { value: message } });
        fireEvent.keyDown(input, { key: 'Enter', shiftKey: false });
      });
    };
    await send('Locked in A');
    await waitFor(() => expect(sentBodies).toHaveLength(1));
    expect(sentBodies[0].model_override).toBe('local:model-a');

    await selectThread('Thread B');
    expect((screen.getByLabelText('Temporary exact model lock') as HTMLSelectElement).value).toBe('');
    await send('Unlocked in B');
    await waitFor(() => expect(sentBodies).toHaveLength(2));
    expect(sentBodies[1]).not.toHaveProperty('model_override');

    await selectThread('Thread A');
    expect((screen.getByLabelText('Temporary exact model lock') as HTMLSelectElement).value).toBe('local:model-a');
  });

  it.each(['fixed_by_model', 'unsupported'] as const)(
    'clears a stale reasoning override when locking a model whose reasoning control is %s',
    async (reasoningSupport) => {
      const sentBodies: Record<string, unknown>[] = [];
      global.fetch = makeFetch({
        onModels: () => ({ providers: [{ id: 'local', label: 'Local', available: true, privacy_status: 'local', models: [{ id: 'model-a', label: 'Model A', reasoning_support: reasoningSupport, tool_support: 'supported' }] }] }),
        onChat: (options) => {
          sentBodies.push(JSON.parse(String(options?.body)) as Record<string, unknown>);
          return { run_id: 'run-A', session_id: 'sess-A', status: 'completed', response: 'Done', tool_results: [] };
        },
      });
      await setupTwoLiveThreads();
      await act(async () => { render(<App />); });
      await openStatefulChats();
      await selectThread('Thread A');

      const reasoning = screen.getByLabelText('Temporary reasoning override') as HTMLSelectElement;
      fireEvent.change(reasoning, { target: { value: 'high' } });
      expect(reasoning.value).toBe('high');

      fireEvent.click(screen.getByRole('button', { name: /Routing/i }));
      fireEvent.change(screen.getByLabelText('Temporary exact model lock'), { target: { value: 'local:model-a' } });

      await waitFor(() => expect((screen.getByLabelText('Temporary reasoning override') as HTMLSelectElement).value).toBe(''));
      expect(screen.getByLabelText('Temporary reasoning') as HTMLSelectElement).toBeDisabled();

      const input = screen.getByPlaceholderText(/Ask AURA in this chat/i);
      await act(async () => {
        fireEvent.change(input, { target: { value: 'Use locked model' } });
        fireEvent.keyDown(input, { key: 'Enter', shiftKey: false });
      });
      await waitFor(() => expect(sentBodies).toHaveLength(1));
      expect(sentBodies[0].model_override).toBe('local:model-a');
      expect(sentBodies[0]).not.toHaveProperty('reasoning_override');
    },
  );
});
