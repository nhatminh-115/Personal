import { Check, CloudOff, Lock, SlidersHorizontal, X } from 'lucide-react';

interface RoutingPopoverProps {
  locked: boolean;
  onToggleLock: () => void;
  onClose: () => void;
}

const routes = [
  ['Root', 'Auto', 'Adaptive'],
  ['Research', 'Model R', 'Med→High'],
  ['Coding', 'Model C', 'High'],
  ['Writing', 'Model W', 'Medium'],
];

export function RoutingPopover({ locked, onToggleLock, onClose }: RoutingPopoverProps) {
  return (
    <div className="popover routing-popover" role="dialog" aria-label="Routing profile">
      <div className="popover__header">
        <div>
          <span className="eyebrow">ROUTING PROFILE</span>
          <h3>Balanced</h3>
        </div>
        <button className="icon-button" type="button" onClick={onClose} aria-label="Close routing popover">
          <X size={16} />
        </button>
      </div>

      <div className="routing-scope-row">
        <span>Scope</span>
        <strong>Session</strong>
      </div>

      <div className="route-table">
        <div className="route-table__head">
          <span>Routes</span>
          <span>Model</span>
          <span>Reasoning</span>
        </div>
        {routes.map(([route, model, reasoning]) => (
          <div className="route-table__row" key={route}>
            <strong>{route}</strong>
            <span>{model}</span>
            <span>{reasoning}</span>
          </div>
        ))}
      </div>

      <div className="routing-footer-grid">
        <div className="setting-card">
          <CloudOff size={15} />
          <span>
            <small>Privacy</small>
            <strong>Internal</strong>
          </span>
        </div>
        <div className="setting-card">
          <SlidersHorizontal size={15} />
          <span>
            <small>Fallback</small>
            <strong>Ask before cloud</strong>
          </span>
        </div>
      </div>

      <div className="popover__actions">
        <button className={`secondary-button ${locked ? 'is-locked' : ''}`} type="button" onClick={onToggleLock}>
          {locked ? <Check size={15} /> : <Lock size={15} />}
          {locked ? 'Agents locked' : 'Lock all agents'}
        </button>
        <button className="primary-button" type="button">
          Open Routing Studio
        </button>
      </div>
    </div>
  );
}
