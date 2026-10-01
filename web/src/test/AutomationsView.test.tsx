import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';
import { AutomationsView } from '../components/global/AutomationsView';
import type { AutomationRecord } from '../data/workspaceData';

describe('AutomationsView', () => {
  it('creates a scheduled prompt through the backend callback', async () => {
    const onCreate = vi.fn().mockResolvedValue(undefined);
    render(<AutomationsView automations={[]} onCreate={onCreate} onToggle={vi.fn()} onDelete={vi.fn()} onRunNow={vi.fn()} />);

    fireEvent.click(screen.getByRole('button', { name: /new automation/i }));
    fireEvent.change(screen.getByLabelText('Name'), { target: { value: 'Daily synthesis' } });
    fireEvent.change(screen.getByLabelText('What should AURA do?'), { target: { value: 'Summarize the latest work.' } });
    fireEvent.change(screen.getByLabelText('Schedule'), { target: { value: '604800' } });
    fireEvent.click(screen.getByRole('button', { name: 'Create automation' }));

    await waitFor(() => expect(onCreate).toHaveBeenCalledWith(expect.objectContaining({
      name: 'Daily synthesis',
      prompt: 'Summarize the latest work.',
      intervalSeconds: 604800,
      scope: 'global',
    })));
  });

  it('routes pause, run-now, and delete actions to persisted handlers', () => {
    const automation: AutomationRecord = {
      id: 'auto-1', name: 'Routine', description: 'A scheduled task', enabled: true, scope: 'global',
      trigger: 'Every day', actions: [], lastRun: 'Never', nextRun: 'tomorrow', status: 'ready', prompt: 'Summarize.', intervalSeconds: 86400,
    };
    const onToggle = vi.fn();
    const onRunNow = vi.fn();
    const onDelete = vi.fn();
    render(<AutomationsView automations={[automation]} onCreate={vi.fn()} onToggle={onToggle} onDelete={onDelete} onRunNow={onRunNow} />);

    fireEvent.click(screen.getByRole('button', { name: 'Pause Routine' }));
    fireEvent.click(screen.getByRole('button', { name: /run now/i }));
    fireEvent.click(screen.getByRole('button', { name: 'Delete Routine' }));
    expect(onToggle).toHaveBeenCalledWith(automation);
    expect(onRunNow).toHaveBeenCalledWith(automation);
    expect(onDelete).toHaveBeenCalledWith(automation);
  });
});
