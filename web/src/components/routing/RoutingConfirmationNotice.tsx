interface RoutingConfirmationNoticeProps {
  proposal: { provider: string; model: string };
  busy?: boolean;
  onConfirm: () => void;
  onCancel: () => void;
}

export function RoutingConfirmationNotice({ proposal, busy = false, onConfirm, onCancel }: RoutingConfirmationNoticeProps) {
  return <div className="routing-studio-backdrop" role="presentation">
    <section className="routing-confirmation" role="alertdialog" aria-modal="true" aria-labelledby="routing-confirmation-title">
      <span className="eyebrow">CLOUD MODEL</span>
      <h2 id="routing-confirmation-title">Use this cloud model?</h2>
      <p>Selected model: <strong>{proposal.model}</strong> · {proposal.provider}</p>
      <p>Your message and selected context will be sent to this provider after you approve. Nothing has been sent yet.</p>
      <footer>
        <button className="secondary-button" type="button" onClick={onCancel} disabled={busy}>Cancel run</button>
        <button className="primary-button" type="button" onClick={onConfirm} disabled={busy}>{busy ? 'Resuming…' : 'Approve and continue'}</button>
      </footer>
    </section>
  </div>;
}
