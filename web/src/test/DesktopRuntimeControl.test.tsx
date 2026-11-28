import { beforeEach, describe, expect, it, vi } from 'vitest';
import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { api } from '../services/api';
import type { ModelCatalog } from '../types';

const desktop = vi.hoisted(() => ({
  invoke: vi.fn(),
  register: vi.fn(),
  unregister: vi.fn(),
  listen: vi.fn(),
}));

vi.mock('@tauri-apps/api/core', () => ({
  invoke: (...args: unknown[]) => desktop.invoke(...args),
  isTauri: () => true,
}));
vi.mock('@tauri-apps/api/event', () => ({ listen: (...args: unknown[]) => desktop.listen(...args) }));
vi.mock('@tauri-apps/api/window', () => ({
  getCurrentWindow: () => ({ show: vi.fn(), unminimize: vi.fn(), setFocus: vi.fn() }),
}));
vi.mock('@tauri-apps/plugin-autostart', () => ({ disable: vi.fn(), enable: vi.fn() }));
vi.mock('@tauri-apps/plugin-notification', () => ({
  isPermissionGranted: vi.fn().mockResolvedValue(true),
  requestPermission: vi.fn().mockResolvedValue('granted'),
  sendNotification: vi.fn(),
}));
vi.mock('@tauri-apps/plugin-global-shortcut', () => ({
  register: (...args: unknown[]) => desktop.register(...args),
  unregister: (...args: unknown[]) => desktop.unregister(...args),
}));
vi.mock('@tauri-apps/plugin-dialog', () => ({ confirm: vi.fn().mockResolvedValue(true) }));

import { DesktopRuntimeControl } from '../components/global/DesktopRuntimeControl';

const runtimeSnapshot = {
  phase: 'ready',
  message: 'Runtime ready',
  apiUrl: 'http://127.0.0.1:17890',
  dockerAvailable: true,
  provider: 'unconfigured',
  baseUrl: 'https://api.openai.com/v1',
  model: '',
  closeToTray: true,
  autostart: false,
  notifications: false,
  globalShortcut: 'CommandOrControl+Alt+A',
  hasProviderKey: false,
  logs: [],
};

