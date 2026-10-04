import { fireEvent, render, screen } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';
import { FilePreviewView } from '../components/global/FilePreviewView';

describe('connected file preview', () => {
  it('offers an explicit browser-local Library copy while retaining the source path', () => {
    const file = new File(['private folder text'], 'notes.txt', { type: 'text/plain' });
    const onImportCopy = vi.fn();
    render(<FilePreviewView
      preview={{ id: 'connected-1', name: file.name, url: 'blob:preview', mimeType: file.type, virtualPath: 'Research / notes.txt', sourceFile: file }}
      onOpenExternal={vi.fn()}
      onImportCopy={onImportCopy}
    />);

    expect(screen.getByText('Copying keeps a browser-local Library copy. The original file stays in the connected folder.')).toBeInTheDocument();
    fireEvent.click(screen.getByRole('button', { name: 'Copy to Library' }));
    expect(onImportCopy).toHaveBeenCalledWith(file, 'Research / notes.txt');
  });

  it('does not offer copying for ordinary remote or Library file previews', () => {
    render(<FilePreviewView
      preview={{ id: 'remote-1', name: 'source.pdf', url: 'https://example.test/source.pdf', mimeType: 'application/pdf', virtualPath: 'Library / Research' }}
      onOpenExternal={vi.fn()}
    />);
    expect(screen.queryByRole('button', { name: 'Copy to Library' })).not.toBeInTheDocument();
  });

  it('sandboxes HTML previews while keeping PDF embedding available', () => {
    const { rerender } = render(<FilePreviewView
      preview={{ id: 'html-1', name: 'untrusted.html', url: 'blob:html', mimeType: 'text/html', virtualPath: 'Library / untrusted.html' }}
      onOpenExternal={vi.fn()}
    />);
    expect(screen.getByTitle('untrusted.html')).toHaveAttribute('sandbox', '');

    rerender(<FilePreviewView
      preview={{ id: 'pdf-1', name: 'report.pdf', url: 'blob:pdf', mimeType: 'application/pdf', virtualPath: 'Library / report.pdf' }}
      onOpenExternal={vi.fn()}
    />);
    expect(screen.getByTitle('report.pdf')).not.toHaveAttribute('sandbox');
  });
});
