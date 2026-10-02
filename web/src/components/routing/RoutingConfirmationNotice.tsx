interface RoutingConfirmationNoticeProps {
  proposal: { provider: string; model: string };
  busy?: boolean;
  onConfirm: () => void;
  onCancel: () => void;
}

export function RoutingConfirmationNotice({ proposal, busy = false, onConfirm, onCancel }: RoutingConfirmationNoticeProps) {
  return <div className="routing-studio-backdrop" role="presentation">
    <section className="routing-confirmation" role="alertdialog" aria-modal="true" aria-labelledby="routing-confirmation-title">
      <span className="eyebrow">ROUTING POLICY</span>
      <h2 id="routing-confirmation-title">Cloud routing requires confirmation</h2>
      <p>Proposed: <strong>{proposal.provider}:{proposal.model}</strong></p>
      <p>The run is paused before the model is called. Approving resumes this run with the proposed model, subject to its routing constraints.</p>
      <footer>
        <button className="secondary-button" type="button" onClick={onCancel} disabled={busy}>Cancel run</button>
        <button className="primary-button" type="button" onClick={onConfirm} disabled={busy}>{busy ? 'Resuming…' : 'Approve and continue'}</button>
      </footer>
    </section>
  </div>;
}
