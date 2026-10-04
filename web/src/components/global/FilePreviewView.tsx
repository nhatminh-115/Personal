import { ExternalLink, FileText, FolderOpen } from 'lucide-react';

export interface FilePreviewRecord {
  id: string;
  name: string;
  url: string;
  mimeType: string;
  virtualPath: string;
  sourceFile?: File;
}

interface FilePreviewViewProps {
  preview: FilePreviewRecord;
  onOpenExternal: () => void;
  onImportCopy?: (file: File, sourcePath: string) => void;
}

export function FilePreviewView({ preview, onOpenExternal, onImportCopy }: FilePreviewViewProps) {
  const image = preview.mimeType.startsWith('image/');
  const html = preview.mimeType === 'text/html' || preview.name.toLowerCase().endsWith('.html');
  const pdf = preview.mimeType === 'application/pdf';
  const embeddable = image || pdf || html;

  return (
    <section className="file-preview-view">
      <header className="file-preview-header">
        <div className="file-preview-title">
          <span className="file-preview-icon"><FileText size={19} /></span>
          <div><strong>{preview.name}</strong><span><FolderOpen size={13} /> {preview.virtualPath}</span></div>
        </div>
        <div className="file-preview-actions">
          {preview.sourceFile && onImportCopy ? <button className="secondary-button secondary-button--lg" type="button" onClick={() => onImportCopy(preview.sourceFile!, preview.virtualPath)}>Copy to Library</button> : null}
          <button className="secondary-button secondary-button--lg" type="button" onClick={onOpenExternal}><ExternalLink size={16} /> Open in browser</button>
        </div>
      </header>
      {preview.sourceFile && onImportCopy ? <p className="file-preview-source-note">Copying keeps a browser-local Library copy. The original file stays in the connected folder.</p> : null}
      <div className="file-preview-canvas">
        {image ? <img src={preview.url} alt={preview.name} /> : null}
        {!image && embeddable ? <iframe src={preview.url} title={preview.name} {...(html ? { sandbox: '' } : {})} /> : null}
        {!embeddable ? (
          <div className="file-preview-unsupported"><FileText size={38} /><strong>Preview is not available for this file type.</strong><span>The file is still part of the current AURA tab and can be opened with the browser/default handler.</span><button className="primary-soft-button" type="button" onClick={onOpenExternal}>Open file</button></div>
        ) : null}
      </div>
    </section>
  );
}
