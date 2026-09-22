import { CheckCircle2 } from 'lucide-react';
import type { ToastMessage } from '../../types';

export function ToastStack({ toasts }: { toasts: ToastMessage[] }) {
  return (
    <div className="toast-stack" aria-live="polite">
      {toasts.map((toast) => (
        <div className="toast" key={toast.id}>
          <CheckCircle2 size={16} />
          <div>
            <strong>{toast.title}</strong>
            {toast.detail ? <span>{toast.detail}</span> : null}
          </div>
        </div>
      ))}
    </div>
  );
}
