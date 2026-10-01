interface RoutingConfirmationNoticeProps {
  proposal: { provider?: string; model?: string };
  onCancel: () => void;
  onOpenStudio: () => void;
  onChangeRouting: () => void;
}

export function RoutingConfirmationNotice({ proposal, onCancel, onOpenStudio, onChangeRouting }: RoutingConfirmationNoticeProps) {
  return <div className="routing-studio-backdrop" role="presentation">
    <section className="routing-confirmation" role="alertdialog" aria-modal="true" aria-labelledby="routing-confirmation-title">
      <span className="eyebrow">ROUTING POLICY</span>
      <h2 id="routing-confirmation-title">Cloud routing requires confirmation</h2>
      <p>Proposed: <strong>{proposal.provider && proposal.model ? `${proposal.provider}:${proposal.model}` : 'cloud model unavailable'}</strong></p>
      <p>Execution stopped before the model was called. Review the route or choose another profile.</p>
      <footer><button className="secondary-button" type="button" onClick={onCancel}>Cancel</button><button className="secondary-button" type="button" onClick={onChangeRouting}>Change routing</button><button className="primary-button" type="button" onClick={onOpenStudio}>Open Routing Studio</button></footer>
    </section>
  </div>;
}
