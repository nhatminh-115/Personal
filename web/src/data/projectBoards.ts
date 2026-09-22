import type { AuraFlowEdge, AuraFlowNode } from '../types';
import type { ProjectRecord } from './workspaceData';

export function makeProjectBoard(project: ProjectRecord): { nodes: AuraFlowNode[]; edges: AuraFlowEdge[] } {
  const prefix = project.id;
  const nodes: AuraFlowNode[] = [
    {
      id: `${prefix}-root-user`, type: 'aura', position: { x: 60, y: 220 },
      data: { kind: 'user', branch: 'Root', eyebrow: 'PROJECT QUESTION', title: project.name, body: project.next, summary: project.next, density: 'compact', accent: 'slate', layer: 'conversation' },
    },
    {
      id: `${prefix}-root-answer`, type: 'aura', position: { x: 410, y: 200 },
      data: { kind: 'answer', branch: 'Root', eyebrow: 'AURA · PROJECT SYNTHESIS', title: 'Current project state', body: project.thesis, summary: project.thesis, density: 'compact', accent: 'cyan', chip: 'Project context', layer: 'conversation' },
    },
    {
      id: `${prefix}-note`, type: 'aura', position: { x: 805, y: 95 },
      data: { kind: 'note', branch: 'Root', eyebrow: 'MANUAL NOTE', title: 'Next pressure test', body: project.next, summary: project.next, density: 'compact', accent: 'amber', manual: true, layer: 'knowledge' },
    },
    {
      id: `${prefix}-artifact`, type: 'aura', position: { x: 810, y: 330 },
      data: { kind: 'execution-result', branch: 'Root', eyebrow: 'PROJECT ARTIFACT', title: 'Working artifact', body: 'Files and generated results linked to this project can be pulled into branches and chat context.', summary: 'Project files and generated results.', density: 'compact', accent: 'green', layer: 'knowledge' },
    },
  ];
  const edges: AuraFlowEdge[] = [
    { id: `${prefix}-e1`, source: `${prefix}-root-user`, target: `${prefix}-root-answer`, type: 'smart', data: { edgeKind: 'reply' } },
    { id: `${prefix}-e2`, source: `${prefix}-root-answer`, target: `${prefix}-note`, type: 'smart', data: { edgeKind: 'semantic' } },
    { id: `${prefix}-e3`, source: `${prefix}-root-answer`, target: `${prefix}-artifact`, type: 'smart', data: { edgeKind: 'context' } },
  ];
  return { nodes, edges };
}
