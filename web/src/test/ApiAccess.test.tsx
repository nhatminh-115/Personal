import { cleanup, fireEvent, render, screen } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import { ApiAccessDialog } from '../components/global/ApiAccessDialog';
import { API_AUTH_REQUIRED_EVENT, api, getApiToken, setApiToken } from '../services/api';

function jsonResponse(body: unknown, status = 200): Response {
  if (status >= 400) {
    return {
      ok: false,
      status,
      text: vi.fn().mockResolvedValue(JSON.stringify(body)),
    } as unknown as Response;
  }

  return {
    ok: true,
    status,
    json: vi.fn().mockResolvedValue(body),
  } as unknown as Response;
}

describe('API access', () => {
  const fetchMock = vi.fn();

  beforeEach(() => {
    sessionStorage.clear();
    fetchMock.mockReset().mockResolvedValue(jsonResponse({}));
    vi.stubGlobal('fetch', fetchMock);
  });

  afterEach(() => {
    cleanup();
    sessionStorage.clear();
    vi.unstubAllGlobals();
  });

  it('sends API requests without an Authorization header when no token is saved', async () => {
    expect(setApiToken(null)).toBe(true);

    await api.fetchModels();

    expect(fetchMock).toHaveBeenCalledWith('/v1/models');
    expect(getApiToken()).toBeNull();
  });

  it('adds the saved bearer token to API requests', async () => {
    const token = 'aura-browser-token-' + 'x'.repeat(32);
    expect(setApiToken(token)).toBe(true);

    await api.fetchModels();

    const init = fetchMock.mock.calls[0]?.[1] as RequestInit | undefined;
    expect((init?.headers as Headers).get('Authorization')).toBe(`Bearer ${token}`);
    expect(getApiToken()).toBe(token);
  });

  it('signals the app when the API requires authentication', async () => {
    fetchMock.mockResolvedValueOnce(jsonResponse({
      detail: { code: 'api_auth_required', message: 'A valid API bearer token is required.' },
    }, 401));
    const authRequired = vi.fn();
    window.addEventListener(API_AUTH_REQUIRED_EVENT, authRequired);

    await expect(api.fetchModels()).rejects.toMatchObject({ status: 401, code: 'api_auth_required' });

    expect(authRequired).toHaveBeenCalledOnce();
    window.removeEventListener(API_AUTH_REQUIRED_EVENT, authRequired);
  });
});

describe('ApiAccessDialog', () => {
  it('shows a forget action for a saved token and invokes it', () => {
    const onForgetToken = vi.fn();
    render(<ApiAccessDialog open tokenConfigured onClose={vi.fn()} onSave={vi.fn()} onForgetToken={onForgetToken} />);

    fireEvent.click(screen.getByRole('button', { name: 'Forget token' }));

    expect(onForgetToken).toHaveBeenCalledOnce();
  });

  it('does not show a forget action when no token is saved', () => {
    render(<ApiAccessDialog open tokenConfigured={false} onClose={vi.fn()} onSave={vi.fn()} onForgetToken={vi.fn()} />);

    expect(screen.queryByRole('button', { name: 'Forget token' })).toBeNull();
  });

  it('closes with Escape', () => {
    const onClose = vi.fn();
    render(<ApiAccessDialog open tokenConfigured={false} onClose={onClose} onSave={vi.fn()} onForgetToken={vi.fn()} />);

    fireEvent.keyDown(window, { key: 'Escape' });

    expect(onClose).toHaveBeenCalledOnce();
  });

  it('rejects a short token without passing it to the app', () => {
    const onSave = vi.fn();
    render(<ApiAccessDialog open tokenConfigured={false} onClose={vi.fn()} onSave={onSave} onForgetToken={vi.fn()} />);

    fireEvent.change(screen.getByLabelText('Bearer token'), { target: { value: 'too-short' } });
    fireEvent.click(screen.getByRole('button', { name: 'Save and reload' }));

    expect(screen.getByRole('alert').textContent).toContain('at least 32 characters');
    expect(onSave).not.toHaveBeenCalled();
  });

  it('passes a valid token to the app without rendering it as text', () => {
    const token = 'aura-browser-token-' + 'y'.repeat(32);
    const onSave = vi.fn();
    render(<ApiAccessDialog open tokenConfigured={false} onClose={vi.fn()} onSave={onSave} onForgetToken={vi.fn()} />);

    fireEvent.change(screen.getByLabelText('Bearer token'), { target: { value: token } });
    fireEvent.click(screen.getByRole('button', { name: 'Save and reload' }));

    expect(onSave).toHaveBeenCalledWith(token);
    expect(screen.queryByText(token)).toBeNull();
  });
});
