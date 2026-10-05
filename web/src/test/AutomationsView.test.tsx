import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';
import { AutomationsView } from '../components/global/AutomationsView';
import { api } from '../services/api';
import type { AutomationRecord, ProjectRecord } from '../data/workspaceData';

const projects: ProjectRecord[] = [{ id: 'p1', name: 'AURA', subtitle: 'Workspace', status: 'active', accent: 'cyan', updated: 'today', meta: '', thesis: '', next: '' }];
const liveAutomation: AutomationRecord = {
  id: 'auto-1', revision: 1, name: 'Daily digest', description: 'Summarize changes', instruction: 'Summarize updates.',
  enabled: true, scope: 'global', trigger: 'Every 1 day', actions: ['Run through AURA'],
  lastRun: 'Never', nextRun: 'Tomorrow', status: 'ready', source: 'live', intervalSeconds: 86400,
  latestExecution: { eventId: 'event-1', runId: 'run-1', queuedAt: '2026-10-01T00:00:00Z', status: 'waiting_for_approval', retryCount: 0 },
};
const demoAutomation: AutomationRecord = {
  id: 'demo-1', name: 'Example routine', description: 'Example only', enabled: true, scope: 'global',
  trigger: 'Every evening', actions: ['Example'], lastRun: 'Example', nextRun: 'Example', status: 'ready', source: 'demo',
};

