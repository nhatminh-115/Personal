import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';
import { AutomationsView } from '../components/global/AutomationsView';
import type { AutomationRecord, ProjectRecord } from '../data/workspaceData';

const projects: ProjectRecord[] = [{ id: 'p1', name: 'AURA', subtitle: 'Workspace', status: 'active', accent: 'cyan', updated: 'today', meta: '', thesis: '', next: '' }];
const liveAutomation: AutomationRecord = {
  id: 'auto-1', name: 'Daily digest', description: 'Summarize changes', instruction: 'Summarize updates.',
  enabled: true, scope: 'global', trigger: 'Every 1 day', actions: ['Run through AURA'],
  lastRun: 'Never', nextRun: 'Tomorrow', status: 'ready', source: 'live', intervalSeconds: 86400,
};
const demoAutomation: AutomationRecord = {
  id: 'demo-1', name: 'Example routine', description: 'Example only', enabled: true, scope: 'global',
  trigger: 'Every evening', actions: ['Example'], lastRun: 'Example', nextRun: 'Example', status: 'ready', source: 'demo',
};

describe('AutomationsView', () => {
  it('creates a persistent project-scoped instruction on the selected interval', async () => {
    const onCreate = vi.fn().mockResolvedValue(liveAutomation);
    render(<AutomationsView projects={projects} automations={[]} onCreate={onCreate} onToggle={vi.fn()} onRunNow={vi.fn()} />);
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

  it('keeps example automations local and only allows live routines to run', () => {
    const onRunNow = vi.fn();
    const onToggle = vi.fn();
    render(<AutomationsView projects={projects} automations={[liveAutomation, demoAutomation]} onCreate={vi.fn()} onToggle={onToggle} onRunNow={onRunNow} />);
    const runButtons = screen.getAllByRole('button', { name: /run now/i });
    expect(runButtons[0]).toBeEnabled();
    expect(runButtons[1]).toBeDisabled();
    fireEvent.click(runButtons[0]);
    expect(onRunNow).toHaveBeenCalledWith(liveAutomation);
    fireEvent.click(screen.getByRole('button', { name: /pause daily digest/i }));
    expect(onToggle).toHaveBeenCalledWith(liveAutomation, false);
    expect(screen.getByText('Persistent scheduler')).toBeInTheDocument();
  });
});
