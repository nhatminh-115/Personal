import { useEffect, useState, type FormEvent } from 'react';
import { X } from 'lucide-react';

interface ApiAccessDialogProps {
  open: boolean;
  tokenConfigured: boolean;
  onClose: () => void;
  onSave: (token: string) => void;
  onForgetToken: () => void;
}

export function ApiAccessDialog({ open, tokenConfigured, onClose, onSave, onForgetToken }: ApiAccessDialogProps) {
  const [token, setToken] = useState('');
  const [error, setError] = useState('');

  useEffect(() => {
    if (open) {
      setToken('');
      setError('');
    }
  }, [open]);

  useEffect(() => {
    if (!open) return;
    const closeOnEscape = (event: KeyboardEvent) => {
      if (event.key === 'Escape') onClose();
    };
    window.addEventListener('keydown', closeOnEscape);
    return () => window.removeEventListener('keydown', closeOnEscape);
  }, [open, onClose]);

  if (!open) return null;

  function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (token.length < 32 || token.trim() !== token || /\s/.test(token)) {
      setError('Enter the configured API token (at least 32 characters, with no spaces).');
      return;
    }
    onSave(token);
  }

  return (
    <div className="modal-scrim api-access-scrim" role="presentation" onMouseDown={(event) => {
      if (event.target === event.currentTarget) onClose();
    }}>
      <section className="api-access-dialog" role="dialog" aria-modal="true" aria-labelledby="api-access-title">
        <div className="modal-head">
          <div>
            <strong>Connection security</strong>
            <h2 id="api-access-title">API access</h2>
          </div>
          <button className="icon-button" type="button" aria-label="Close API access" onClick={onClose}><X size={16} /></button>
        </div>
        <p className="api-access-dialog__copy">
          Enter the shared <code>AURA_API_TOKEN</code> configured on the AURA server. The browser keeps it in this tab’s session storage and sends it only with AURA API requests.
        </p>
        {tokenConfigured ? <p className="api-access-dialog__status">A token is saved for this browser tab. Enter a replacement if the server rejected it, or forget it to remove it. AURA will ask again if the server still requires a token.</p> : null}
        <form onSubmit={handleSubmit}>
          <label htmlFor="aura-api-token">Bearer token</label>
          <input
            id="aura-api-token"
            type="password"
            autoComplete="current-password"
            value={token}
            onChange={(event) => { setToken(event.target.value); setError(''); }}
            placeholder="Paste the server token"
            autoFocus
          />
          {error ? <p className="api-access-dialog__error" role="alert">{error}</p> : null}
          <p className="modal-note">
            AURA requires at least 32 characters. Generate one with <code>python -c "import secrets; print(secrets.token_urlsafe(32))"</code>. This shared token gates the API; it does not create separate user accounts.
          </p>
          <div className="api-access-dialog__actions">
            {tokenConfigured ? (
              <button className="soft-pill api-access-dialog__forget" type="button" onClick={onForgetToken}>Forget token</button>
            ) : null}
            <button className="soft-pill" type="button" onClick={onClose}>Cancel</button>
            <button className="soft-pill is-active" type="submit">Save and reload</button>
          </div>
        </form>
      </section>
    </div>
  );
}
