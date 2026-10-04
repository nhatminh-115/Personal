import { fireEvent, render, waitFor } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { ProjectChatWorkspace } from '../components/chat/ProjectChatWorkspace';
import { api } from '../services/api';
import type { AIContextItem } from '../types';

vi.mock('../services/api', () => ({
  api: { fetchWorkspaceObjectPage: vi.fn() },
}));

vi.mock('../lib/localFiles', () => ({
  getLocalFile: vi.fn().mockResolvedValue(new Blob(['Local note contents'])),
}));

vi.mock('../components/chat/ChatPane', () => ({
  ChatPane: (props: {
    contextItems?: AIContextItem[];
    onContextPanelOpenChange?: (open: boolean) => void;
    onContextObjectIdsChange?: (objectIds: string[]) => void;
    onContextFileContentIdsChange?: (objectIds: string[]) => void;
  }) => (
    <div>
      {props.contextItems?.map((item) => <span key={item.id}>{`${item.kind}|${item.title}|${item.detail}|${item.tokens}`}</span>)}
      <button onClick={() => props.onContextPanelOpenChange?.(true)}>Open context</button>
      <button onClick={() => props.onContextObjectIdsChange?.(['object-1'])}>Select object</button>
      <button onClick={() => props.onContextFileContentIdsChange?.(['file-reference-1'])}>Send file text</button>
    </div>
  ),
}));

const project = { id: 'project-1', name: 'AURA', title: 'AURA' } as any;
const thread = {
  id: 'thread-1',
  title: 'Live chat',
  summary: '',
  source: 'live',
  sessionId: 'session-1',
  messages: [],
  initialContextObjectIds: [],
} as any;

function renderWorkspace(libraryItems: any[] = [], onContextFileContentIdsChange = vi.fn()) {
  return render(
    <ProjectChatWorkspace
      project={project}
      threads={[thread]}
      activeThreadId={thread.id}
      libraryItems={libraryItems}
      notes={[]}
      onSelectThread={vi.fn()}
      onNewThread={vi.fn()}
      onUpdateMessages={vi.fn()}
      onContextObjectIdsChange={vi.fn()}
      onContextFileContentIdsChange={onContextFileContentIdsChange}
    />,
  );
}