describe('DesktopRuntimeControl settings', () => {
  beforeEach(() => {
    vi.restoreAllMocks();
    vi.clearAllMocks();
    window.sessionStorage.clear();
    desktop.listen.mockResolvedValue(() => {});
    desktop.register.mockResolvedValue(undefined);
    desktop.unregister.mockResolvedValue(undefined);
    desktop.invoke.mockImplementation(async (command: string) => {
      if (command === 'desktop_status' || command === 'desktop_save_windows_preferences' || command === 'desktop_restart' || command === 'desktop_set_provider_mode') return runtimeSnapshot;
      if (command === 'desktop_api_token') return 'test-token';
      throw new Error(`Unexpected desktop command: ${command}`);
    });
  });

  it('uses the restart command when the runtime is already ready', async () => {
    render(<DesktopRuntimeControl />);
    await waitFor(() => expect(desktop.invoke).toHaveBeenCalledWith('desktop_status'));

    fireEvent.click(screen.getByRole('button', { name: 'Kuractus Desktop runtime: Ready. Open runtime settings' }));
    fireEvent.click(screen.getByRole('button', { name: 'Restart runtime' }));

    await waitFor(() => expect(desktop.invoke).toHaveBeenCalledWith('desktop_restart'));
  });

  it('saves unrelated settings without unregistering and registering the unchanged global shortcut', async () => {
    const view = render(<DesktopRuntimeControl />);
    await waitFor(() => expect(desktop.register).toHaveBeenCalledTimes(1));

    fireEvent.click(screen.getByRole('button', { name: 'Kuractus Desktop runtime: Ready. Open runtime settings' }));
    fireEvent.click(screen.getByRole('checkbox', { name: /Close to tray/ }));
    fireEvent.click(screen.getByRole('button', { name: 'Save desktop settings' }));

    await waitFor(() => expect(desktop.invoke).toHaveBeenCalledWith('desktop_save_windows_preferences', expect.objectContaining({
      closeToTray: false,
      autostart: false,
      notifications: false,
      globalShortcut: 'CommandOrControl+Alt+A',
    })));
    expect(desktop.invoke).not.toHaveBeenCalledWith('desktop_restart');
    expect(desktop.invoke).not.toHaveBeenCalledWith('desktop_stop');
    expect(desktop.unregister).not.toHaveBeenCalled();
    expect(desktop.register).toHaveBeenCalledTimes(1);
    fireEvent.click(screen.getByRole('button', { name: 'Close desktop settings' }));
    expect(desktop.invoke).not.toHaveBeenCalledWith('desktop_stop');
    view.unmount();
  });

  it('does not open a settings dialog on startup and opens directly to AI Provider when requested', async () => {
    const view = render(<DesktopRuntimeControl />);
    await waitFor(() => expect(desktop.invoke).toHaveBeenCalledWith('desktop_status'));
    expect(screen.queryByRole('dialog')).not.toBeInTheDocument();
    view.unmount();

    render(<DesktopRuntimeControl providerSettingsRequest={1} />);
    const providerDialog = await screen.findByRole('dialog', { name: /AI Provider/ });
    expect(providerDialog).toBeInTheDocument();
    expect(providerDialog.parentElement?.parentElement).toBe(document.body);
    expect(screen.getByRole('tab', { name: 'AI Provider' })).toHaveAttribute('aria-selected', 'true');
    expect(screen.getByText(/Choose a provider, test the key/)).toBeInTheDocument();
    expect(screen.queryByText(/127\.0\.0\.1:17890/)).not.toBeInTheDocument();
    expect(screen.queryByRole('button', { name: 'Stop and preserve data' })).not.toBeInTheDocument();
  });

  it('connects with a secure key, discovers real models, and activates the model the user selects', async () => {
    const discovered: ModelCatalog = { providers: [{
      id: 'openai', label: 'OpenAI', kind: 'cloud', available: true, base_url: 'https://api.openai.com/v1', privacy_status: 'cloud',
      models: [
        { id: 'gpt-4o-2024-11-20', label: 'gpt-4o-2024-11-20', capabilities: ['general'], tool_support: 'supported', reasoning_support: 'fixed_by_model' },
        { id: 'gpt-4o-mini', label: 'gpt-4o-mini', capabilities: ['general'], tool_support: 'supported', reasoning_support: 'fixed_by_model' },
      ],
    }] };
    vi.spyOn(api, 'refreshModels').mockResolvedValue(discovered);
    desktop.invoke.mockImplementation(async (command: string, args?: Record<string, unknown>) => {
      if (command === 'desktop_status') return runtimeSnapshot;
      if (command === 'desktop_save_provider_connection') {
        const id = String(args?.connectionId);
        return { ...runtimeSnapshot, provider: 'openai', activeProviderConnectionId: id, providerConnections: [{ id, name: 'OpenAI', baseUrl: 'https://api.openai.com/v1', model: String(args?.model), hasApiKey: true }] };
      }
      if (command === 'desktop_api_token') return 'test-token';
      throw new Error(`Unexpected desktop command: ${command}`);
    });
    const onModelsChanged = vi.fn();
    render(<DesktopRuntimeControl providerSettingsRequest={1} onModelsChanged={onModelsChanged} />);
    await screen.findByRole('dialog', { name: /AI Provider/ });
    fireEvent.change(screen.getByLabelText('Provider'), { target: { value: 'openai' } });
    fireEvent.change(screen.getByPlaceholderText('Paste your OpenAI API key'), { target: { value: 'sk-private-test' } });
    fireEvent.click(screen.getByRole('button', { name: 'Connect and discover models' }));

    await waitFor(() => expect(api.refreshModels).toHaveBeenCalledOnce());
    await waitFor(() => expect(screen.getByText('2 models discovered. Choose one to use in conversations.')).toBeInTheDocument());
    expect(desktop.invoke).toHaveBeenCalledWith('desktop_save_provider_connection', expect.objectContaining({
      name: 'OpenAI',
      model: 'gpt-4o-mini',
      providerApiKey: 'sk-private-test',
      activate: true,
    }));
    expect(screen.getByRole('button', { name: 'Provider model' })).toHaveTextContent('GPT-4o · Nov 2024');
    expect(screen.queryByText('gpt-4o-2024-11-20')).not.toBeInTheDocument();
    expect(screen.queryByText('sk-private-test')).not.toBeInTheDocument();

    fireEvent.click(screen.getByRole('button', { name: 'Provider model' }));
    fireEvent.click(screen.getByRole('option', { name: 'GPT-4o · Nov 2024' }));
    fireEvent.click(screen.getByRole('button', { name: 'Use selected model' }));
    const firstConnectionId = String((desktop.invoke.mock.calls.find(([command]) => command === 'desktop_save_provider_connection')?.[1] as Record<string, unknown>)?.connectionId);
    await waitFor(() => expect(desktop.invoke).toHaveBeenCalledWith('desktop_save_provider_connection', expect.objectContaining({
      connectionId: firstConnectionId,
      model: 'gpt-4o-2024-11-20',
      activate: true,
    })));
    expect(onModelsChanged).toHaveBeenCalledWith(discovered);
  });

  it('does not present a rejected provider key as a connected model or expose the key in errors', async () => {
    vi.spyOn(api, 'refreshModels').mockResolvedValue({ providers: [{
      id: 'openai', label: 'OpenAI', kind: 'cloud', available: false, base_url: 'https://api.openai.com/v1', privacy_status: 'cloud', models: [],
    }] });
    desktop.invoke.mockImplementation(async (command: string, args?: Record<string, unknown>) => {
      if (command === 'desktop_status') return runtimeSnapshot;
      if (command === 'desktop_save_provider_connection') {
        const id = String(args?.connectionId);
        return { ...runtimeSnapshot, provider: 'openai', activeProviderConnectionId: id, providerConnections: [{ id, name: 'OpenAI', baseUrl: 'https://api.openai.com/v1', model: String(args?.model), hasApiKey: true }] };
      }
      if (command === 'desktop_api_token') return 'test-token';
      throw new Error(`Unexpected desktop command: ${command}`);
    });
    render(<DesktopRuntimeControl providerSettingsRequest={1} />);
    await screen.findByRole('dialog', { name: /AI Provider/ });
    fireEvent.change(screen.getByLabelText('Provider'), { target: { value: 'openai' } });
    fireEvent.change(screen.getByPlaceholderText('Paste your OpenAI API key'), { target: { value: 'sk-rejected-private' } });
    fireEvent.click(screen.getByRole('button', { name: 'Connect and discover models' }));

    expect(await screen.findByRole('alert')).toHaveTextContent('Could not connect to this provider. Check the API key and endpoint');
    expect(screen.queryByText('sk-rejected-private')).not.toBeInTheDocument();
    expect(screen.queryByRole('button', { name: 'Provider model' })).not.toBeInTheDocument();
  });
});
