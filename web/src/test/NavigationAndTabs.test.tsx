import { render, screen, fireEvent, act, waitFor, within } from '@testing-library/react';
import { describe, it, expect, vi, beforeEach } from 'vitest';
import App from '../App';
import * as folderConn from '../lib/folderConnections';

async function openWorkspaceSearch() {
  fireEvent.click(screen.getByRole('button', { name: /Search anything/i }));
  return screen.findByRole('textbox', { name: 'Search saved workspace content' });
}

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

  it('renders the V16 shell navigation without browser tabs or an address bar', async () => {
    await act(async () => {
      render(<App />);
    });

    const nav = screen.getByRole('navigation', { name: 'Personal workspace navigation' });
    for (const label of ['Home', 'Conversation', 'Projects', 'Notes', 'Library', 'Automations', 'Preferences']) {
      expect(within(nav).getByTitle(label)).toBeInTheDocument();
    }
    expect(nav).toBeInTheDocument();
    expect(document.querySelector('.workspace-chrome')).not.toBeInTheDocument();
    expect(screen.queryByPlaceholderText(/enter a URL/i)).not.toBeInTheDocument();
  });

  it('opens the all-project conversation workspace and selects a saved live thread in place', async () => {
    window.localStorage.setItem('aura-v7-chats', JSON.stringify([{
      id: 'live-thread-a', projectId: 'stateful', title: 'Saved architecture decision',
      summary: 'A persisted project conversation', updated: 'just now', messages: [], source: 'live', sessionId: 'session-live-a',
    }]));
    await act(async () => { render(<App />); });

    fireEvent.click(within(screen.getByRole('navigation', { name: 'Personal workspace navigation' })).getByTitle('Conversation'));
    expect(await screen.findByRole('heading', { name: 'Conversations' })).toBeInTheDocument();
    const scope = screen.getByRole('combobox', { name: 'Conversation project scope' });
    expect(scope).toHaveValue('');
    const savedThread = await waitFor(() => document.querySelector<HTMLButtonElement>('.conversation-v16__thread'));
    expect(savedThread).not.toBeNull();
    fireEvent.click(savedThread!);

    await waitFor(() => expect(screen.getByRole('combobox', { name: 'Conversation project scope' })).toHaveValue(''));
    expect(document.querySelector('.project-chat-workspace')).toBeInTheDocument();
    expect(document.querySelector('.project-chat-workspace--rail-hidden')).toBeInTheDocument();
  });

  it('runs a real workspace search from the V16 search action and displays backend results', async () => {
    const searchResults = [{
      object_id: 'object-search-1', object_type: 'manual_note', title: 'A saved finding',
      excerpt: 'This contains the phrase unique omnibox search.', project_name: null,
      created_by: 'user', updated_at: '2026-10-01T12:00:00Z',
    }];
    global.fetch = vi.fn().mockImplementation((url: string) => {
      if (url.includes('/v1/workspace/search')) return Promise.resolve({ ok: true, json: () => Promise.resolve(searchResults) });
      if (url.includes('/v1/workspace/projects')) return Promise.resolve({ ok: true, json: () => Promise.resolve([]) });
      if (url.includes('/v1/models')) return Promise.resolve({ ok: true, json: () => Promise.resolve({ providers: [] }) });
      if (url.includes('/v1/sessions') || url.includes('/v1/memory') || url.includes('/v1/workspace/notes') || url.includes('/v1/workspace/library')) {
        return Promise.resolve({ ok: true, json: () => Promise.resolve([]) });
      }
      return Promise.resolve({ ok: true, json: () => Promise.resolve({}) });
    });
    await act(async () => { render(<App />); });

    const input = await openWorkspaceSearch();
    fireEvent.change(input, { target: { value: 'unique omnibox search' } });
    await act(async () => { fireEvent.submit(input.closest('form')!); });

    expect(await screen.findByText('A saved finding')).toBeInTheDocument();
    expect(global.fetch).toHaveBeenCalledWith(expect.stringContaining('/v1/workspace/search?query=unique+omnibox+search'));
  });

  it('loads later pages from the backend workspace search', async () => {
    const first = {
      object_id: 'search-page-one', object_type: 'manual_note', title: 'First saved result',
      excerpt: 'First page matching phrase.', project_name: null, created_by: 'user', updated_at: '2026-10-01T12:00:00Z',
    };
    const second = { ...first, object_id: 'search-page-two', title: 'Older saved result', excerpt: 'Later page matching phrase.' };
    global.fetch = vi.fn().mockImplementation((input: RequestInfo | URL) => {
      const url = String(input);
      if (url.startsWith('/v1/workspace/search?')) {
        const params = new URL(url, 'http://aura.test').searchParams;
        return Promise.resolve({
          ok: true,
          headers: new Headers(params.has('cursor') ? {} : { 'X-Next-Cursor': 'search-older-page' }),
          json: () => Promise.resolve(params.has('cursor') ? [second] : [first]),
        } as Response);
      }
      if (url.includes('/v1/models')) return Promise.resolve({ ok: true, json: () => Promise.resolve({ providers: [] }) } as Response);
      if (url.includes('/v1/sessions') || url.includes('/v1/memory')) return Promise.resolve({ ok: true, json: () => Promise.resolve([]) } as Response);
      return Promise.resolve({ ok: true, headers: new Headers(), json: () => Promise.resolve([]) } as Response);
    });
    await act(async () => { render(<App />); });

    const input = await openWorkspaceSearch();
    fireEvent.change(input, { target: { value: 'matching phrase' } });
    await act(async () => { fireEvent.submit(input.closest('form')!); });
    expect(await screen.findByText('First saved result')).toBeInTheDocument();
    await waitFor(() => expect(global.fetch).toHaveBeenCalledWith('/v1/workspace/search?query=matching+phrase&limit=25'));

    fireEvent.click(screen.getByRole('button', { name: 'Load more results' }));
    expect(await screen.findByText('Older saved result')).toBeInTheDocument();
    await waitFor(() => expect(global.fetch).toHaveBeenCalledWith('/v1/workspace/search?query=matching+phrase&limit=25&cursor=search-older-page'));
    expect(screen.getByText('First saved result')).toBeInTheDocument();
  });

  it('merges indexed connected-folder metadata and opens the original file on demand', async () => {
    const indexedFile: folderConn.IndexedFolderFile = {
      connectionId: 'folder-1', connectionName: 'Research', relativePath: 'papers/overview.pdf',
      name: 'overview.pdf', size: 512, lastModified: 1760000000000, mimeType: 'application/pdf',
    };
    vi.spyOn(folderConn, 'searchDirectoryIndexes').mockResolvedValue([indexedFile]);
    const openFile = vi.spyOn(folderConn, 'openIndexedFolderFile').mockResolvedValue(new File(['contents'], 'overview.pdf', { type: 'application/pdf' }));
    const originalCreateObjectURL = URL.createObjectURL;
    Object.defineProperty(URL, 'createObjectURL', { configurable: true, value: vi.fn(() => 'blob:aura-folder-file') });
    global.fetch = vi.fn().mockImplementation((url: string) => {
      if (url.includes('/v1/workspace/search')) return Promise.resolve({ ok: true, json: () => Promise.resolve([]) });
      if (url.includes('/v1/workspace/projects')) return Promise.resolve({ ok: true, json: () => Promise.resolve([]) });
      if (url.includes('/v1/models')) return Promise.resolve({ ok: true, json: () => Promise.resolve({ providers: [] }) });
      if (url.includes('/v1/sessions') || url.includes('/v1/memory') || url.includes('/v1/workspace/notes') || url.includes('/v1/workspace/library')) {
        return Promise.resolve({ ok: true, json: () => Promise.resolve([]) });
      }
      return Promise.resolve({ ok: true, json: () => Promise.resolve({}) });
    });
    await act(async () => { render(<App />); });

    const input = await openWorkspaceSearch();
    fireEvent.change(input, { target: { value: 'overview.pdf' } });
    await act(async () => { fireEvent.submit(input.closest('form')!); });
    fireEvent.click(await screen.findByRole('button', { name: /overview\.pdf/ }));
    await waitFor(() => expect(openFile).toHaveBeenCalledWith(indexedFile));
    Object.defineProperty(URL, 'createObjectURL', { configurable: true, value: originalCreateObjectURL });
  });

  it('opens a persisted search match at its node in the project Board', async () => {
    const project = { id: 'search-project', name: 'Search Project', subtitle: 'Indexed workspace', created_at: '2026-10-01T00:00:00Z', updated_at: '2026-10-01T00:00:00Z' };
    const object = { id: 'search-match-1', project_name: project.name, session_id: null, source_message_id: null, object_type: 'context_bridge', created_by: 'user', title: 'Bridge match', content: '', metadata_json: { bridge_options: { conclusions: true }, bridge_sections: { conclusions: 'Keep this conclusion.' } }, created_at: '2026-10-01T00:00:00Z', updated_at: '2026-10-01T00:00:00Z' };
    global.fetch = vi.fn().mockImplementation((url: string) => {
      if (url.includes('/v1/workspace/search')) return Promise.resolve({ ok: true, json: () => Promise.resolve([{ object_id: object.id, object_type: object.object_type, title: object.title, excerpt: 'Keep this conclusion.', project_name: project.name, created_by: 'user', updated_at: object.updated_at }]) });
      if (url.includes('/v1/workspace/projects/') && url.includes('/graph')) return Promise.resolve({ ok: true, json: () => Promise.resolve({ project_name: project.name, objects: [object], edges: [], layout: { project_name: project.name, layout: {}, revision: 0, updated_at: null }, execution_traces: [] }) });
      if (url.includes('/v1/workspace/projects')) return Promise.resolve({ ok: true, json: () => Promise.resolve([project]) });
      if (url.includes('/v1/models')) return Promise.resolve({ ok: true, json: () => Promise.resolve({ providers: [] }) });
      if (url.includes('/v1/sessions') || url.includes('/v1/memory') || url.includes('/v1/workspace/notes') || url.includes('/v1/workspace/library')) {
        return Promise.resolve({ ok: true, json: () => Promise.resolve([]) });
      }
      return Promise.resolve({ ok: true, json: () => Promise.resolve({}) });
    });
    await act(async () => { render(<App />); });

    const input = await openWorkspaceSearch();
    fireEvent.change(input, { target: { value: 'bridge match unique' } });
    await act(async () => { fireEvent.submit(input.closest('form')!); });
    fireEvent.click(await screen.findByRole('button', { name: /Bridge match/ }));

    const projectNavigation = await screen.findByRole('navigation', { name: 'Project navigation' });
    expect(projectNavigation.querySelector('button.is-active')).toHaveTextContent('Board');
    await waitFor(() => expect(global.fetch).toHaveBeenCalledWith(expect.stringContaining('/v1/workspace/projects/Search%20Project/graph')));
    await waitFor(() => expect(document.querySelector('[data-id="search-match-1"]')).toHaveClass('selected'), { timeout: 5000 });
  });

  it('opens a project-scoped manual note at its node in the project Board', async () => {
    const project = { id: 'note-project', name: 'Note Project', subtitle: 'Project notes', created_at: '2026-10-02T00:00:00Z', updated_at: '2026-10-02T00:00:00Z' };
    const note = { id: 'board-note-search-match', project_name: project.name, session_id: null, source_message_id: null, object_type: 'manual_note', created_by: 'user', title: 'Board note match', content: 'Project-specific constraints.', metadata_json: {}, created_at: '2026-10-02T00:00:00Z', updated_at: '2026-10-02T00:00:00Z' };
    global.fetch = vi.fn().mockImplementation((url: string) => {
      if (url.includes('/v1/workspace/search')) return Promise.resolve({ ok: true, json: () => Promise.resolve([{ object_id: note.id, object_type: note.object_type, title: note.title, excerpt: note.content, project_name: project.name, created_by: 'user', updated_at: note.updated_at }]) });
      if (url.includes('/v1/workspace/projects/') && url.includes('/graph')) return Promise.resolve({ ok: true, json: () => Promise.resolve({ project_name: project.name, objects: [note], edges: [], layout: { project_name: project.name, layout: {}, revision: 0, updated_at: null }, execution_traces: [] }) });
      if (url.includes('/v1/workspace/projects')) return Promise.resolve({ ok: true, json: () => Promise.resolve([project]) });
      if (url.includes('/v1/models')) return Promise.resolve({ ok: true, json: () => Promise.resolve({ providers: [] }) });
      if (url.includes('/v1/sessions') || url.includes('/v1/memory') || url.includes('/v1/workspace/notes') || url.includes('/v1/workspace/library')) {
        return Promise.resolve({ ok: true, json: () => Promise.resolve([]) });
      }
      return Promise.resolve({ ok: true, json: () => Promise.resolve({}) });
    });
    await act(async () => { render(<App />); });

    const input = await openWorkspaceSearch();
    fireEvent.change(input, { target: { value: 'board note match' } });
    await act(async () => { fireEvent.submit(input.closest('form')!); });
    fireEvent.click(await screen.findByRole('button', { name: /Board note match/ }));

    const projectNavigation = await screen.findByRole('navigation', { name: 'Project navigation' });
    expect(projectNavigation.querySelector('button.is-active')).toHaveTextContent('Board');
    await waitFor(() => expect(global.fetch).toHaveBeenCalledWith(expect.stringContaining('/v1/workspace/projects/Note%20Project/graph')));
    await waitFor(() => expect(document.querySelector('[data-id="board-note-search-match"]')).toHaveClass('selected'));
  });

  it('opening a project shows one project overview in the V16 page shell', async () => {
    await act(async () => {
      render(<App />);
    });

    const projectButton = screen.getByTitle('Stateful Architecture');
    await act(async () => { fireEvent.click(projectButton); });

    expect(await screen.findByRole('heading', { name: 'Stateful Architecture' })).toBeInTheDocument();
    expect(screen.getByRole('navigation', { name: 'Project navigation' })).toBeInTheDocument();
    expect(document.querySelector('.workspace-chrome')).not.toBeInTheDocument();
  });

  it('project navigation switches among overview, conversations, Board, Split, and Files', async () => {
    await act(async () => {
      render(<App />);
    });

    const projectButton = screen.getByTitle('Stateful Architecture');
    await act(async () => { fireEvent.click(projectButton); });
    const clickProjectTab = async (label: string) => {
      const currentNav = await screen.findByRole('navigation', { name: 'Project navigation' });
      fireEvent.click(within(currentNav).getByRole('button', { name: label }));
      await waitFor(() => expect(screen.getByRole('navigation', { name: 'Project navigation' }).querySelector('button.is-active')).toHaveTextContent(label));
    };

    await clickProjectTab('Conversations');
    await clickProjectTab('Board');
    expect(document.querySelector('.routing-trigger-wrap')).not.toBeInTheDocument();
    expect(document.querySelector('.inspector-toggle')).not.toBeInTheDocument();
    await clickProjectTab('Split');
    expect(document.querySelector('.routing-trigger-wrap')).not.toBeInTheDocument();
    expect(document.querySelector('.inspector-toggle')).not.toBeInTheDocument();
    await clickProjectTab('Files');
    await clickProjectTab('Overview');
    expect(document.querySelector('.workspace-chrome')).not.toBeInTheDocument();
  });

  it('searches every Library reference linked to the project from Project Files', async () => {
    const match = {
      id: 'far-project-file', name: 'A far-page source', kind: 'PDF', collection: 'Research',
      detail: 'Contains the old unique phrase', tags: ['reference'], project_names: ['Stateful Architecture'],
      size: 2048, mime_type: 'application/pdf', revision: 1, created_at: '2026-10-02T00:00:00Z', updated_at: '2026-10-02T00:00:00Z',
    };
    const olderMatch = { ...match, id: 'older-project-file', name: 'An older source' };
    global.fetch = vi.fn().mockImplementation((input: RequestInfo | URL) => {
      const url = String(input);
      if (url.startsWith('/v1/workspace/library?')) {
        const params = new URL(url, 'http://aura.test').searchParams;
        if (params.has('q')) return Promise.resolve({
          ok: true,
          headers: new Headers(params.has('cursor') ? {} : { 'X-Next-Cursor': 'older-file-page' }),
          json: () => Promise.resolve(params.has('cursor') ? [olderMatch] : [match]),
        } as Response);
        return Promise.resolve({ ok: true, headers: new Headers(), json: () => Promise.resolve([]) } as Response);
      }
      if (url.includes('/v1/models')) return Promise.resolve({ ok: true, json: () => Promise.resolve({ providers: [] }) } as Response);
      if (url.includes('/v1/sessions')) return Promise.resolve({ ok: true, json: () => Promise.resolve([]) } as Response);
      if (url.includes('/v1/memory')) return Promise.resolve({ ok: true, json: () => Promise.resolve([]) } as Response);
      return Promise.resolve({ ok: true, json: () => Promise.resolve({}) } as Response);
    });
    await act(async () => { render(<App />); });

    const projectButton = screen.getAllByText(/Stateful Architecture/i)[0].closest('button')!;
    await act(async () => { fireEvent.click(projectButton); });
    const filesButton = screen.getAllByRole('button').find((button) => button.textContent?.includes('Project + linked Library'))!;
    await act(async () => { fireEvent.click(filesButton); });

    fireEvent.change(screen.getByPlaceholderText('Search project files and artifacts'), { target: { value: 'old unique phrase' } });
    expect(await screen.findByText('A far-page source')).toBeInTheDocument();
    await waitFor(() => expect(global.fetch).toHaveBeenCalledWith('/v1/workspace/library?page_size=50&q=old+unique+phrase&project_name=Stateful+Architecture'));
    expect(screen.queryByText(/Search covers loaded Library references/)).not.toBeInTheDocument();

    fireEvent.click(screen.getByRole('button', { name: 'Load more matches' }));
    expect(await screen.findByText('An older source')).toBeInTheDocument();
    await waitFor(() => expect(global.fetch).toHaveBeenCalledWith('/v1/workspace/library?page_size=50&cursor=older-file-page&q=old+unique+phrase&project_name=Stateful+Architecture'));
  });

  it('searches all unlinked Library references from the project link picker', async () => {
    const candidate = {
      id: 'unloaded-library-candidate', name: 'A far-page source', kind: 'PDF', collection: 'Research',
      detail: 'Contains an unlinked unique phrase', tags: ['reference'], project_names: [],
      size: 2048, mime_type: 'application/pdf', revision: 1, created_at: '2026-10-02T00:00:00Z', updated_at: '2026-10-02T00:00:00Z',
    };
    global.fetch = vi.fn().mockImplementation((input: RequestInfo | URL, init?: RequestInit) => {
      const url = String(input);
      if (url.startsWith('/v1/workspace/library?')) {
        const params = new URL(url, 'http://aura.test').searchParams;
        if (params.has('unlinked_project_name') && params.has('q')) return Promise.resolve({
          ok: true,
          headers: new Headers(),
          json: () => Promise.resolve([candidate]),
        } as Response);
        return Promise.resolve({ ok: true, headers: new Headers(), json: () => Promise.resolve([]) } as Response);
      }
      if (url.includes(`/v1/workspace/library/${candidate.id}`) && init?.method === 'PUT') {
        const body = JSON.parse(String(init.body));
        return Promise.resolve({ ok: true, json: () => Promise.resolve({ ...candidate, project_names: body.project_names, revision: body.expected_revision + 1 }) } as Response);
      }
      if (url.includes('/v1/models')) return Promise.resolve({ ok: true, json: () => Promise.resolve({ providers: [] }) } as Response);
      if (url.includes('/v1/sessions')) return Promise.resolve({ ok: true, json: () => Promise.resolve([]) } as Response);
      if (url.includes('/v1/memory')) return Promise.resolve({ ok: true, json: () => Promise.resolve([]) } as Response);
      return Promise.resolve({ ok: true, json: () => Promise.resolve({}) } as Response);
    });
    await act(async () => { render(<App />); });

    const projectButton = screen.getAllByText(/Stateful Architecture/i)[0].closest('button')!;
    await act(async () => { fireEvent.click(projectButton); });
    const filesButton = screen.getAllByRole('button').find((button) => button.textContent?.includes('Project + linked Library'))!;
    await act(async () => { fireEvent.click(filesButton); });
    fireEvent.click(screen.getByRole('button', { name: /Link from Library/i }));
    fireEvent.change(screen.getByPlaceholderText('Search all unlinked Library files'), { target: { value: 'unlinked unique phrase' } });

    const result = await screen.findByRole('button', { name: /A far-page source/ });
    await waitFor(() => expect(global.fetch).toHaveBeenCalledWith('/v1/workspace/library?page_size=50&q=unlinked+unique+phrase&unlinked_project_name=Stateful+Architecture'));
    await act(async () => { fireEvent.click(result); });

    await waitFor(() => {
      const update = vi.mocked(global.fetch).mock.calls.find(([input, init]) => String(input).includes(`/v1/workspace/library/${candidate.id}`) && init?.method === 'PUT');
      expect(update).toBeDefined();
      expect(JSON.parse(String(update?.[1]?.body)).project_names).toContain('Stateful Architecture');
      expect(JSON.parse(String(update?.[1]?.body)).expected_revision).toBe(1);
    });
    expect(screen.queryByRole('button', { name: /A far-page source/ })).not.toBeInTheDocument();
  });


  it('file object opens its dedicated preview surface without a browser tab strip', async () => {
    await act(async () => {
      render(<App />);
    });

    // Click Library via sidebar title
    const libraryNav = screen.getByTitle('Library');
    await act(async () => {
      fireEvent.click(libraryNav);
    });

    // Click on a library item to open dedicated tab
    const fileItem = await screen.findByText(/German A1 Tracker/i);
    await act(async () => {
      fireEvent.click(fileItem.closest('button')!);
    });

    expect(await screen.findByRole('button', { name: /Open in browser/ })).toBeInTheDocument();
    expect(document.querySelector('.file-preview-view')).toBeInTheDocument();
    expect(document.querySelector('.workspace-chrome')).not.toBeInTheDocument();
  });

  it('exposes Preferences from the shell and leaves browser history controls out of the workspace', async () => {
    await act(async () => {
      render(<App />);
    });

    fireEvent.click(within(screen.getByRole('navigation', { name: 'Personal workspace navigation' })).getByTitle('Preferences'));
    expect(await screen.findByRole('heading', { name: 'Preferences' })).toBeInTheDocument();
    expect(screen.getByRole('heading', { name: 'API access' })).toBeInTheDocument();
    expect(screen.getByRole('heading', { name: 'Routing' })).toBeInTheDocument();
    expect(screen.queryByTitle('Back')).not.toBeInTheDocument();
    expect(screen.queryByTitle('Forward')).not.toBeInTheDocument();
  });

  it('preserves routing control in topbar and confirms old sidebar model picker is absent', async () => {
    await act(async () => {
      render(<App />);
    });

    // Open a project, then its conversations, so project controls are available.
    const projectButton = screen.getAllByText(/Stateful Architecture/i)[0].closest('button')!;
    await act(async () => {
      fireEvent.click(projectButton);
    });
    await act(async () => { fireEvent.click(screen.getByRole('button', { name: 'Conversations' })); });

    // Routing badge present in topbar
    expect(screen.getByText(/Routing…/i)).toBeInTheDocument();
    const reasoningControl = screen.getByRole('button', { name: 'Temporary reasoning override' });
    expect(reasoningControl).toHaveTextContent('Reasoning');
    expect(reasoningControl).toHaveTextContent('Profile');
    expect(screen.queryByText(/Model C/i)).not.toBeInTheDocument();

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