describe('live chat context loading', () => {
  beforeEach(() => vi.clearAllMocks());

  it('loads one object page when Context opens and does not reload it for selection changes', async () => {
    vi.mocked(api.fetchWorkspaceObjectPage).mockResolvedValue({
      objects: [{
        id: 'object-1',
        project_name: 'AURA',
        object_type: 'manual_note',
        created_by: 'user',
        title: 'Saved note',
        content: 'Note contents',
        metadata_json: {},
        created_at: '2026-10-03T00:00:00Z',
        updated_at: '2026-10-03T00:00:00Z',
      } as any],
      nextCursor: null,
    });

    const view = renderWorkspace();
    expect(api.fetchWorkspaceObjectPage).not.toHaveBeenCalled();

    fireEvent.click(view.getByRole('button', { name: 'Open context' }));
    await waitFor(() => expect(api.fetchWorkspaceObjectPage).toHaveBeenCalledWith('AURA', null));

    fireEvent.click(view.getByRole('button', { name: 'Select object' }));
    await waitFor(() => expect(api.fetchWorkspaceObjectPage).toHaveBeenCalledTimes(1));
  });

  it('labels Library file references as metadata-only context and estimates only the reference title', async () => {
    vi.mocked(api.fetchWorkspaceObjectPage).mockResolvedValue({
      objects: [{
        id: 'file-reference-1',
        project_name: null,
        object_type: 'file_reference',
        created_by: 'user',
        title: 'Local budget.pdf',
        content: '',
        metadata_json: { storage_location: 'browser_local' },
        created_at: '2026-10-03T00:00:00Z',
        updated_at: '2026-10-03T00:00:00Z',
      } as any],
      nextCursor: null,
    });

    const view = renderWorkspace();
    fireEvent.click(view.getByRole('button', { name: 'Open context' }));

    expect(await view.findByText(/file\|Local budget\.pdf\|file reference · metadata only/)).toHaveTextContent(
      'file reference · metadata only · this browser has no supported local text, PDF, Word document, or spreadsheet copy available|4',
    );
  });

  it('offers explicit text sending only for supported files stored in this browser', async () => {
    vi.mocked(api.fetchWorkspaceObjectPage).mockResolvedValue({
      objects: [{
        id: 'file-reference-1', project_name: null, object_type: 'file_reference', created_by: 'user',
        title: 'Local notes.md', content: '', metadata_json: { storage_location: 'browser_local' },
        created_at: '2026-10-03T00:00:00Z', updated_at: '2026-10-03T00:00:00Z',
      } as any],
      nextCursor: null,
    });
    const onSendFileContent = vi.fn();
    const view = renderWorkspace([{
      id: 'file-reference-1', name: 'Local notes', kind: 'MD', source: 'imported', blobKey: 'local-file-1', size: 100,
    }], onSendFileContent);
    fireEvent.click(view.getByRole('button', { name: 'Open context' }));

    const contextItem = await view.findByText(/file\|Local notes\.md\|browser-local text/);
    expect(contextItem).toHaveTextContent('stays here until you explicitly send it with a message');
    fireEvent.click(view.getByRole('button', { name: 'Send file text' }));
    expect(onSendFileContent).toHaveBeenCalledWith('thread-1', ['file-reference-1']);
  });

  it('offers browser-local PDF text extraction only for an imported PDF available in this browser', async () => {
    vi.mocked(api.fetchWorkspaceObjectPage).mockResolvedValue({
      objects: [{
        id: 'file-reference-1', project_name: null, object_type: 'file_reference', created_by: 'user',
        title: 'Local chapters.pdf', content: '', metadata_json: { storage_location: 'browser_local' },
        created_at: '2026-10-03T00:00:00Z', updated_at: '2026-10-03T00:00:00Z',
      } as any],
      nextCursor: null,
    });
    const onSendFileContent = vi.fn();
    const view = renderWorkspace([{
      id: 'file-reference-1', name: 'Local chapters', kind: 'PDF', source: 'imported', blobKey: 'local-pdf-1', size: 1_500,
    }], onSendFileContent);
    fireEvent.click(view.getByRole('button', { name: 'Open context' }));

    const contextItem = await view.findByText(/file\|Local chapters\.pdf\|browser-local PDF/);
    expect(contextItem).toHaveTextContent('text is extracted here only after you explicitly send it with a message');
    fireEvent.click(view.getByRole('button', { name: 'Send file text' }));
    expect(onSendFileContent).toHaveBeenCalledWith('thread-1', ['file-reference-1']);
  });

  it('offers browser-local Word text extraction only for an imported DOCX available in this browser', async () => {
    vi.mocked(api.fetchWorkspaceObjectPage).mockResolvedValue({
      objects: [{
        id: 'file-reference-1', project_name: null, object_type: 'file_reference', created_by: 'user',
        title: 'Local report.docx', content: '', metadata_json: { storage_location: 'browser_local' },
        created_at: '2026-10-03T00:00:00Z', updated_at: '2026-10-03T00:00:00Z',
      } as any],
      nextCursor: null,
    });
    const onSendFileContent = vi.fn();
    const view = renderWorkspace([{
      id: 'file-reference-1', name: 'Local report', kind: 'DOCX', source: 'imported', blobKey: 'local-docx-1', size: 1_500,
    }], onSendFileContent);
    fireEvent.click(view.getByRole('button', { name: 'Open context' }));

    const contextItem = await view.findByText(/file\|Local report\.docx\|browser-local Word document/);
    expect(contextItem).toHaveTextContent('text is extracted here only after you explicitly send it with a message');
    fireEvent.click(view.getByRole('button', { name: 'Send file text' }));
    expect(onSendFileContent).toHaveBeenCalledWith('thread-1', ['file-reference-1']);
  });

  it('offers browser-local spreadsheet extraction only for an imported XLSX available in this browser', async () => {
    vi.mocked(api.fetchWorkspaceObjectPage).mockResolvedValue({
      objects: [{
        id: 'file-reference-1', project_name: null, object_type: 'file_reference', created_by: 'user',
        title: 'Local budget.xlsx', content: '', metadata_json: { storage_location: 'browser_local' },
        created_at: '2026-10-05T00:00:00Z', updated_at: '2026-10-05T00:00:00Z',
      } as any],
      nextCursor: null,
    });
    const onSendFileContent = vi.fn();
    const view = renderWorkspace([{
      id: 'file-reference-1', name: 'Local budget', kind: 'XLSX', source: 'imported', blobKey: 'local-xlsx-1', size: 1_500,
    }], onSendFileContent);
    fireEvent.click(view.getByRole('button', { name: 'Open context' }));

    const contextItem = await view.findByText(/file\|Local budget\.xlsx\|browser-local spreadsheet/);
    expect(contextItem).toHaveTextContent('text is extracted here only after you explicitly send it with a message');
    fireEvent.click(view.getByRole('button', { name: 'Send file text' }));
    expect(onSendFileContent).toHaveBeenCalledWith('thread-1', ['file-reference-1']);
  });
});
