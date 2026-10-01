import { render, screen, fireEvent, act } from '@testing-library/react';
import { describe, it, expect, vi, beforeEach } from 'vitest';
import App from '../App';

describe('Live Chat and Backend Integration in v9.1 Shell', () => {
  beforeEach(() => {
    window.localStorage.clear();
    vi.restoreAllMocks();
  });

  it('sends chat request to /v1/chat and renders completed response with real execution events', async () => {
    let chatPayload: any = null;

    global.fetch = vi.fn().mockImplementation((url: string, init?: RequestInit) => {
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
                  id: 'ev-1',
                  event_type: 'routing_profile_resolved',
                  payload: { profile_name: 'Balanced' },
                  created_at: new Date().toISOString(),
                },
                {
                  id: 'ev-2',
                  event_type: 'model_selected',
                  payload: { model_id: 'model-c' },
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
    const projectButton = screen.getAllByText(/Stateful Architecture/i)[0];
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

    // Type prompt into textarea and send
    const textarea = screen.getByPlaceholderText(/Ask AURA in this chat…/i);
    fireEvent.change(textarea, { target: { value: 'Explain state persistence in AURA' } });

    const sendBtn = screen.getByRole('button', { name: /Send/i });
    await act(async () => {
      fireEvent.click(sendBtn);
    });

    // Verify chat payload sent to /v1/chat
    expect(chatPayload).not.toBeNull();
    expect(chatPayload.message).toBe('Explain state persistence in AURA');
    expect(chatPayload.session_id).toBeDefined();

    // Verify response rendered in v9.1 UI
    expect(await screen.findByText(/Live backend synthesis response for project architecture/i)).toBeInTheDocument();

    // Verify execution badge
    expect(await screen.findByText(/AURA · 2 steps/i)).toBeInTheDocument();
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

  it.each([
    ['ModelCapabilityMismatch', 'Choose a compatible model or adjust the request requirements.'],
    ['ReasoningControlUnsupported', 'Use Profile reasoning or choose a model with known support.'],
    ['ModelUnavailable', 'AURA did not substitute another model.'],
    ['NoEligibleRoute', 'Review the profile in Routing Studio.'],
  ])('shows actionable guidance for %s without exposing raw error JSON', async (code, guidance) => {
    global.fetch = vi.fn().mockImplementation((url: string) => {
      if (url.includes('/v1/models')) return Promise.resolve({ ok: true, json: () => Promise.resolve({ providers: [] }) });
      if (url.includes('/v1/sessions')) return Promise.resolve({ ok: true, json: () => Promise.resolve([]) });
      if (url.includes('/v1/memory')) return Promise.resolve({ ok: true, json: () => Promise.resolve([]) });
      if (url.includes('/v1/chat')) return Promise.resolve({ ok: false, status: 400, text: () => Promise.resolve(JSON.stringify({ error: code, message: `Routing rejected: ${code}`, details: { internal: 'detail' } })) });
      return Promise.resolve({ ok: true, json: () => Promise.resolve({}) });
    });
    await act(async () => { render(<App />); });
    fireEvent.click(screen.getAllByText(/Stateful Architecture/i)[0]);
    fireEvent.click(screen.getByRole('button', { name: /Open project chats/i }));
    fireEvent.click(screen.getByTitle('New chat'));
    fireEvent.change(screen.getByPlaceholderText(/Ask AURA in this chat…/i), { target: { value: 'Route this request' } });
    await act(async () => { fireEvent.click(screen.getByRole('button', { name: /Send/i })); });
    expect(await screen.findByText(new RegExp(`Routing rejected: ${code}`))).toBeInTheDocument();
    expect(screen.getByText(new RegExp(guidance))).toBeInTheDocument();
    expect(screen.queryByText(/"internal"\s*:/)).not.toBeInTheDocument();
  });
});
