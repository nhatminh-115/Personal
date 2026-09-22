import { Check, LoaderCircle, Route, Search, Sparkles, Square } from 'lucide-react';

type RunPhase = 'routing' | 'context' | 'synthesizing';

interface AIRunStripProps {
  phase: RunPhase;
  specialist: string;
  onStop: () => void;
}

const steps: { id: RunPhase; label: string; icon: typeof Route }[] = [
  { id: 'routing', label: 'Route task', icon: Route },
  { id: 'context', label: 'Gather context', icon: Search },
  { id: 'synthesizing', label: 'Synthesize answer', icon: Sparkles },
];

const order: RunPhase[] = ['routing', 'context', 'synthesizing'];

export function AIRunStrip({ phase, specialist, onStop }: AIRunStripProps) {
  const activeIndex = order.indexOf(phase);

  return (
    <div className="ai-run-strip">
      <div className="ai-run-strip__title">
        <span className="running-dot" />
        <div>
          <strong>AURA is working</strong>
          <small>{specialist}</small>
        </div>
      </div>

      <div className="ai-run-strip__steps">
        {steps.map(({ id, label, icon: Icon }, index) => {
          const done = index < activeIndex;
          const active = index === activeIndex;
          return (
            <span key={id} className={`${done ? 'is-done' : ''} ${active ? 'is-active' : ''}`}>
              {done ? <Check size={11} /> : active ? <LoaderCircle size={11} className="spin" /> : <Icon size={11} />}
              {label}
            </span>
          );
        })}
      </div>

      <button type="button" className="ai-run-strip__stop" onClick={onStop}>
        <Square size={10} /> Stop
      </button>
    </div>
  );
}
