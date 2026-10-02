import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';
import { AutomationsView } from '../components/global/AutomationsView';
import { api } from '../services/api';
import type { AutomationRecord, ProjectRecord } from '../data/workspaceData';

const projects: ProjectRecord[] = [{ id: 'p1', name: 'AURA', subtitle: 'Workspace', status: 'active', accent: 'cyan', updated: 'today', meta: '', thesis: '', next: '' }];
const liveAutomation: AutomationRecord = {
  id: 'auto-1', name: 'Daily digest', description: 'Summarize changes', instruction: 'Summarize updates.',
  enabled: true, scope: 'global', trigger: 'Every 1 day', actions: ['Run through AURA'],
  lastRun: 'Never', nextRun: 'Tomorrow', status: 'ready', source: 'live', intervalSeconds: 86400,
  latestExecution: { eventId: 'event-1', runId: 'run-1', queuedAt: '2026-10-01T00:00:00Z', status: 'waiting_for_approval', retryCount: 0 },
};
const demoAutomation: AutomationRecord = {
  id: 'demo-1', name: 'Example routine', description: 'Example only', enabled: true, scope: 'global',
  trigger: 'Every evening', actions: ['Example'], lastRun: 'Example', nextRun: 'Example', status: 'ready', source: 'demo',
};