describe('AutomationsView', () => {
  it('offers explicit automation pagination and a retry after a page error', () => {
    const onLoadMore = vi.fn();
    const { rerender } = render(<AutomationsView projects={projects} automations={[liveAutomation]} hasMore onLoadMore={onLoadMore} onCreate={vi.fn()} onToggle={vi.fn()} onRunNow={vi.fn()} onApprovalResolved={vi.fn()} />);
    fireEvent.click(screen.getByRole('button', { name: 'Load more automations' }));
    expect(onLoadMore).toHaveBeenCalledOnce();

    rerender(<AutomationsView projects={projects} automations={[liveAutomation]} hasMore pageError="Network unavailable" onLoadMore={onLoadMore} onCreate={vi.fn()} onToggle={vi.fn()} onRunNow={vi.fn()} onApprovalResolved={vi.fn()} />);
    fireEvent.click(screen.getByRole('button', { name: 'Retry' }));
    expect(onLoadMore).toHaveBeenCalledTimes(2);
    expect(screen.getByText(/Could not load automations: Network unavailable/)).toBeInTheDocument();
  });

  it('disables Run now while the latest run is awaiting approval', () => {
    const onRunNow = vi.fn();
    render(<AutomationsView projects={projects} automations={[liveAutomation]} onCreate={vi.fn()} onToggle={vi.fn()} onRunNow={onRunNow} onApprovalResolved={vi.fn()} />);
    const button = screen.getByRole('button', { name: 'Run now' });
    expect(button).toBeDisabled();
    fireEvent.click(button);
    expect(onRunNow).not.toHaveBeenCalled();
  });

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
      webhook_enabled: false,
      schedule: { mode: 'interval', local_time: null, weekdays: [], timezone: Intl.DateTimeFormat().resolvedOptions().timeZone || 'UTC' },
    }));
  });

  it('edits a live automation while preserving its project scope', async () => {
    const projectAutomation = { ...liveAutomation, scope: 'project' as const, projectId: 'p1', projectName: 'AURA' };
    const onUpdate = vi.fn().mockResolvedValue(projectAutomation);
    render(<AutomationsView projects={projects} automations={[projectAutomation]} onCreate={vi.fn()} onUpdate={onUpdate} onToggle={vi.fn()} onRunNow={vi.fn()} onApprovalResolved={vi.fn()} />);

    fireEvent.click(screen.getByRole('button', { name: 'Edit Daily digest' }));
    expect(await screen.findByRole('dialog', { name: 'Update this routine' })).toBeInTheDocument();
    expect(screen.getByText(/Scope stays in AURA/)).toBeInTheDocument();
    expect(screen.queryByRole('button', { name: 'Global' })).not.toBeInTheDocument();
    fireEvent.change(screen.getByLabelText('Name'), { target: { value: 'Project review' } });
    fireEvent.change(screen.getByLabelText('Instruction for AURA'), { target: { value: 'Summarize decisions and owners.' } });
    fireEvent.change(screen.getByLabelText('Run every'), { target: { value: '2' } });
    fireEvent.change(screen.getByLabelText('Run every').parentElement!.querySelector('select')!, { target: { value: 'hours' } });
    fireEvent.click(screen.getByRole('button', { name: 'Save changes' }));

    await waitFor(() => expect(onUpdate).toHaveBeenCalledWith('auto-1', {
      name: 'Project review', description: 'Summarize changes', instruction: 'Summarize decisions and owners.', interval_seconds: 7200,
      webhook_enabled: false,
      schedule: { mode: 'interval', local_time: null, weekdays: [], timezone: 'UTC' },
    }, 1));
  });

  it('creates an authenticated webhook and reveals its secret only in the one-time setup dialog', async () => {
    const onCreate = vi.fn().mockResolvedValue({
      ...liveAutomation, webhookEnabled: true, webhookPath: '/v1/automations/auto-2/webhook/events', webhookSecret: 'one-time-webhook-secret',
    });
    render(<AutomationsView projects={projects} automations={[]} onCreate={onCreate} onToggle={vi.fn()} onRunNow={vi.fn()} onApprovalResolved={vi.fn()} />);
    fireEvent.click(screen.getByRole('button', { name: /new automation/i }));
    fireEvent.change(screen.getByLabelText('Name'), { target: { value: 'Deploy signal' } });
    fireEvent.change(screen.getByLabelText('Instruction for AURA'), { target: { value: 'Check deployment status.' } });
    fireEvent.click(screen.getByRole('checkbox'));
    fireEvent.click(screen.getByRole('button', { name: 'Create automation' }));

    await waitFor(() => expect(onCreate).toHaveBeenCalledWith(expect.objectContaining({ webhook_enabled: true })));
    expect(await screen.findByRole('dialog', { name: 'Save this secret now' })).toBeInTheDocument();
    expect(screen.getByText('/v1/automations/auto-2/webhook/events')).toBeInTheDocument();
    expect(screen.getByText('one-time-webhook-secret')).toBeInTheDocument();
    expect(screen.getByText(/request body is ignored/i)).toBeInTheDocument();
  });

  it('shows the configured webhook endpoint without exposing a saved secret', () => {
    const configured = { ...liveAutomation, webhookEnabled: true, webhookPath: '/v1/automations/auto-1/webhook/events' };
    render(<AutomationsView projects={projects} automations={[configured]} onCreate={vi.fn()} onToggle={vi.fn()} onRunNow={vi.fn()} onApprovalResolved={vi.fn()} />);
    fireEvent.click(screen.getByText('Webhook endpoint'));
    expect(screen.getByText('/v1/automations/auto-1/webhook/events')).toBeInTheDocument();
    expect(screen.queryByText(/Bearer/)).not.toBeInTheDocument();
  });

  it('creates a weekly wall-clock schedule in the selected timezone', async () => {
    const onCreate = vi.fn().mockResolvedValue(liveAutomation);
    render(<AutomationsView projects={projects} automations={[]} onCreate={onCreate} onToggle={vi.fn()} onRunNow={vi.fn()} onApprovalResolved={vi.fn()} />);
    fireEvent.click(screen.getByRole('button', { name: /new automation/i }));
    fireEvent.change(screen.getByLabelText('Name'), { target: { value: 'Weekly review' } });
    fireEvent.change(screen.getByLabelText('Instruction for AURA'), { target: { value: 'Review the week.' } });
    fireEvent.change(screen.getByLabelText('Schedule'), { target: { value: 'weekly' } });
    fireEvent.change(screen.getByLabelText('Local time'), { target: { value: '08:30' } });
    fireEvent.change(screen.getByLabelText('Timezone'), { target: { value: 'Asia/Saigon' } });
    fireEvent.click(screen.getByLabelText('Saturday'));
    fireEvent.click(screen.getByRole('button', { name: 'Create automation' }));
    await waitFor(() => expect(onCreate).toHaveBeenCalledWith(expect.objectContaining({
      schedule: { mode: 'weekly', local_time: '08:30', weekdays: [0, 1, 2, 3, 4, 5], timezone: 'Asia/Saigon' },
    })));
  });

  it('keeps archived routines paused, exposes history, and offers restore', () => {
    const archived = { ...liveAutomation, archived: true, enabled: false };
    const onSetArchived = vi.fn();
    render(<AutomationsView projects={projects} automations={[archived]} includeArchived onToggleArchived={vi.fn()} onSetArchived={onSetArchived} onCreate={vi.fn()} onUpdate={vi.fn()} onToggle={vi.fn()} onRunNow={vi.fn()} onApprovalResolved={vi.fn()} />);

    expect(screen.getByText('Archived')).toBeInTheDocument();
    expect(screen.getByText('waiting for approval')).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Run now' })).toBeDisabled();
    expect(screen.getByRole('button', { name: 'Resume Daily digest' })).toBeDisabled();
    fireEvent.click(screen.getByRole('button', { name: 'Restore' }));
    expect(onSetArchived).toHaveBeenCalledWith(archived, false);
  });

  it('offers a paused duplicate with independent run history', () => {
    const onDuplicate = vi.fn();
    render(<AutomationsView projects={projects} automations={[liveAutomation]} onDuplicate={onDuplicate} onCreate={vi.fn()} onUpdate={vi.fn()} onToggle={vi.fn()} onRunNow={vi.fn()} onApprovalResolved={vi.fn()} />);

    fireEvent.click(screen.getByRole('button', { name: 'Duplicate' }));

    expect(onDuplicate).toHaveBeenCalledWith(liveAutomation);
  });

  it('cancels a queued run and keeps its history visible', async () => {
    const queuedRun = { event_id: 'queued-event', run_id: 'queued-run', queued_at: '2026-10-02T00:00:00Z', status: 'queued', retry_count: 0 };
    const historySpy = vi.spyOn(api, 'fetchAutomationRuns').mockResolvedValue({ runs: [queuedRun], nextCursor: null });
    const onCancelRun = vi.fn().mockResolvedValue({ ...queuedRun, status: 'cancelled' });
    render(<AutomationsView projects={projects} automations={[liveAutomation]} onCancelRun={onCancelRun} onCreate={vi.fn()} onToggle={vi.fn()} onRunNow={vi.fn()} onApprovalResolved={vi.fn()} />);

    fireEvent.click(screen.getByRole('button', { name: 'Run history' }));
    fireEvent.click(await screen.findByRole('button', { name: 'Cancel queued run' }));

    await waitFor(() => expect(onCancelRun).toHaveBeenCalledWith(liveAutomation.id, queuedRun.event_id));
    expect(await screen.findByText('Cancelled before execution')).toBeInTheDocument();
    historySpy.mockRestore();
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
    vi.spyOn(api, 'fetchAutomationRuns').mockResolvedValue({ runs: [
      { event_id: 'event-new', run_id: 'run-new', queued_at: '2026-10-02T09:00:00Z', status: 'dead_letter', retry_count: 2, trigger_type: 'webhook' },
      { event_id: 'event-old', run_id: 'run-old', queued_at: '2026-10-01T09:00:00Z', status: 'completed', retry_count: 0 },
    ], nextCursor: null });
    render(<AutomationsView projects={projects} automations={[liveAutomation]} onCreate={vi.fn()} onToggle={vi.fn()} onRunNow={vi.fn()} onApprovalResolved={vi.fn()} />);

    expect(api.fetchAutomationRuns).not.toHaveBeenCalled();
    fireEvent.click(screen.getByRole('button', { name: 'Run history' }));
    expect(await screen.findByText('2026-10-02T09:00:00Z')).toBeInTheDocument();
    expect(screen.getByText('dead letter')).toBeInTheDocument();
    expect(screen.getByText('via webhook')).toBeInTheDocument();
    expect(screen.getByText('2 retries')).toBeInTheDocument();
    expect(screen.getByText('2026-10-01T09:00:00Z')).toBeInTheDocument();
    expect(api.fetchAutomationRuns).toHaveBeenCalledWith('auto-1', 10);
    expect(screen.queryByText(/private instruction|sensitive output/i)).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole('button', { name: 'Hide run history' }));
    expect(screen.queryByText('2026-10-02T09:00:00Z')).not.toBeInTheDocument();
  });
  it('loads older automation runs only when requested', async () => {
    vi.clearAllMocks();
    vi.spyOn(api, 'fetchAutomationRuns')
      .mockResolvedValueOnce({ runs: [
        { event_id: 'event-new', run_id: 'run-new', queued_at: '2026-10-02T09:00:00Z', status: 'completed', retry_count: 0 },
      ], nextCursor: 'older-runs-cursor' })
      .mockResolvedValueOnce({ runs: [
        { event_id: 'event-old', run_id: 'run-old', queued_at: '2026-10-01T09:00:00Z', status: 'failed', retry_count: 1 },
      ], nextCursor: null });
    render(<AutomationsView projects={projects} automations={[liveAutomation]} onCreate={vi.fn()} onToggle={vi.fn()} onRunNow={vi.fn()} onApprovalResolved={vi.fn()} />);

    fireEvent.click(screen.getByRole('button', { name: 'Run history' }));
    expect(await screen.findByText('2026-10-02T09:00:00Z')).toBeInTheDocument();
    fireEvent.click(screen.getByRole('button', { name: 'Load older runs' }));
    expect(await screen.findByText('2026-10-01T09:00:00Z')).toBeInTheDocument();
    expect(screen.getByText('2026-10-02T09:00:00Z')).toBeInTheDocument();
    expect(api.fetchAutomationRuns).toHaveBeenLastCalledWith('auto-1', 10, 'older-runs-cursor');
    expect(screen.queryByRole('button', { name: 'Load older runs' })).not.toBeInTheDocument();
  });
  it('refreshes cached history when reopened and on explicit request', async () => {
    vi.clearAllMocks();
    vi.spyOn(api, 'fetchAutomationRuns')
      .mockResolvedValueOnce({ runs: [{ event_id: 'event-1', run_id: 'run-1', queued_at: '2026-10-02T09:00:00Z', status: 'running', retry_count: 0 }], nextCursor: null })
      .mockResolvedValueOnce({ runs: [{ event_id: 'event-1', run_id: 'run-1', queued_at: '2026-10-02T09:00:00Z', status: 'completed', retry_count: 0 }], nextCursor: null })
      .mockResolvedValueOnce({ runs: [{ event_id: 'event-1', run_id: 'run-1', queued_at: '2026-10-02T09:00:00Z', status: 'failed', retry_count: 1 }], nextCursor: null });
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
    vi.spyOn(api, 'fetchAutomationRuns').mockResolvedValue({ runs: [
      { event_id: 'event-1', run_id: 'run-history-1', queued_at: '2026-10-02T09:00:00Z', status: 'completed', retry_count: 0 },
    ], nextCursor: null });
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
    expect(screen.getAllByText('ollama · qwen-local').length).toBeGreaterThan(0);
    expect(screen.getByText('read_workspace_file · succeeded')).toBeInTheDocument();
    expect(screen.queryByText('private automation instruction')).not.toBeInTheDocument();
    expect(screen.queryByText('private raw tool output')).not.toBeInTheDocument();
    expect(screen.queryByText('hidden reasoning')).not.toBeInTheDocument();
    expect(screen.getByText(/raw tool payloads are not included/i)).toBeInTheDocument();
    expect(api.fetchRunDetails).toHaveBeenCalledWith('run-history-1');
    expect(api.fetchRunRouting).toHaveBeenCalledWith('run-history-1');
  });
  it('offers retry for failed runs and identifies the new run as a retry', async () => {
    const failedRun = {
      event_id: 'failed-event', run_id: 'failed-run', queued_at: '2026-10-02T00:00:00Z',
      status: 'dead_letter', retry_count: 3, trigger_type: 'webhook' as const,
    };
    const retriedRun = {
      event_id: 'retry-event', run_id: 'retry-run', queued_at: '2026-10-03T00:00:00Z',
      status: 'queued', retry_count: 0, trigger_type: 'retry' as const, retry_of_event_id: 'failed-event',
    };
    const onRetryRun = vi.fn().mockResolvedValue(retriedRun);
    vi.spyOn(api, 'fetchAutomationRuns').mockResolvedValue({ runs: [failedRun], nextCursor: null });
    const idleAutomation = { ...liveAutomation, latestExecution: { ...liveAutomation.latestExecution!, status: 'completed' } };
    render(<AutomationsView projects={projects} automations={[idleAutomation]} onCreate={vi.fn()} onToggle={vi.fn()} onRunNow={vi.fn()} onRetryRun={onRetryRun} onApprovalResolved={vi.fn()} />);
    fireEvent.click(screen.getByRole('button', { name: 'Run history' }));
    await screen.findByText('dead letter');
    fireEvent.click(screen.getByRole('button', { name: 'Retry run' }));
    await waitFor(() => expect(onRetryRun).toHaveBeenCalledWith('auto-1', 'failed-event'));
    expect(await screen.findByText('via retry')).toBeInTheDocument();
    expect(screen.getByText('Retry of failed-e')).toBeInTheDocument();
  });

  it('keeps example automations local and only allows idle live routines to run', () => {
    const idleAutomation: AutomationRecord = {
      ...liveAutomation,
      latestExecution: { ...liveAutomation.latestExecution!, status: 'completed' },
    };
    const onRunNow = vi.fn();
    const onToggle = vi.fn();
    render(<AutomationsView projects={projects} automations={[idleAutomation, demoAutomation]} onCreate={vi.fn()} onToggle={onToggle} onRunNow={onRunNow} onApprovalResolved={vi.fn()} />);
    const runButtons = screen.getAllByRole('button', { name: /run now/i });
    expect(runButtons[0]).toBeEnabled();
    expect(runButtons[1]).toBeDisabled();
    fireEvent.click(runButtons[0]);
    expect(onRunNow).toHaveBeenCalledWith(idleAutomation);
    fireEvent.click(screen.getByRole('button', { name: /pause daily digest/i }));
    expect(onToggle).toHaveBeenCalledWith(idleAutomation, false);
    expect(screen.getByText('Persistent scheduler')).toBeInTheDocument();
    expect(screen.getByText('completed')).toBeInTheDocument();
  });
});
