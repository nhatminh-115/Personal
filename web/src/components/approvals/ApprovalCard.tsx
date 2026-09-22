import React, { useState } from 'react';
import type { ApprovalDetail } from '../../types';
import { ShieldAlert, Check, X, Edit3 } from 'lucide-react';

export interface ApprovalCardProps {
  approval: ApprovalDetail;
  onDecision: (
    decision: 'approved' | 'rejected' | 'edited',
    notes?: string,
    editedInput?: Record<string, any>
  ) => Promise<void>;
}

export const ApprovalCard: React.FC<ApprovalCardProps> = ({ approval, onDecision }) => {
  const [isEditing, setIsEditing] = useState(false);
  const [editedJson, setEditedJson] = useState(JSON.stringify(approval.tool_input, null, 2));
  const [decisionNotes, setDecisionNotes] = useState('');
  const [jsonError, setJsonError] = useState<string | null>(null);
  const [isSubmitting, setIsSubmitting] = useState(false);

  const handleApprove = async () => {
    setIsSubmitting(true);
    try {
      await onDecision('approved', decisionNotes || 'Approved via Web UI');
    } finally {
      setIsSubmitting(false);
    }
  };

  const handleReject = async () => {
    setIsSubmitting(true);
    try {
      await onDecision('rejected', decisionNotes || 'Rejected via Web UI');
    } finally {
      setIsSubmitting(false);
    }
  };

  const handleSaveEditAndApprove = async () => {
    try {
      const parsed = JSON.parse(editedJson);
      setJsonError(null);
      setIsSubmitting(true);
      await onDecision('edited', decisionNotes || 'Edited and approved via Web UI', parsed);
    } catch (err: any) {
      setJsonError(`Invalid JSON: ${err.message}`);
    } finally {
      setIsSubmitting(false);
    }
  };

  return (
    <div className="aura-approval-banner glow-surface" data-testid="approval-banner">
      <div className="aura-approval-header">
        <div className="aura-approval-title">
          <ShieldAlert size={16} className="text-amber" />
          <strong>Action Authorization Required: <code>{approval.tool_name}</code></strong>
        </div>
        <span className={`risk-badge risk-${approval.risk_level.toLowerCase()}`}>
          {approval.risk_level.toUpperCase()} RISK
        </span>
      </div>

      <div className="aura-approval-desc">
        The agent requested to invoke tool <code>{approval.tool_name}</code> with arguments:
      </div>

      {isEditing ? (
        <div className="aura-approval-edit-block">
          <textarea
            className="aura-approval-textarea"
            aria-label="Edit arguments JSON"
            value={editedJson}
            onChange={(e) => {
              setEditedJson(e.target.value);
              setJsonError(null);
            }}
          />
          {jsonError && <div className="aura-approval-error">{jsonError}</div>}
        </div>
      ) : (
        <div className="aura-approval-args">
          <pre>{JSON.stringify(approval.tool_input, null, 2)}</pre>
        </div>
      )}

      <div className="aura-approval-notes-wrap">
        <input
          type="text"
          className="aura-approval-input"
          placeholder="Optional audit notes / reason..."
          value={decisionNotes}
          onChange={(e) => setDecisionNotes(e.target.value)}
        />
      </div>

      <div className="aura-approval-actions">
        {isEditing ? (
          <>
            <button
              type="button"
              className="action-btn action-btn--approve"
              onClick={handleSaveEditAndApprove}
              disabled={isSubmitting}
            >
              <Check size={14} /> Submit Edited Input
            </button>
            <button
              type="button"
              className="action-btn action-btn--secondary"
              onClick={() => setIsEditing(false)}
              disabled={isSubmitting}
            >
              Cancel Edit
            </button>
          </>
        ) : (
          <>
            <button
              type="button"
              className="action-btn action-btn--approve"
              onClick={handleApprove}
              disabled={isSubmitting}
            >
              <Check size={14} /> Approve Execution
            </button>
            <button
              type="button"
              className="action-btn action-btn--reject"
              onClick={handleReject}
              disabled={isSubmitting}
            >
              <X size={14} /> Reject
            </button>
            <button
              type="button"
              className="action-btn action-btn--secondary"
              onClick={() => setIsEditing(true)}
              disabled={isSubmitting}
            >
              <Edit3 size={14} /> Edit Arguments
            </button>
          </>
        )}
      </div>
    </div>
  );
};
