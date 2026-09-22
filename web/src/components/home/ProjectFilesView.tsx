import { ArrowLeft, ExternalLink, File, FileCode2, FileSpreadsheet, FileText, Link2, Plus, Search, Upload, X } from 'lucide-react';
import { useMemo, useRef, useState } from 'react';
import { projectArtifacts, type LibraryItem, type ProjectRecord } from '../../data/workspaceData';

interface ProjectFilesViewProps {
  project: ProjectRecord;
  libraryItems: LibraryItem[];
  onBack: () => void;
  onOpenItem: (item: LibraryItem) => void;
  onImportFiles: (files: File[], projectId: string) => void;
  onToggleProjectLink: (itemId: string, projectId: string) => void;
}

function iconForKind(kind: string) {
  if (kind === 'HTML' || kind === 'CODE') return FileCode2;
  if (kind === 'CSV') return FileSpreadsheet;
  if (kind === 'PDF' || kind === 'MD' || kind === 'NOTE') return FileText;
  return File;
}

export function ProjectFilesView({ project, libraryItems, onBack, onOpenItem, onImportFiles, onToggleProjectLink }: ProjectFilesViewProps) {
  const [query, setQuery] = useState('');
  const [linkOpen, setLinkOpen] = useState(false);
  const inputRef = useRef<HTMLInputElement | null>(null);
  const linked = useMemo(() => libraryItems.filter((item) => item.projectLinks?.includes(project.id)), [libraryItems, project.id]);
  const available = useMemo(() => libraryItems.filter((item) => !item.projectLinks?.includes(project.id)), [libraryItems, project.id]);
  const localArtifacts = useMemo(() => projectArtifacts.filter((item) => item.projectId === project.id), [project.id]);
  const q = query.trim().toLowerCase();
  const filteredLinked = linked.filter((item) => !q || `${item.name} ${item.detail}`.toLowerCase().includes(q));
  const filteredLocal = localArtifacts.filter((item) => !q || `${item.name} ${item.detail}`.toLowerCase().includes(q));

  return (
    <section className="project-files-view">
      <div className="project-files-head">
        <div>
          <button className="back-link" type="button" onClick={onBack}><ArrowLeft size={14} /> Project overview</button>
          <span className="eyebrow">PROJECT FILES</span>
          <h1>{project.name}</h1>
          <p>Project-local artifacts stay here. Personal files are linked from Library instead of duplicated.</p>
        </div>
        <div className="project-files-actions">
          <input
            ref={inputRef}
            type="file"
            multiple
            hidden
            onChange={(event) => {
              const files = Array.from(event.target.files ?? []) as File[];
              if (files.length) onImportFiles(files, project.id);
              event.target.value = '';
            }}
          />
          <button className="soft-action-button" type="button" onClick={() => setLinkOpen((value) => !value)}><Link2 size={14} /> Link from Library</button>
          <button className="primary-soft-button" type="button" onClick={() => inputRef.current?.click()}><Upload size={14} /> Import & link</button>
        </div>
      </div>

      <label className="project-files-search"><Search size={14} /><input value={query} onChange={(event) => setQuery(event.target.value)} placeholder="Search project files and artifacts" /></label>

      {linkOpen ? (
        <div className="project-link-picker">
          <div className="project-link-picker__head"><span><strong>Link Library files</strong><small>Creates a reference; the original file remains in Personal Library.</small></span><button className="icon-button" type="button" onClick={() => setLinkOpen(false)}><X size={14} /></button></div>
          <div className="project-link-picker__list">
            {available.length ? available.map((item) => (
              <button key={item.id} type="button" onClick={() => onToggleProjectLink(item.id, project.id)}>
                <span className={`file-kind file-kind--${item.kind.toLowerCase()}`}>{item.kind}</span>
                <span><strong>{item.name}</strong><small>{item.collection} · {item.detail}</small></span>
                <Plus size={13} />
              </button>
            )) : <span className="empty-inline">Everything in Library is already linked to this project.</span>}
          </div>
        </div>
      ) : null}

      <div className="project-files-section">
        <div className="section-heading section-heading--compact"><div><span className="eyebrow">LINKED FROM LIBRARY</span><h2>{linked.length} personal files</h2></div><small>Reusable across projects</small></div>
        <div className="project-file-list">
          {filteredLinked.length ? filteredLinked.map((item) => {
            const Icon = iconForKind(item.kind);
            return (
              <div key={item.id} className="project-file-row">
                <span className="project-file-row__icon"><Icon size={16} /></span>
                <span className="project-file-row__copy"><strong>{item.name}</strong><small>{item.detail}</small><em>Library · {item.collection} · {item.updated}</em></span>
                <button type="button" onClick={() => onOpenItem(item)}><ExternalLink size={13} /> Open</button>
                <button className="unlink-button" type="button" onClick={() => onToggleProjectLink(item.id, project.id)}>Unlink</button>
              </div>
            );
          }) : <div className="empty-section">No linked Library files match this search.</div>}
        </div>
      </div>

      <div className="project-files-section">
        <div className="section-heading section-heading--compact"><div><span className="eyebrow">PROJECT-LOCAL</span><h2>{localArtifacts.length} working artifacts</h2></div><small>Code, generated results and project-only notes</small></div>
        <div className="project-file-list">
          {filteredLocal.map((item) => {
            const Icon = iconForKind(item.kind);
            return (
              <div key={item.id} className="project-file-row project-file-row--local">
                <span className="project-file-row__icon"><Icon size={16} /></span>
                <span className="project-file-row__copy"><strong>{item.name}</strong><small>{item.detail}</small><em>{item.origin === 'generated' ? 'Generated by AURA' : 'Project workspace'} · {item.updated}</em></span>
                {item.linkedLibraryId ? <span className="linked-badge"><Link2 size={11} /> linked to Library note</span> : <span className={`artifact-status artifact-status--${item.status ?? 'ready'}`}>{item.status ?? 'ready'}</span>}
              </div>
            );
          })}
        </div>
      </div>
    </section>
  );
}
