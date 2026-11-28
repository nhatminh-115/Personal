import { act, fireEvent, render, screen, within } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import App from '../App';
import { RoutingConfirmationNotice } from '../components/routing/RoutingConfirmationNotice';

function mockWorkspaceFetch() {
  global.fetch = vi.fn().mockImplementation((input: RequestInfo | URL) => {
    const url = String(input);
    if (url.includes('/v1/models')) {
      return Promise.resolve({ ok: true, json: () => Promise.resolve({ providers: [{
        id: 'local', label: 'Local', kind: 'local', available: true, base_url: 'local', privacy_status: 'local',
        models: [{ id: 'model-a', label: 'Model A', capabilities: [], tool_support: 'supported', reasoning_support: 'high' }],
      }] }) });
    }
    if (url.includes('/v1/memory') || url.includes('/v1/sessions')) {
      return Promise.resolve({ ok: true, headers: { get: () => null }, json: () => Promise.resolve([]) });
    }
    return Promise.resolve({ ok: true, json: () => Promise.resolve({}) });
  });
}

describe('model choice replaces the old routing controls', () => {
  beforeEach(() => {
    window.localStorage.clear();
    vi.restoreAllMocks();
    mockWorkspaceFetch();
  });

  it('shows conversation model and reasoning selectors without a routing profile UI', async () => {
    await act(async () => { render(<App />); });
    const navigation = screen.getByRole('navigation', { name: 'Personal workspace navigation' });
    await act(async () => { fireEvent.click(within(navigation).getByTitle('Preferences')); });
    expect(await screen.findByRole('heading', { name: 'Preferences' })).toBeInTheDocument();
    expect(screen.queryByText(/Routing Studio|Routing Profile|Winning scope/i)).not.toBeInTheDocument();

    const projectButton = screen.getAllByText(/Stateful Architecture/i)[0].closest('button')!;
    await act(async () => { fireEvent.click(projectButton); });
    const openProjectChats = (await screen.findByText(/Open project chats/i)).closest('button')!;
    await act(async () => { fireEvent.click(openProjectChats); });
    const composer = await screen.findByPlaceholderText(/Ask Kuractus in this chat/i);
    fireEvent.focus(composer);
    expect(screen.getByRole('button', { name: 'Conversation model' })).toHaveTextContent('Automatic');
    expect(screen.getByRole('button', { name: 'Conversation reasoning' })).toHaveTextContent('Auto');
    expect(document.querySelector('.routing-trigger-wrap')).not.toBeInTheDocument();
    expect(screen.queryByRole('button', { name: /Assistant work mode/i })).not.toBeInTheDocument();
    expect(screen.queryByText(/System Balanced|Winning scope|Routing Studio/i)).not.toBeInTheDocument();
  });

  it('keeps a clear approval before a cloud provider receives the message', () => {
    const onConfirm = vi.fn();
    const onCancel = vi.fn();
    render(<RoutingConfirmationNotice proposal={{ provider: 'OpenAI', model: 'GPT-4o' }} onConfirm={onConfirm} onCancel={onCancel} />);
    expect(screen.getByRole('alertdialog', { name: 'Use this cloud model?' })).toHaveTextContent('Nothing has been sent yet.');
    expect(screen.getByText((_, element) => element?.textContent === 'Selected model: GPT-4o · OpenAI')).toBeInTheDocument();
    fireEvent.click(screen.getByRole('button', { name: 'Approve and continue' }));
    expect(onConfirm).toHaveBeenCalledOnce();
    fireEvent.click(screen.getByRole('button', { name: 'Cancel run' }));
    expect(onCancel).toHaveBeenCalledOnce();
  });
});
