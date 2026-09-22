import { ExternalLink, FileText, FolderOpen } from 'lucide-react';

export interface FilePreviewRecord {
  id: string;
  name: string;
  url: string;
  mimeType: string;
  virtualPath: string;
}

interface FilePreviewViewProps {
  preview: FilePreviewRecord;
  onOpenExternal: () => void;
}

export function FilePreviewView({ preview, onOpenExternal }: FilePreviewViewProps) {
  const image = preview.mimeType.startsWith('image/');
  const embeddable = image || preview.mimeType === 'application/pdf' || preview.mimeType === 'text/html' || preview.name.toLowerCase().endsWith('.html');

  return (
    <section className="file-preview-view">
      <header className="file-preview-header">
        <div className="file-preview-title">
          <span className="file-preview-icon"><FileText size={19} /></span>
          <div><strong>{preview.name}</strong><span><FolderOpen size={13} /> {preview.virtualPath}</span></div>
        </div>
        <button className="secondary-button secondary-button--lg" type="button" onClick={onOpenExternal}><ExternalLink size={16} /> Open in browser</button>
      </header>
      <div className="file-preview-canvas">
        {image ? <img src={preview.url} alt={preview.name} /> : null}
        {!image && embeddable ? <iframe src={preview.url} title={preview.name} /> : null}
        {!embeddable ? (
          <div className="file-preview-unsupported"><FileText size={38} /><strong>Preview is not available for this file type.</strong><span>The file is still part of the current AURA tab and can be opened with the browser/default handler.</span><button className="primary-soft-button" type="button" onClick={onOpenExternal}>Open file</button></div>
        ) : null}
      </div>
    </section>
  );
}
