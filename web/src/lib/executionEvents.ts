import type { ExecutionStep, RunEvent } from '../types';

export function mapRunEventsToExecutionSteps(events: RunEvent[]): ExecutionStep[] {
  if (!events || events.length === 0) {
    return [
      {
        id: 'step-done',
        label: 'Run completed',
        detail: 'Direct model response',
        status: 'done',
      },
    ];
  }

  return events.map((ev, idx) => {
    let label = ev.event_type;
    let detail = '';
    const p = ev.payload || {};

    switch (ev.event_type) {
      case 'request_received':
        label = 'Request received';
        detail = p.session_id ? `Session ${String(p.session_id).slice(0, 8)}…` : 'Session initialized';
        break;
      case 'routing_profile_resolved':
        label = 'Routing profile resolved';
        detail = p.profile_name ? `${p.profile_name} (v${p.profile_version ?? 1})` : 'Profile loaded';
        break;
      case 'model_selected':
        label = 'Model selected';
        detail = p.model_id ? `${p.model_id} (${p.provider_id || 'provider'})` : 'Auto candidate selected';
        break;
      case 'reasoning_effort_selected':
        label = 'Reasoning effort selected';
        detail = p.reasoning_effort || 'Adaptive';
        break;
      case 'fallback_considered':
        label = 'Fallback candidate evaluated';
        detail = p.candidate_model || 'Alternative provider candidate';
        break;
      case 'fallback_blocked':
        label = 'Fallback blocked';
        detail = p.reason || 'Privacy or capability boundary violation';
        break;
      case 'model_called':
        label = 'Model invocation';
        detail = p.model ? `Called ${p.model}` : 'Synthesis execution';
        break;
      case 'tool_requested':
        label = `Tool requested: ${p.tool_name || 'action'}`;
        detail = p.arguments ? JSON.stringify(p.arguments).slice(0, 50) : 'Arguments parsed';
        break;
      case 'tool_executed':
        label = `Tool executed: ${p.tool_name || 'action'}`;
        detail = p.status || 'Execution finished';
        break;
      case 'approval_required':
      case 'approval_waiting':
        label = 'Waiting for user authorization';
        detail = `${p.tool_name || 'Tool'} · ${p.risk_level || 'HIGH'} risk`;
        break;
      case 'approval_decision':
        label = `Approval decision: ${p.decision || 'recorded'}`;
        detail = p.decision_notes || p.notes || '';
        break;
      case 'delegation_started':
        label = `Delegated to ${p.specialist || 'specialist'}`;
        detail = p.goal || 'Subtask delegation started';
        break;
      case 'delegation_completed':
        label = 'Specialist execution completed';
        detail = p.specialist || 'Child run returned';
        break;
      case 'run_completed':
        label = 'Run completed';
        detail = 'Final response produced';
        break;
      case 'run_failed':
        label = 'Run failed';
        detail = p.error || 'Execution stopped';
        break;
      default:
        label = ev.event_type.replace(/_/g, ' ');
        detail = Object.keys(p).length > 0 ? Object.keys(p).slice(0, 3).join(', ') : '';
    }

    return {
      id: ev.id || `event-step-${idx}`,
      label,
      detail,
      status: ev.event_type.includes('failed') ? 'failed' : 'done',
      payload: p,
    };
  });
}
