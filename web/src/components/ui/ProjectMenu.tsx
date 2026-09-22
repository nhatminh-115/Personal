import { BookOpenText, Braces, FileStack, FlaskConical, Network, Sparkles } from 'lucide-react';

interface ProjectMenuProps {
  onSelect: (target: 'overview' | 'research' | 'experiment' | 'artifacts') => void;
}

const menuItems = [
  { id: 'overview' as const, title: 'Project overview', description: 'Constellation of active work', icon: Sparkles },
  { id: 'research' as const, title: 'Research cluster', description: 'TTT, recurrent memory, papers', icon: BookOpenText },
  { id: 'experiment' as const, title: 'Experiments', description: 'Toy implementation and benchmark', icon: Braces },
  { id: 'artifacts' as const, title: 'Context & artifacts', description: 'Notes, bridges and merge objects', icon: FileStack },
];

export function ProjectMenu({ onSelect }: ProjectMenuProps) {
  return (
    <div className="project-menu" role="menu">
      <div className="project-menu__header">
        <div className="project-menu__glyph"><Network size={15} /></div>
        <div>
          <span className="eyebrow">STATEFUL ARCHITECTURE</span>
          <strong>Open project surface</strong>
        </div>
      </div>
      <div className="project-menu__grid">
        {menuItems.map(({ id, title, description, icon: Icon }) => (
          <button type="button" role="menuitem" key={id} onClick={() => onSelect(id)}>
            <span className="project-menu__icon"><Icon size={16} /></span>
            <span><strong>{title}</strong><small>{description}</small></span>
          </button>
        ))}
      </div>
      <div className="project-menu__footer">
        <FlaskConical size={13} />
        <span>Local workspace · mock project data</span>
      </div>
    </div>
  );
}
