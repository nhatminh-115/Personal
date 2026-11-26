import { CheckCircle2, CircleAlert, X } from 'lucide-react';
import type { ToastMessage } from '../../types';

export function ToastStack({ toasts, onDismiss }: { toasts: ToastMessage[]; onDismiss: (id: number) => void }) {
  return (
    <div className="toast-stack" aria-live="polite">
      {toasts.map((toast) => (
        <div className={`toast ${/could not|failed|error/i.test(toast.title) ? 'toast--error' : ''}`} key={toast.id}>
          {/could not|failed|error/i.test(toast.title) ? <CircleAlert size={16} /> : <CheckCircle2 size={16} />}
          <div>
            <strong>{toast.title}</strong>
            {toast.detail ? <span>{toast.detail}</span> : null}
          </div>
          <button className="toast__dismiss" type="button" aria-label={`Dismiss ${toast.title}`} onClick={() => onDismiss(toast.id)}><X size={13} /></button>
        </div>
      ))}
    </div>
  );
}