describe('AutomationsView', () => {
  it('creates a persistent project-scoped instruction on the selected interval', async () => {
    const onCreate = vi.fn().mockResolvedValue(liveAutomation);
    render(<AutomationsView projects={projects} automations={[]} onCreate={onCreate} onToggle={vi.fn()} onRunNow={vi.fn()} onApprovalResolved={vi.fn()} />);
    fireEvent.click(screen.getByRole('button', { name: /new automation/i }));
    fireEvent.change(screen.getByLabelText('Name'), { target: { value: 'Project digest' } });
    fireEvent.change(screen.getByLabelText('Description'), { target: { value: 'A short summary' } });
    fireEvent.change(screen.getByLabelText('Instruction for AURA'), { target: { value: 'Review the latest project activity.' } });
    fireEvent.click(screen.getByRole('button', { name: 'Project' }));
    fireEvent.change(screen.getByLabelText('Run every'), { target: { value: '2' } });
    fireEvent.change(screen.getByLabelText('Run every').parentElement!.querySelector('select')!, { target: { value: 'hours' } });
    fireEvent.click(screen.getByRole('button', { name: 'Create automation' }));
    await waitFor(() => expect(onCreate).toHaveBeenCalledWith({
      name: 'Project digest', description: 'A short summary', instruction: 'Review the latest project activity.',
      scope: 'project', project_name: 'AURA', interval_seconds: 7200,
    }));
  });

  it('reviews sequential automation approvals and refreshes the run after the final decision', async () => {
    const firstApproval = {
      id: 'approval-1', run_id: 'run-1', session_id: 'session-1', tool_call_id: 'call-1',
      tool_name: 'write_workspace_file', tool_input: { path: 'private_file.py', content: 'safe content' },
      risk_level: 'high', status: 'pending', created_at: '2026-10-02T00:00:00Z',
    };
    const secondApproval = {
      ...firstApproval, id: 'approval-2', tool_call_id: 'call-2', tool_name: 'sandbox_shell_execute',
      tool_input: { command: 'python private_file.py' },
    };
    vi.spyOn(api, 'fetchRunDetails').mockResolvedValue({
      id: 'run-1', session_id: 'session-1', status: 'waiting_for_approval', user_message: 'private instruction',
      created_at: '', updated_at: '', events: [{ id: 'event-approval', event_type: 'approval_requested', created_at: '',
        payload: { approval_id: 'approval-1', tool_name: 'write_workspace_file' } }],
    });
    vi.spyOn(api, 'fetchApproval').mockImplementation(async (id) => (id === 'approval-1' ? firstApproval : secondApproval));
    vi.spyOn(api, 'submitApproval')
      .mockResolvedValueOnce({ approval_id: 'approval-2', status: 'approved', run_id: 'run-1', execution_status: 'waiting_for_approval' })
      .mockResolvedValueOnce({ approval_id: 'approval-2', status: 'rejected', run_id: 'run-1', execution_status: 'cancelled' });
    const onApprovalResolved = vi.fn();
    render(<AutomationsView projects={projects} automations={[liveAutomation]} onCreate={vi.fn()} onToggle={vi.fn()} onRunNow={vi.fn()} onApprovalResolved={onApprovalResolved} />);

    fireEvent.click(screen.getByRole('button', { name: 'Review approval' }));
    expect(await screen.findByRole('dialog', { name: 'Daily digest' })).toBeInTheDocument();
    expect(screen.getByText('write_workspace_file')).toBeInTheDocument();
    expect(screen.getByText(/private_file\.py/)).toBeInTheDocument();

    fireEvent.click(screen.getByRole('button', { name: 'Approve and continue' }));
    expect(await screen.findByText('sandbox_shell_execute')).toBeInTheDocument();
    fireEvent.click(screen.getByRole('button', { name: 'Reject' }));
    await waitFor(() => expect(onApprovalResolved).toHaveBeenCalledWith('auto-1'));
    expect(api.submitApproval).toHaveBeenNthCalledWith(1, 'approval-1', 'approved', undefined, undefined);
    expect(api.submitApproval).toHaveBeenNthCalledWith(2, 'approval-2', 'rejected', undefined, undefined);
  });

  it('validates edited automation input and submits only an explicit JSON object decision', async () => {
    vi.clearAllMocks();
    const approval = {
      id: 'approval-edit', run_id: 'run-1', session_id: 'session-1', tool_call_id: 'call-edit',
      tool_name: 'write_workspace_file', tool_input: { path: 'report.md', content: 'draft' },
      risk_level: 'high', status: 'pending', created_at: '2026-10-02T00:00:00Z',
    };
    vi.spyOn(api, 'fetchRunDetails').mockResolvedValue({
      id: 'run-1', session_id: 'session-1', status: 'waiting_for_approval', user_message: 'update report',
      created_at: '', updated_at: '', events: [{ id: 'event-edit', event_type: 'approval_requested', created_at: '',
        payload: { approval_id: approval.id, tool_name: approval.tool_name } }],
    });
    vi.spyOn(api, 'fetchApproval').mockResolvedValue(approval);
    vi.spyOn(api, 'submitApproval').mockResolvedValue({
      approval_id: approval.id, status: 'edited', run_id: 'run-1', execution_status: 'completed',
    });
    const onApprovalResolved = vi.fn();
    render(<AutomationsView projects={projects} automations={[liveAutomation]} onCreate={vi.fn()} onToggle={vi.fn()} onRunNow={vi.fn()} onApprovalResolved={onApprovalResolved} />);

    fireEvent.click(screen.getByRole('button', { name: 'Review approval' }));
    await screen.findByRole('dialog', { name: 'Daily digest' });
    fireEvent.click(screen.getByRole('button', { name: 'Edit input' }));
    const editor = screen.getByRole('textbox', { name: 'Edit automation tool input JSON' });
    fireEvent.change(editor, { target: { value: '{ invalid json' } });
    fireEvent.click(screen.getByRole('button', { name: 'Approve edited input' }));
    expect(await screen.findByRole('alert')).toHaveTextContent(/JSON|property/i);
    expect(api.submitApproval).not.toHaveBeenCalled();

    fireEvent.change(editor, { target: { value: JSON.stringify({ path: 'report.md', content: 'reviewed' }) } });
    fireEvent.click(screen.getByRole('button', { name: 'Approve edited input' }));
    await waitFor(() => expect(onApprovalResolved).toHaveBeenCalledWith('auto-1'));
    expect(api.submitApproval).toHaveBeenCalledWith(approval.id, 'edited', undefined, {
      path: 'report.md', content: 'reviewed',
    });
  });

  it('rejects non-object automation approval edits without resolving the approval', async () => {
    vi.clearAllMocks();
    const approval = {
      id: 'approval-array', run_id: 'run-1', session_id: 'session-1', tool_call_id: 'call-array',
      tool_name: 'write_workspace_file', tool_input: { path: 'report.md' },
      risk_level: 'high', status: 'pending', created_at: '2026-10-02T00:00:00Z',
    };
    vi.spyOn(api, 'fetchRunDetails').mockResolvedValue({
      id: 'run-1', session_id: 'session-1', status: 'waiting_for_approval', user_message: 'update report',
      created_at: '', updated_at: '', events: [{ id: 'event-array', event_type: 'approval_requested', created_at: '',
        payload: { approval_id: approval.id } }],
    });
    vi.spyOn(api, 'fetchApproval').mockResolvedValue(approval);
    const onApprovalResolved = vi.fn();
    render(<AutomationsView projects={projects} automations={[liveAutomation]} onCreate={vi.fn()} onToggle={vi.fn()} onRunNow={vi.fn()} onApprovalResolved={onApprovalResolved} />);

    fireEvent.click(screen.getByRole('button', { name: 'Review approval' }));
    await screen.findByRole('dialog', { name: 'Daily digest' });
    fireEvent.click(screen.getByRole('button', { name: 'Edit input' }));
    fireEvent.change(screen.getByRole('textbox', { name: 'Edit automation tool input JSON' }), { target: { value: '[]' } });
    fireEvent.click(screen.getByRole('button', { name: 'Approve edited input' }));

    expect(await screen.findByRole('alert')).toHaveTextContent(/JSON object/i);
    expect(api.submitApproval).not.toHaveBeenCalled();
    expect(onApprovalResolved).not.toHaveBeenCalled();
  });

  it('loads safe run history on demand without displaying run contents', async () => {
    vi.clearAllMocks();
    vi.spyOn(api, 'fetchAutomationRuns').mockResolvedValue([
      { event_id: 'event-new', run_id: 'run-new', queued_at: '2026-10-02T09:00:00Z', status: 'failed', retry_count: 2 },
      { event_id: 'event-old', run_id: 'run-old', queued_at: '2026-10-01T09:00:00Z', status: 'completed', retry_count: 0 },
    ]);
    render(<AutomationsView projects={projects} automations={[liveAutomation]} onCreate={vi.fn()} onToggle={vi.fn()} onRunNow={vi.fn()} onApprovalResolved={vi.fn()} />);

    expect(api.fetchAutomationRuns).not.toHaveBeenCalled();
    fireEvent.click(screen.getByRole('button', { name: 'Run history' }));
    expect(await screen.findByText('2026-10-02T09:00:00Z')).toBeInTheDocument();
    expect(screen.getByText('failed')).toBeInTheDocument();
    expect(screen.getByText('2 retries')).toBeInTheDocument();
    expect(screen.getByText('2026-10-01T09:00:00Z')).toBeInTheDocument();
    expect(api.fetchAutomationRuns).toHaveBeenCalledWith('auto-1', 10);
    expect(screen.queryByText(/private instruction|sensitive output/i)).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole('button', { name: 'Hide run history' }));
    expect(screen.queryByText('2026-10-02T09:00:00Z')).not.toBeInTheDocument();
  });
  it('refreshes cached history when reopened and on explicit request', async () => {
    vi.clearAllMocks();
    vi.spyOn(api, 'fetchAutomationRuns')
      .mockResolvedValueOnce([{ event_id: 'event-1', run_id: 'run-1', queued_at: '2026-10-02T09:00:00Z', status: 'running', retry_count: 0 }])
      .mockResolvedValueOnce([{ event_id: 'event-1', run_id: 'run-1', queued_at: '2026-10-02T09:00:00Z', status: 'completed', retry_count: 0 }])
      .mockResolvedValueOnce([{ event_id: 'event-1', run_id: 'run-1', queued_at: '2026-10-02T09:00:00Z', status: 'failed', retry_count: 1 }]);
    render(<AutomationsView projects={projects} automations={[liveAutomation]} onCreate={vi.fn()} onToggle={vi.fn()} onRunNow={vi.fn()} onApprovalResolved={vi.fn()} />);

    fireEvent.click(screen.getByRole('button', { name: 'Run history' }));
    expect(await screen.findByText('running')).toBeInTheDocument();
    fireEvent.click(screen.getByRole('button', { name: 'Refresh history' }));
    expect(await screen.findByText('completed')).toBeInTheDocument();
    expect(screen.queryByText('running')).not.toBeInTheDocument();
    expect(api.fetchAutomationRuns).toHaveBeenCalledTimes(2);

    fireEvent.click(screen.getByRole('button', { name: 'Hide run history' }));
    fireEvent.click(screen.getByRole('button', { name: 'Run history' }));
    expect(await screen.findByText('failed')).toBeInTheDocument();
    expect(screen.getByText('1 retries')).toBeInTheDocument();
    expect(api.fetchAutomationRuns).toHaveBeenCalledTimes(3);
  });
  it('inspects persisted routing and filtered events without exposing instructions or raw tool payloads', async () => {
    vi.clearAllMocks();
    vi.spyOn(api, 'fetchAutomationRuns').mockResolvedValue([
      { event_id: 'event-1', run_id: 'run-history-1', queued_at: '2026-10-02T09:00:00Z', status: 'completed', retry_count: 0 },
    ]);
    vi.spyOn(api, 'fetchRunDetails').mockResolvedValue({
      id: 'run-history-1', session_id: 'automation-session', status: 'completed', user_message: 'private automation instruction',
      final_response: 'The weekly report is ready.', error_message: undefined, created_at: '2026-10-02T09:00:00Z', updated_at: '2026-10-02T09:01:00Z',
      events: [
        { id: 'event-model', event_type: 'model_selected', created_at: '2026-10-02T09:00:01Z', payload: { provider: 'ollama', model: 'qwen-local', agent_role: 'root' } },
        { id: 'event-tool', event_type: 'tool_executed', created_at: '2026-10-02T09:00:02Z', payload: { tool_name: 'read_workspace_file', success: true, output: 'private raw tool output' } },
        { id: 'event-thought', event_type: 'assistant_thought', created_at: '2026-10-02T09:00:03Z', payload: { content: 'hidden reasoning' } },
      ],
    });
    vi.spyOn(api, 'fetchRunRouting').mockResolvedValue({
      run_id: 'run-history-1', decisions: [{
        run_id: 'run-history-1', snapshot: { winning_scope: 'project' },
        model_selection: { provider: 'ollama', model: 'qwen-local', agent_role: 'root', winning_scope: 'project' },
        reasoning_selection: null, fallback_events: [],
      }],
    });
    render(<AutomationsView projects={projects} automations={[liveAutomation]} onCreate={vi.fn()} onToggle={vi.fn()} onRunNow={vi.fn()} onApprovalResolved={vi.fn()} />);

    fireEvent.click(screen.getByRole('button', { name: 'Run history' }));
    fireEvent.click(await screen.findByRole('button', { name: 'Inspect run' }));
    expect(await screen.findByRole('dialog', { name: 'Daily digest' })).toBeInTheDocument();
    expect(screen.getByText('The weekly report is ready.')).toBeInTheDocument();
    expect(screen.getByText('ollama · qwen-local')).toBeInTheDocument();
    expect(screen.getByText('read_workspace_file · succeeded')).toBeInTheDocument();
    expect(screen.queryByText('private automation instruction')).not.toBeInTheDocument();
    expect(screen.queryByText('private raw tool output')).not.toBeInTheDocument();
    expect(screen.queryByText('hidden reasoning')).not.toBeInTheDocument();
    expect(screen.getByText(/raw tool payloads are not included/i)).toBeInTheDocument();
    expect(api.fetchRunDetails).toHaveBeenCalledWith('run-history-1');
    expect(api.fetchRunRouting).toHaveBeenCalledWith('run-history-1');
  });
  it('keeps example automations local and only allows live routines to run', () => {
    const onRunNow = vi.fn();
    const onToggle = vi.fn();
    render(<AutomationsView projects={projects} automations={[liveAutomation, demoAutomation]} onCreate={vi.fn()} onToggle={onToggle} onRunNow={onRunNow} onApprovalResolved={vi.fn()} />);
    const runButtons = screen.getAllByRole('button', { name: /run now/i });
    expect(runButtons[0]).toBeEnabled();
    expect(runButtons[1]).toBeDisabled();
    fireEvent.click(runButtons[0]);
    expect(onRunNow).toHaveBeenCalledWith(liveAutomation);
    fireEvent.click(screen.getByRole('button', { name: /pause daily digest/i }));
    expect(onToggle).toHaveBeenCalledWith(liveAutomation, false);
    expect(screen.getByText('Persistent scheduler')).toBeInTheDocument();
    expect(screen.getByText('waiting for approval')).toBeInTheDocument();
  });
});
