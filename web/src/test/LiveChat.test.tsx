import { render, screen, fireEvent, act, waitFor } from '@testing-library/react';
import { describe, it, expect, vi, beforeEach } from 'vitest';
import App from '../App';

describe('Live Chat and Backend Integration in v9.1 Shell', () => {
  beforeEach(() => {
    window.localStorage.clear();
    vi.restoreAllMocks();
  });

  it('sends chat request to /v1/chat and renders completed response with real execution events', async () => {
    let chatPayload: any = null;
    const consoleError = vi.spyOn(console, 'error');

    global.fetch = vi.fn().mockImplementation((url: string, init?: RequestInit) => {
      if (url.includes('/v1/workspace/projects/') && url.endsWith('/graph')) {
        return Promise.resolve({ ok: true, json: () => Promise.resolve({ objects: [{
          id: 'workspace-note-1', object_type: 'manual_note', title: 'Shared project constraint',
          content: 'Keep the migration reversible.', metadata_json: {}, created_by: 'user', session_id: null, source_message_id: null,
        }, {
          id: 'research-source-1', object_type: 'research_source', title: 'Durable execution paper',
          content: 'A paper abstract.', metadata_json: {}, created_by: 'research', session_id: null, source_message_id: null,
        }, {
          id: 'research-evidence-1', object_type: 'research_evidence', title: 'Checkpoint evidence',
          content: 'Execution resumes from a checkpoint.', metadata_json: {}, created_by: 'research', session_id: null, source_message_id: null,
        }, {
          id: 'research-claim-1', object_type: 'research_claim', title: 'Restartability claim',
          content: 'Verified claim text.', metadata_json: { verification_status: 'verified' }, created_by: 'research', session_id: null, source_message_id: null,
        }], edges: [], layout: { project_name: 'AURA', layout: {}, revision: 0 }, execution_traces: [] }) });
      }
      if (url.includes('/v1/models')) {
        return Promise.resolve({ ok: true, json: () => Promise.resolve({ providers: [] }) });
      }
      if (url.includes('/v1/sessions')) {
        return Promise.resolve({ ok: true, json: () => Promise.resolve([]) });
      }
      if (url.includes('/v1/memory')) {
        return Promise.resolve({ ok: true, json: () => Promise.resolve([]) });
      }
      if (url.includes('/v1/chat')) {
        chatPayload = JSON.parse(String(init?.body));
        return Promise.resolve({
          ok: true,
          json: () =>
            Promise.resolve({
              run_id: 'run-live-chat-1',
              session_id: chatPayload.session_id,
              status: 'completed',
              response: 'Live backend synthesis response for project architecture.',
              tool_results: [],
            }),
        });
      }
      if (url.includes('/v1/runs/run-live-chat-1/research')) {
        return Promise.resolve({ ok: true, json: () => Promise.resolve(null) });
      }
      if (url.includes('/v1/runs/run-live-chat-1')) {
        return Promise.resolve({
          ok: true,
          json: () =>
            Promise.resolve({
              id: 'run-live-chat-1',
              session_id: 'sess-test',
              status: 'completed',
              user_message: 'Hello from test',
              final_response: 'Live backend synthesis response for project architecture.',
              created_at: new Date().toISOString(),
              updated_at: new Date().toISOString(),
              events: [
                {
                  id: 'ev-context',
                  event_type: 'context_compiled',
                  payload: {
                    estimated_tokens: 184,
                    objects: [
                      { object_id: 'workspace-note-1', object_type: 'manual_note', selected_by_user: true, source_object_ids: [] },
                      { object_id: 'research-claim-1', object_type: 'research_claim', selected_by_user: true, source_object_ids: ['research-evidence-1'] },
                    ],
                  },
                  created_at: new Date().toISOString(),
                },
                {
                  id: 'ev-1',
                  event_type: 'routing_profile_resolved',
                  payload: { profile_name: 'Balanced' },
                  created_at: new Date().toISOString(),
                },
                {
                  id: 'ev-2',
                  event_type: 'model_selected',
                  payload: { model_id: 'model-c', provider: 'mock', model: 'model-c', agent_role: 'root' },
                  created_at: new Date().toISOString(),
                },
                {
                  id: 'ev-reasoning',
                  event_type: 'reasoning_effort_selected',
                  payload: { selected_effort: 'medium' },
                  created_at: new Date().toISOString(),
                },
              ],
            }),
        });
      }
      return Promise.resolve({ ok: true, json: () => Promise.resolve({}) });
    });

    await act(async () => {
      render(<App />);
    });

    // Open project chat
    const projectButton = screen.getAllByText(/^AURA$/i).find((item) => item.closest('.project-card'))!;
    await act(async () => {
      fireEvent.click(projectButton);
    });

    // Click Chats
    const chatsBtn = screen.getByRole('button', { name: /Open project chats/i });
    await act(async () => {
      fireEvent.click(chatsBtn);
    });

    // Click "New chat" to ensure it's a live thread
    const newChatBtn = screen.getByTitle('New chat');
    await act(async () => {
      fireEvent.click(newChatBtn);
    });

    // The live Context panel uses saved project graph objects and sends their IDs.
    fireEvent.click(screen.getByText('Context').closest('button')!);
    const contextItem = (await screen.findByText('Shared project constraint')).closest<HTMLButtonElement>('.ai-context-item')!;
    expect((await screen.findByText('Durable execution paper')).closest('.ai-context-item')).toHaveTextContent('research source');
    expect((await screen.findByText('Checkpoint evidence')).closest('.ai-context-item')).toHaveTextContent('research evidence');
    const claimItem = (await screen.findByText('Restartability claim')).closest<HTMLButtonElement>('.ai-context-item')!;
    const reactErrors = vi.spyOn(console, 'error').mockImplementation(() => {});
    fireEvent.click(claimItem);
    expect(claimItem).toHaveAttribute('aria-pressed', 'true');
    fireEvent.click(contextItem);
    expect(contextItem).toHaveAttribute('aria-pressed', 'true');
    expect(reactErrors.mock.calls.some((args) => String(args[0]).includes('Cannot update a component'))).toBe(false);
    reactErrors.mockRestore();

    // Type prompt into textarea and send
    const textarea = screen.getByPlaceholderText(/Ask AURA in this chat…/i);
    fireEvent.change(textarea, { target: { value: 'Explain state persistence in AURA' } });
    fireEvent.click(screen.getByRole('button', { name: /Code/i }));

    const sendBtn = screen.getByRole('button', { name: /Send/i });
    await act(async () => {
      fireEvent.click(sendBtn);
    });

    // Verify chat payload sent to /v1/chat
    expect(chatPayload).not.toBeNull();
    expect(chatPayload.message).toBe('Explain state persistence in AURA');
    expect(chatPayload.session_id).toBeDefined();
    expect(chatPayload.context_object_ids).toEqual(['workspace-note-1', 'research-claim-1']);
    expect(chatPayload.task_type).toBe('coding');

    // Verify response rendered in v9.1 UI
    expect(await screen.findByText(/Live backend synthesis response for project architecture/i)).toBeInTheDocument();
    expect(screen.getByText('mock:model-c')).toBeInTheDocument();
    expect(screen.getByText('Reasoning · Medium')).toBeInTheDocument();

    // The live response reuses the persisted context manifest and focuses the exact Research object on Board.
    expect(screen.getByText('0.2k context')).toBeInTheDocument();
    expect(screen.getByRole('button', { name: /Research claim.*research-claim-1/i })).toBeInTheDocument();

    // Verify execution badge
    expect(await screen.findByText(/AURA · 4 steps/i)).toBeInTheDocument();

    fireEvent.click(screen.getByText('Context').closest('button')!);
    fireEvent.click(screen.getByRole('button', { name: 'Show Restartability claim on Board' }));
    expect(await screen.findByRole('button', { name: 'Board' })).toBeInTheDocument();
    expect(await screen.findByText('Restartability claim')).toBeInTheDocument();
    await waitFor(() => expect(screen.getByText('Restartability claim').closest('.react-flow__node')).toHaveClass('selected'));

    // Response provenance must also navigate to the persisted object without the message click stealing focus.
    fireEvent.click(screen.getByRole('button', { name: 'Chat' }));
    fireEvent.click(screen.getByRole('button', { name: /Research claim.*research-claim-1/i }));
    expect(await screen.findByRole('button', { name: 'Board' })).toBeInTheDocument();
    await waitFor(() => expect(screen.getByText('Restartability claim').closest('.react-flow__node')).toHaveClass('selected'));
    expect(consoleError.mock.calls.flat().join(' ')).not.toMatch(/Received NaN/);
  });

  it('handles waiting_for_approval and resumes after decision is submitted', async () => {
    let decisionSubmitted = false;

    global.fetch = vi.fn().mockImplementation((url: string, _init?: RequestInit) => {
      if (url.includes('/v1/models')) {
        return Promise.resolve({ ok: true, json: () => Promise.resolve({ providers: [] }) });
      }
      if (url.includes('/v1/sessions')) {
        return Promise.resolve({ ok: true, json: () => Promise.resolve([]) });
      }
      if (url.includes('/v1/memory')) {
        return Promise.resolve({ ok: true, json: () => Promise.resolve([]) });
      }
      if (url.includes('/v1/chat')) {
        return Promise.resolve({
          ok: true,
          json: () =>
            Promise.resolve({
              run_id: 'run-appr-1',
              session_id: 'sess-appr-1',
              status: 'waiting_for_approval',
              approval_id: 'appr-req-001',
              tool_results: [],
            }),
        });
      }
      if (url.includes('/v1/approvals/appr-req-001/decision')) {
        decisionSubmitted = true;
        return Promise.resolve({
          ok: true,
          json: () =>
            Promise.resolve({
              approval_id: 'appr-req-001',
              status: 'approved',
              run_id: 'run-appr-1',
              execution_status: 'completed',
              final_response: 'Resumed and finished after approval.',
            }),
        });
      }
      if (url.includes('/v1/approvals/appr-req-001')) {
        return Promise.resolve({
          ok: true,
          json: () =>
            Promise.resolve({
              id: 'appr-req-001',
              run_id: 'run-appr-1',
              session_id: 'sess-appr-1',
              tool_name: 'sandbox_shell_execute',
              tool_input: { script: 'deploy.sh' },
              risk_level: 'HIGH',
              status: 'pending',
              created_at: new Date().toISOString(),
            }),
        });
      }
      if (url.includes('/v1/runs/run-appr-1/research')) {
        return Promise.resolve({ ok: true, json: () => Promise.resolve(null) });
      }
      if (url.includes('/v1/runs/run-appr-1')) {
        return Promise.resolve({
          ok: true,
          json: () =>
            Promise.resolve({
              id: 'run-appr-1',
              session_id: 'sess-appr-1',
              status: 'completed',
              user_message: 'Run deploy',
              final_response: 'Resumed and finished after approval.',
              created_at: new Date().toISOString(),
              updated_at: new Date().toISOString(),
              events: [],
            }),
        });
      }
      return Promise.resolve({ ok: true, json: () => Promise.resolve({}) });
    });

    await act(async () => {
      render(<App />);
    });

    // Navigate to project chat
    const projectButton = screen.getAllByText(/Stateful Architecture/i)[0];
    await act(async () => {
      fireEvent.click(projectButton);
    });
    const chatsBtn = screen.getByRole('button', { name: /Open project chats/i });
    await act(async () => {
      fireEvent.click(chatsBtn);
    });

    // Click new chat
    const newChatBtn = screen.getByTitle('New chat');
    await act(async () => {
      fireEvent.click(newChatBtn);
    });

    // Send command requiring approval
    const textarea = screen.getByPlaceholderText(/Ask AURA in this chat…/i);
    fireEvent.change(textarea, { target: { value: 'Execute deploy script' } });
    const sendBtn = screen.getByRole('button', { name: /Send/i });
    await act(async () => {
      fireEvent.click(sendBtn);
    });

    // Verify approval card appears in chat
    expect(await screen.findByTestId('approval-banner')).toBeInTheDocument();
    expect(screen.getAllByText(/sandbox_shell_execute/i).length).toBeGreaterThan(0);
    expect(screen.getByText(/HIGH RISK/i)).toBeInTheDocument();

    // Click Approve Execution
    const approveBtn = screen.getByRole('button', { name: /Approve Execution/i });
    await act(async () => {
      fireEvent.click(approveBtn);
    });

    expect(decisionSubmitted).toBe(true);

    // Verify resumed response rendered
    expect(await screen.findByText(/Resumed and finished after approval/i)).toBeInTheDocument();
  });

  it('shows concise routing guidance for a structured privacy boundary error', async () => {
    global.fetch = vi.fn().mockImplementation((url: string) => {
      if (url.includes('/v1/models')) return Promise.resolve({ ok: true, json: () => Promise.resolve({ providers: [] }) });
      if (url.includes('/v1/sessions')) return Promise.resolve({ ok: true, json: () => Promise.resolve([]) });
      if (url.includes('/v1/memory')) return Promise.resolve({ ok: true, json: () => Promise.resolve([]) });
      if (url.includes('/v1/chat')) return Promise.resolve({ ok: false, status: 403, text: () => Promise.resolve(JSON.stringify({ error: 'PrivacyBoundaryViolation', message: 'No local model is eligible.', details: { privacy: 'local_only' } })) });
      return Promise.resolve({ ok: true, json: () => Promise.resolve({}) });
    });
    await act(async () => { render(<App />); });
    fireEvent.click(screen.getAllByText(/Stateful Architecture/i)[0]);
    fireEvent.click(screen.getByRole('button', { name: /Open project chats/i }));
    fireEvent.click(screen.getByTitle('New chat'));
    fireEvent.change(screen.getByPlaceholderText(/Ask AURA in this chat…/i), { target: { value: 'Keep this local' } });
    await act(async () => { fireEvent.click(screen.getByRole('button', { name: /Send/i })); });
    expect(await screen.findByText(/No local model is eligible\. Privacy policy blocked this route/i)).toBeInTheDocument();
    expect(screen.getByText(/Review the profile scope and select a route that meets its privacy boundary/i)).toBeInTheDocument();
  });
});
