import type { AuraFlowEdge, AuraFlowNode, WorkspaceExecutionEvent, WorkspaceExecutionTrace } from '../../types';

function executionNodeContent(event: WorkspaceExecutionEvent) {
  switch (event.event_type) {
    case 'model_selected': {
      const role = event.agent_role === 'root' ? 'Root' : event.agent_role ? `${event.agent_role} specialist` : 'Agent';
      return { title: `${role} · ${event.model ?? 'model selected'}`, body: event.provider ? `Provider: ${event.provider}` : 'Route selected', chip: 'ROUTER' };
    }
    case 'delegation_started':
      return { title: `Delegate · ${event.specialist ?? 'specialist'}`, body: 'Child runtime started', chip: 'SPECIALIST' };
    case 'delegation_completed':
      return { title: `${event.specialist ?? 'Specialist'} · ${event.status ?? 'completed'}`, body: 'Child runtime returned', chip: 'SPECIALIST' };
    case 'tool_requested':
      return { title: `Tool · ${event.tool_name ?? 'requested'}`, body: 'Tool call requested', chip: 'TOOL' };
    case 'tool_executed':
      return {
        title: `Result · ${event.tool_name ?? 'tool'}`,
        body: event.success === false ? `Failed${event.error_category ? ` · ${event.error_category}` : ''}` : 'Completed',
        chip: 'RESULT',
      };
    case 'approval_requested':
      return { title: `Approval · ${event.tool_name ?? 'tool action'}`, body: event.risk_level ? `Risk: ${event.risk_level}` : 'Approval requested', chip: 'APPROVAL' };
    case 'approval_granted':
      return { title: 'Approval granted', body: 'Execution resumed', chip: 'APPROVAL' };
    case 'approval_rejected':
      return { title: 'Approval rejected', body: 'Execution stopped', chip: 'APPROVAL' };
    case 'response_generated':
      return { title: 'Response generated', body: 'AURA prepared a response', chip: 'RESPONSE' };
    case 'run_failed':
      return { title: 'Run failed', body: 'Execution ended with an error', chip: 'RUN' };
    case 'run_cancelled':
      return { title: 'Run cancelled', body: 'Execution was cancelled', chip: 'RUN' };
    case 'run_completed':
    default:
      return { title: 'Run completed', body: 'Execution finished', chip: 'RUN' };
  }
}

function executionEdge(id: string, source: string, target: string): AuraFlowEdge {
  return { id, source, target, type: 'smart', animated: true, selectable: false, deletable: false, data: { edgeKind: 'execution' } };
}

/** Create a read-only Board projection from sanitized persisted run events. */
export function projectExecutionGraph(
  traces: WorkspaceExecutionTrace[],
  workspaceNodes: AuraFlowNode[],
): { nodes: AuraFlowNode[]; edges: AuraFlowEdge[] } {
  const workspaceNodeById = new Map(workspaceNodes.map((node) => [node.id, node]));
  const traceByRun = new Map(traces.map((trace) => [trace.run_id, trace]));
  const eventNodeById = new Map<string, string>();
  const eventByRunAndType = new Map<string, WorkspaceExecutionEvent[]>();
  const nodes: AuraFlowNode[] = [];
  const edges: AuraFlowEdge[] = [];

  const runDepth = (trace: WorkspaceExecutionTrace): number => {
    let depth = 0;
    let current = trace;
    const visited = new Set([trace.run_id]);
    while (current.parent_run_id && traceByRun.has(current.parent_run_id) && !visited.has(current.parent_run_id)) {
      visited.add(current.parent_run_id);
      current = traceByRun.get(current.parent_run_id)!;
      depth += 1;
    }
    return depth;
  };

  traces.forEach((trace, traceIndex) => {
    const orderedEvents = [...trace.events].sort((a, b) => a.created_at.localeCompare(b.created_at) || a.id.localeCompare(b.id));
    eventByRunAndType.set(trace.run_id, orderedEvents);
    const source = trace.user_object_id ? workspaceNodeById.get(trace.user_object_id) : undefined;
    const anchor = source?.position ?? { x: 80, y: traceIndex * 260 };
    const depth = runDepth(trace);
    const runEventNodes: string[] = [];

    orderedEvents.forEach((event, index) => {
      const id = `execution-${event.id}`;
      const content = executionNodeContent(event);
      eventNodeById.set(event.id, id);
      runEventNodes.push(id);
      nodes.push({
        id,
        type: 'aura',
        position: {
          x: anchor.x + 360 + (index % 4) * 270,
          y: anchor.y + depth * 220 + Math.floor(index / 4) * 140,
        },
        draggable: false,
        selectable: false,
        connectable: false,
        data: {
          kind: 'execution',
          eyebrow: 'EXECUTION TRACE',
          title: content.title,
          body: content.body,
          summary: content.body,
          density: 'compact',
          accent: event.success === false || event.event_type === 'run_failed' ? 'amber' : 'cyan',
          chip: content.chip,
          layer: 'execution',
        },
      } as AuraFlowNode);
      if (index > 0) edges.push(executionEdge(`execution-link-${orderedEvents[index - 1].id}-${event.id}`, runEventNodes[index - 1], id));
    });

    if (runEventNodes.length > 0 && trace.user_object_id && workspaceNodeById.has(trace.user_object_id)) {
      edges.push(executionEdge(`execution-start-${trace.run_id}`, trace.user_object_id, runEventNodes[0]));
    }
    if (runEventNodes.length > 0 && trace.response_object_id && workspaceNodeById.has(trace.response_object_id)) {
      edges.push(executionEdge(`execution-response-${trace.run_id}`, runEventNodes[runEventNodes.length - 1], trace.response_object_id));
    }
  });

  for (const trace of traces) {
    if (!trace.parent_run_id) continue;
    const parentEvents = eventByRunAndType.get(trace.parent_run_id) ?? [];
    const childEvents = eventByRunAndType.get(trace.run_id) ?? [];
    const handoff = parentEvents.find((event) => event.event_type === 'delegation_started' && event.child_run_id === trace.run_id);
    const returned = parentEvents.find((event) => event.event_type === 'delegation_completed' && event.child_run_id === trace.run_id);
    const handoffNode = handoff ? eventNodeById.get(handoff.id) : undefined;
    const returnNode = returned ? eventNodeById.get(returned.id) : undefined;
    const childFirst = childEvents[0] ? eventNodeById.get(childEvents[0].id) : undefined;
    const childLast = childEvents.at(-1) ? eventNodeById.get(childEvents.at(-1)!.id) : undefined;
    if (handoffNode && childFirst) edges.push(executionEdge(`execution-delegate-${trace.run_id}`, handoffNode, childFirst));
    if (childLast && returnNode) edges.push(executionEdge(`execution-return-${trace.run_id}`, childLast, returnNode));
  }

  return { nodes, edges };
}
