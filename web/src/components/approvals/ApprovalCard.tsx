import React, { useState } from 'react'
import { ApprovalDetail } from '../../types'
import { ShieldAlert, Check, X, Edit3 } from 'lucide-react'

interface ApprovalCardProps {
  approval: ApprovalDetail
  onDecision: (
    decision: 'approved' | 'rejected' | 'edited',
    notes?: string,
    editedInput?: Record<string, any>
  ) => Promise<void>
}

export const ApprovalCard: React.FC<ApprovalCardProps> = ({ approval, onDecision }) => {
  const [isEditing, setIsEditing] = useState(false)
  const [editedJson, setEditedJson] = useState(JSON.stringify(approval.tool_input, null, 2))
  const [decisionNotes, setDecisionNotes] = useState('')
  const [jsonError, setJsonError] = useState<string | null>(null)
  const [isSubmitting, setIsSubmitting] = useState(false)

  const handleApprove = async () => {
    setIsSubmitting(true)
    try {
      await onDecision('approved', decisionNotes || 'Approved via Web UI')
    } finally {
      setIsSubmitting(false)
    }
  }

  const handleReject = async () => {
    setIsSubmitting(true)
    try {
      await onDecision('rejected', decisionNotes || 'Rejected via Web UI')
    } finally {
      setIsSubmitting(false)
    }
  }

  const handleSaveEditAndApprove = async () => {
    try {
      const parsed = JSON.parse(editedJson)
      setJsonError(null)
      setIsSubmitting(true)
      await onDecision('edited', decisionNotes || 'Edited and approved via Web UI', parsed)
    } catch (err: any) {
      setJsonError(`Invalid JSON: ${err.message}`)
    } finally {
      setIsSubmitting(false)
    }
  }

  return (
    <div className="approval-overlay">
      <div className="approval-card">
        <div className="approval-header">
          <div className="approval-title">
            <ShieldAlert size={18} color="var(--accent-amber)" />
            <span>Action Authorization Required: {approval.tool_name}</span>
          </div>
          <span className={`risk-badge ${approval.risk_level.toLowerCase()}`}>
            {approval.risk_level} RISK
          </span>
        </div>

        <div style={{ fontSize: 13, color: 'var(--text-secondary)', marginBottom: 8 }}>
          The agent requested to invoke tool <code>{approval.tool_name}</code> with arguments:
        </div>

        {isEditing ? (
          <div>
            <textarea
              className="chat-textarea"
              style={{
                fontFamily: 'var(--font-mono)',
                fontSize: 12,
                backgroundColor: '#0c0a14',
                border: '1px solid var(--accent-purple)',
                borderRadius: 6,
                padding: 10,
                width: '100%',
                minHeight: 120,
              }}
              value={editedJson}
              onChange={(e) => {
                setEditedJson(e.target.value)
                setJsonError(null)
              }}
            />
            {jsonError && (
              <div style={{ color: 'var(--accent-red)', fontSize: 12, marginTop: 4 }}>
                {jsonError}
              </div>
            )}
          </div>
        ) : (
          <div className="approval-args">
            <pre>{JSON.stringify(approval.tool_input, null, 2)}</pre>
          </div>
        )}

        <div style={{ margin: '10px 0' }}>
          <input
            type="text"
            className="project-select-input"
            placeholder="Optional audit notes / reason..."
            value={decisionNotes}
            onChange={(e) => setDecisionNotes(e.target.value)}
          />
        </div>

        <div className="approval-actions">
          {isEditing ? (
            <>
              <button
                type="button"
                className="btn-approve"
                onClick={handleSaveEditAndApprove}
                disabled={isSubmitting}
              >
                <Check size={14} /> Submit Edited Input
              </button>
              <button
                type="button"
                className="btn-edit-args"
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
                className="btn-approve"
                onClick={handleApprove}
                disabled={isSubmitting}
              >
                <Check size={14} /> Approve Execution
              </button>
              <button
                type="button"
                className="btn-reject"
                onClick={handleReject}
                disabled={isSubmitting}
              >
                <X size={14} /> Reject
              </button>
              <button
                type="button"
                className="btn-edit-args"
                onClick={() => setIsEditing(true)}
                disabled={isSubmitting}
              >
                <Edit3 size={14} /> Edit Arguments
              </button>
            </>
          )}
        </div>
      </div>
    </div>
  )
}
