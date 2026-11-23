import { beforeEach, describe, expect, it, vi } from 'vitest';
import { fireEvent, render, screen, waitFor } from '@testing-library/react';

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
    vi.clearAllMocks();
    window.sessionStorage.clear();
    desktop.listen.mockResolvedValue(() => {});
    desktop.register.mockResolvedValue(undefined);
    desktop.unregister.mockResolvedValue(undefined);
    desktop.invoke.mockImplementation(async (command: string) => {
      if (command === 'desktop_status' || command === 'desktop_save_preferences') return runtimeSnapshot;
      if (command === 'desktop_api_token') return 'test-token';
      throw new Error(`Unexpected desktop command: ${command}`);
    });
  });

  it('saves unrelated settings without unregistering and registering the unchanged global shortcut', async () => {
    const view = render(<DesktopRuntimeControl />);
    await waitFor(() => expect(desktop.register).toHaveBeenCalledTimes(1));

    fireEvent.click(screen.getByRole('button', { name: 'AURA Desktop runtime: Ready. Open runtime settings' }));
    fireEvent.click(screen.getByRole('checkbox', { name: /Close to tray/ }));
    fireEvent.click(screen.getByRole('button', { name: 'Save settings & restart' }));

    await waitFor(() => expect(desktop.invoke).toHaveBeenCalledWith('desktop_save_preferences', expect.any(Object)));
    expect(desktop.unregister).not.toHaveBeenCalled();
    expect(desktop.register).toHaveBeenCalledTimes(1);
    view.unmount();
  });
});
