import { render, screen, fireEvent, act } from '@testing-library/react'
import { describe, it, expect, vi } from 'vitest'
import { ApprovalCard } from '../components/approvals/ApprovalCard'
import { ApprovalDetail } from '../types'

const sampleApproval: ApprovalDetail = {
  id: 'appr-test-123',
  run_id: 'run-test-123',
  session_id: 'sess-test-123',
  tool_name: 'sandbox_shell_execute',
  tool_input: { command: 'rm -rf /tmp/test' },
  risk_level: 'CRITICAL',
  status: 'pending',
  created_at: new Date().toISOString(),
}

describe('ApprovalCard Component', () => {
  it('renders tool name, risk badge, and proposed arguments', () => {
    render(<ApprovalCard approval={sampleApproval} onDecision={vi.fn()} />)

    const matches = screen.getAllByText(/sandbox_shell_execute/i)
    expect(matches.length).toBeGreaterThan(0)
    expect(screen.getByText(/CRITICAL RISK/i)).toBeInTheDocument()
    expect(screen.getByText(/"command": "rm -rf \/tmp\/test"/i)).toBeInTheDocument()
  })

  it('triggers approve decision when Approve Execution is clicked', async () => {
    const onDecisionMock = vi.fn().mockResolvedValue(undefined)
    render(<ApprovalCard approval={sampleApproval} onDecision={onDecisionMock} />)

    await act(async () => {
      fireEvent.click(screen.getByRole('button', { name: /Approve Execution/i }))
    })
    expect(onDecisionMock).toHaveBeenCalledWith('approved', expect.any(String))
  })

  it('triggers reject decision when Reject is clicked', async () => {
    const onDecisionMock = vi.fn().mockResolvedValue(undefined)
    render(<ApprovalCard approval={sampleApproval} onDecision={onDecisionMock} />)

    await act(async () => {
      fireEvent.click(screen.getByRole('button', { name: /Reject/i }))
    })
    expect(onDecisionMock).toHaveBeenCalledWith('rejected', expect.any(String))
  })

  it('allows editing arguments and submitting edited JSON', async () => {
    const onDecisionMock = vi.fn().mockResolvedValue(undefined)
    const { container } = render(<ApprovalCard approval={sampleApproval} onDecision={onDecisionMock} />)

    // Click Edit Arguments
    fireEvent.click(screen.getByRole('button', { name: /Edit Arguments/i }))

    // Modify textarea content
    const textarea = container.querySelector('textarea')!
    fireEvent.change(textarea, {
      target: { value: JSON.stringify({ command: 'ls -la' }) },
    })

    // Submit edited input
    await act(async () => {
      fireEvent.click(screen.getByRole('button', { name: /Submit Edited Input/i }))
    })
    expect(onDecisionMock).toHaveBeenCalledWith('edited', expect.any(String), { command: 'ls -la' })
  })
})
