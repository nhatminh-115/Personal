import { Check, Layers3, LayoutGrid, Link2, Maximize, MousePointer2, NotebookPen, Redo2, Undo2 } from 'lucide-react';
import type { ReactNode } from 'react';
import type { LayerKey } from '../../types';

interface BoardToolbarProps {
  activeTool: 'select' | 'note' | 'link';
  onToolChange: (tool: 'select' | 'note' | 'link') => void;
  onAutoLayout: () => void;
  onFitView: () => void;
  onUndo: () => void;
  onRedo: () => void;
  canUndo: boolean;
  canRedo: boolean;
  layers: Record<LayerKey, boolean>;
  onLayerToggle: (layer: LayerKey) => void;
}

export function BoardToolbar({
  activeTool,
  onToolChange,
  onAutoLayout,
  onFitView,
  onUndo,
  onRedo,
  canUndo,
  canRedo,
  layers,
  onLayerToggle,
}: BoardToolbarProps) {
  return (
    <div className="board-toolbar">
      <div className="board-tools board-tools--gradient">
        <ToolButton active={activeTool === 'select'} label="Select" onClick={() => onToolChange('select')} icon={<MousePointer2 size={14} />} />
        <ToolButton active={activeTool === 'note'} label="Note" onClick={() => onToolChange('note')} icon={<NotebookPen size={14} />} />
        <ToolButton active={activeTool === 'link'} label="Link" onClick={() => onToolChange('link')} icon={<Link2 size={14} />} />
        <span className="toolbar-divider" />
        <ToolButton label="Undo" shortcut="Ctrl Z" onClick={onUndo} icon={<Undo2 size={14} />} disabled={!canUndo} />
        <ToolButton label="Redo" shortcut="Ctrl ⇧ Z" onClick={onRedo} icon={<Redo2 size={14} />} disabled={!canRedo} />
        <span className="toolbar-divider" />
        <ToolButton label="Auto layout" onClick={onAutoLayout} icon={<LayoutGrid size={14} />} />
        <ToolButton label="Fit view" onClick={onFitView} icon={<Maximize size={14} />} />
      </div>

      <div className="layer-toggle">
        <span className="layer-toggle__title"><Layers3 size={12} /> Layers</span>
        {(['conversation', 'knowledge', 'execution'] as LayerKey[]).map((layer) => (
          <button className={layers[layer] ? 'is-active' : ''} type="button" key={layer} onClick={() => onLayerToggle(layer)}>
            <span className="layer-check">{layers[layer] ? <Check size={9} /> : null}</span>
            {layer[0].toUpperCase() + layer.slice(1)}
          </button>
        ))}
      </div>
    </div>
  );
}

function ToolButton({
  active,
  label,
  shortcut,
  onClick,
  icon,
  disabled,
}: {
  active?: boolean;
  label: string;
  shortcut?: string;
  onClick: () => void;
  icon: ReactNode;
  disabled?: boolean;
}) {
  return (
    <button
      className={active ? 'is-active' : ''}
      type="button"
      onClick={onClick}
      disabled={disabled}
      title={shortcut ? `${label} · ${shortcut}` : label}
    >
      <span className="board-tool__icon">{icon}</span>
      <span className="board-tool__label">{label}</span>
    </button>
  );
}
