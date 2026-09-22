import { Activity, ArrowLeft, ChevronRight, Files, MessageSquareText, Sparkles, StickyNote } from 'lucide-react';
import type { CSSProperties } from 'react';
import { genericOrbit, projects, statefulOrbit } from '../../data/workspaceData';

interface ProjectHomeProps {
  projectId: string;
  chatCount: number;
  fileCount: number;
  noteCount: number;
  onBack: () => void;
  onOpenNode: (nodeId: string) => void;
  onOpenChats: () => void;
  onOpenFiles: () => void;
  onMockObject: (label: string) => void;
}

export function ProjectHome({ projectId, chatCount, fileCount, noteCount, onBack, onOpenNode, onOpenChats, onOpenFiles, onMockObject }: ProjectHomeProps) {
  const project = projects.find((item) => item.id === projectId) ?? projects[0];
  const items = project.id === 'stateful' ? statefulOrbit : genericOrbit;
  const inner = items.filter((item) => item.ring === 'inner');
  const outer = items.filter((item) => item.ring === 'outer');

  const renderItem = (item: (typeof items)[number], duration: string, reverse = false) => {
    const Icon = item.icon;
    const style = {
      '--orbit-angle': `${item.angle}deg`,
      '--orbit-radius': `${item.radius}px`,
      '--orbit-duration': duration,
      '--orbit-direction': reverse ? 'reverse' : 'normal',
    } as CSSProperties;

    return (
      <div className="orbit-anchor" key={item.id} style={style}>
        <button
          className={`orbit-item orbit-item--${item.status}`}
          type="button"
          onClick={() => item.targetNode ? onOpenNode(item.targetNode) : onMockObject(item.label)}
        >
          <span className="orbit-item__counter">
            <span className="orbit-item__icon"><Icon size={14} /></span>
            <span className="orbit-item__copy"><strong>{item.label}</strong><small>{item.detail}</small></span>
            <span className="orbit-item__status" />
          </span>
        </button>
      </div>
    );
  };

  return (
    <section className="project-home">
      <div className="project-home__header">
        <div>
          <div className="project-home__crumbs">
            <button type="button" onClick={onBack}><ArrowLeft size={13} /> All projects</button>
            <ChevronRight size={11} aria-hidden="true" />
            <span>Overview</span>
          </div>
          <h1>{project.name}</h1>
          <p>{project.subtitle}. Chats, files, notes and graph objects stay scoped here while reusable files remain in your Personal Library.</p>
        </div>
        <div className="project-overview-actions">
          <button className="soft-action-button" type="button" onClick={onOpenFiles}><Files size={14} /><span><strong>{fileCount} files</strong><small>Project + linked Library</small></span></button>
          <button className="primary-soft-button" type="button" onClick={onOpenChats}><MessageSquareText size={14} /> {chatCount} chats</button>
        </div>
      </div>

      <div className="project-summary-bar" aria-label="Project summary">
        <button type="button" onClick={onOpenChats}>
          <span className="project-summary-bar__icon"><MessageSquareText size={14} /></span>
          <span className="project-summary-bar__copy"><span>Chats</span><strong>{chatCount}</strong><small>Conversation threads</small></span>
        </button>
        <button type="button" onClick={onOpenFiles}>
          <span className="project-summary-bar__icon"><Files size={14} /></span>
          <span className="project-summary-bar__copy"><span>Files</span><strong>{fileCount}</strong><small>Linked + project-local</small></span>
        </button>
        <button type="button" onClick={() => onMockObject('Linked notes')}>
          <span className="project-summary-bar__icon"><StickyNote size={14} /></span>
          <span className="project-summary-bar__copy"><span>Notes</span><strong>{noteCount}</strong><small>Linked workspace notes</small></span>
        </button>
        <div className="project-summary-bar__status">
          <span className="project-summary-bar__icon"><Activity size={14} /></span>
          <span className="project-summary-bar__copy"><span>Status</span><strong>{project.status}</strong><small>Updated {project.updated}</small></span>
        </div>
      </div>

      <div className="orbit-stage" aria-label={`${project.name} project constellation`}>
        <div className="orbit-ring orbit-ring--one" />
        <div className="orbit-ring orbit-ring--two" />
        <div className="orbit-axis orbit-axis--x" />
        <div className="orbit-axis orbit-axis--y" />

        <div className="orbit-layer orbit-layer--inner">{inner.map((item) => renderItem(item, '52s'))}</div>
        <div className="orbit-layer orbit-layer--outer">{outer.map((item) => renderItem(item, '76s', true))}</div>

        <button className="orbit-core glow-surface" type="button" onClick={onOpenChats}>
          <span className="orbit-core__icon"><Sparkles size={17} /></span>
          <span className="eyebrow">AURA PROJECT</span>
          <strong>{project.name}</strong>
          <small>{project.subtitle}</small>
          <span className="orbit-core__meta">Open project chats →</span>
        </button>
      </div>

      <div className="project-home__footer">
        <div><span>Current thesis</span><strong>{project.thesis}</strong></div>
        <div><span>Next pressure test</span><strong>{project.next}</strong></div>
      </div>
    </section>
  );
}
