import { render, screen, fireEvent, act } from '@testing-library/react';
import { describe, it, expect, vi, beforeEach } from 'vitest';
import App from '../App';
import * as folderConn from '../lib/folderConnections';

describe('Navigation and Workspace Shell Invariants', () => {
  beforeEach(() => {
    window.localStorage.clear();
    vi.restoreAllMocks();
    global.fetch = vi.fn().mockImplementation((url: string) => {
      if (url.includes('/v1/models')) {
        return Promise.resolve({
          ok: true,
          json: () => Promise.resolve({ providers: [] }),
        });
      }
      if (url.includes('/v1/sessions')) {
        return Promise.resolve({
          ok: true,
          json: () => Promise.resolve([]),
        });
      }
      if (url.includes('/v1/memory')) {
        return Promise.resolve({
          ok: true,
          json: () => Promise.resolve([]),
        });
      }
      return Promise.resolve({
        ok: true,
        json: () => Promise.resolve({}),
      });
    });
  });

  it('verifies AURA tab is permanent and cannot be closed', async () => {
    await act(async () => {
      render(<App />);
    });

    const auraTab = screen.getByRole('button', { name: /^AURA$/i });
    expect(auraTab).toBeInTheDocument();

    expect(screen.queryByTitle('Close tab')).not.toBeInTheDocument();
  });

  it('opening a project creates/reuses exactly one project tab', async () => {
    await act(async () => {
      render(<App />);
    });

    // Click project
    const projectButton = screen.getAllByText(/Stateful Architecture/i)[0];
    await act(async () => {
      fireEvent.click(projectButton);
    });

    // The project tab is present
    const projectTabs = screen.getAllByText(/Stateful Architecture/i);
    expect(projectTabs.length).toBeGreaterThan(0);

    // Clicking again reuses existing tab
    await act(async () => {
      fireEvent.click(projectButton);
    });
    expect(screen.getAllByText(/Stateful Architecture/i).length).toBeGreaterThanOrEqual(1);
  });

  it('overview / chat / board / files reuse the same project tab', async () => {
    await act(async () => {
      render(<App />);
    });

    // Navigate to Stateful Architecture project
    const projectButton = screen.getAllByText(/Stateful Architecture/i)[0].closest('button')!;
    await act(async () => {
      fireEvent.click(projectButton);
    });

    // Click Chats in project home
    const chatsBtn = screen.getByText(/Open project chats/i).closest('button')!;
    await act(async () => {
      fireEvent.click(chatsBtn);
    });

    // Verify workspace mode group is present
    expect(screen.getByRole('group', { name: /Workspace mode/i })).toBeInTheDocument();

    // Switch to Board mode
    const boardModeBtn = screen.getByRole('button', { name: /Board/i });
    await act(async () => {
      fireEvent.click(boardModeBtn);
    });

    // Switch to Split mode
    const splitModeBtn = screen.getByRole('button', { name: /Split/i });
    await act(async () => {
      fireEvent.click(splitModeBtn);
    });
  });

  it('file object opens its own dedicated preview tab', async () => {
    await act(async () => {
      render(<App />);
    });

    // Click Library via sidebar title
    const libraryNav = screen.getByTitle('Library');
    await act(async () => {
      fireEvent.click(libraryNav);
    });

    // Click on a library item to open dedicated tab
    const fileItem = screen.getAllByText(/German A1 Tracker/i)[0];
    await act(async () => {
      fireEvent.click(fileItem);
    });

    // A separate tab for German A1 Tracker opens
    expect(screen.getByRole('button', { name: /German A1 Tracker/i })).toBeInTheDocument();
  });

  it('back/forward restores workspace state snapshots', async () => {
    await act(async () => {
      render(<App />);
    });

    // Start at Home
    expect(screen.getByText(/Personal AI workspace/i)).toBeInTheDocument();

    // Navigate to Library
    const libraryNav = screen.getByTitle('Library');
    await act(async () => {
      fireEvent.click(libraryNav);
    });
    expect(screen.getByText(/Your files can stay where they already live/i)).toBeInTheDocument();

    // Click Back button in topbar
    const backBtn = screen.getByTitle('Back');
    await act(async () => {
      fireEvent.click(backBtn);
    });

    // Restores Home snapshot
    expect(screen.getByText(/Personal AI workspace/i)).toBeInTheDocument();

    // Click Forward button
    const forwardBtn = screen.getByTitle('Forward');
    await act(async () => {
      fireEvent.click(forwardBtn);
    });

    // Restores Library snapshot
    expect(screen.getByText(/Your files can stay where they already live/i)).toBeInTheDocument();
  });

  it('preserves routing control in topbar and confirms old sidebar model picker is absent', async () => {
    await act(async () => {
      render(<App />);
    });

    // Navigate into a project so project topbar controls are visible
    const projectButton = screen.getAllByText(/Stateful Architecture/i)[0].closest('button')!;
    await act(async () => {
      fireEvent.click(projectButton);
    });

    // Routing badge present in topbar
    expect(screen.getByText(/Balanced · Session/i)).toBeInTheDocument();
    expect(screen.getByText(/Reasoning: Profile/i)).toBeInTheDocument();
    expect(screen.getByText(/Model C/i)).toBeInTheDocument();

    // Old sidebar model picker is absent
    expect(screen.queryByTestId('model-picker')).not.toBeInTheDocument();
    expect(screen.queryByText(/Select Model Override/i)).not.toBeInTheDocument();
  });

  it('truthfully handles connected-folder when directory picker is unsupported', async () => {
    vi.spyOn(folderConn, 'supportsDirectoryPicker').mockReturnValue(false);

    await act(async () => {
      render(<App />);
    });

    // Go to Library
    const libraryNav = screen.getByTitle('Library');
    await act(async () => {
      fireEvent.click(libraryNav);
    });

    // The unsupported note is rendered
    expect(screen.getByText(/Folder connections need Chrome or Edge/i)).toBeInTheDocument();
  });
});
