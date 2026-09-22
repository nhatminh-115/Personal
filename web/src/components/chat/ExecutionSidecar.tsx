import { Check, ChevronRight, Circle, LoaderCircle, X } from 'lucide-react';
import type { ExecutionStep } from '../../types';

interface ExecutionSidecarProps {
  title: string;
  steps: ExecutionStep[];
  onClose: () => void;
}

export function ExecutionSidecar({ title, steps, onClose }: ExecutionSidecarProps) {
  const complete = steps.filter((step) => step.status === 'done').length;
  const runningIndex = steps.findIndex((step) => step.status === 'running');
  const current = runningIndex >= 0 ? runningIndex + 1 : Math.min(complete + 1, steps.length);

  return (
    <aside className="execution-sidecar">
      <div className="execution-sidecar__header">
        <div>
          <span className="eyebrow">EXECUTION</span>
          <h3>{title}</h3>
          <p>Operational trace · no chain-of-thought</p>
        </div>
        <button className="icon-button" type="button" onClick={onClose} aria-label="Close execution">
          <X size={16} />
        </button>
      </div>

      <div className="execution-progress">
        <span>Step {current} of {steps.length}</span>
        <strong>{complete}/{steps.length} complete</strong>
        <div className="execution-progress__track"><span style={{ width: `${Math.max(8, (complete / Math.max(steps.length, 1)) * 100)}%` }} /></div>
      </div>

      <div className="execution-stepper">
        {steps.map((step, index) => (
          <ExecutionStepRow step={step} key={step.id} index={index + 1} isLast={index === steps.length - 1} />
        ))}
      </div>
    </aside>
  );
}

function ExecutionStepRow({ step, index, isLast }: { step: ExecutionStep; index: number; isLast: boolean }) {
  return (
    <div className={`execution-step ${step.status === 'running' ? 'is-running glow-surface' : ''} ${step.status === 'done' ? 'is-done' : ''}`}>
      <div className="execution-step__rail">
        <span className="execution-step__dot">
          {step.status === 'done' ? <Check size={12} /> : null}
          {step.status === 'running' ? <LoaderCircle size={12} className="spin" /> : null}
          {step.status === 'queued' ? <Circle size={8} /> : null}
          <em>{step.status === 'queued' ? index : null}</em>
        </span>
        {isLast ? null : <span className="execution-step__line" />}
      </div>
      <div className="execution-step__content">
        <div className="execution-step__heading">
          <strong>{step.label}</strong>
          <small>{step.status}</small>
        </div>
        {step.detail ? <span>{step.detail}</span> : null}
        {step.children?.map((child) => (
          <div className="execution-child" key={child.id}>
            <ChevronRight size={11} />
            <span>{child.label}</span>
            {child.detail ? <small>{child.detail}</small> : null}
          </div>
        ))}
      </div>
    </div>
  );
}
