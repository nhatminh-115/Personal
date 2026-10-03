import {
  ApprovalDecisionResponse,
  ApprovalDetail,
  RoutingConfirmationDetail,
  RoutingConfirmationDecisionResponse,
  ChatResponse,
  MemoryItem,
  ModelCatalog,
  ModelProbeResponse,
  ResearchInspectorData,
  RunDetail,
  SessionDetail,
  SessionExecutionState,
  SessionSummary,
  EffectiveRouting,
  RoutingDecision,
  RoutingProfile,
  RoutingProfileValidation,
  RunRoutingDecision,
  ReasoningEffort,
  WorkspaceEdge,
  WorkspaceGraph,
  WorkspaceExecutionHistory,
  CapabilityProvidersResponse,
  WorkspaceLayout,
  WorkspaceNoteRecord,
  WorkspaceObject,
  StudySessionRecord,
  StudyCardRecord,
  WorkspaceLibraryReferenceRecord,
  WorkspaceProjectRecord,
  WorkspaceSearchResult,
  WorkspaceContextPreview,
  AutomationRecordResponse,
  AutomationExecutionRecord,
  AutomationRunResponse,
} from '../types';

export class ApiError extends Error {
  status: number;
  code?: string;
  details?: any;

  constructor(status: number, message: string, code?: string, details?: any) {
    super(message);
    this.name = 'ApiError';
    this.status = status;
    this.code = code;
    this.details = details;
  }
}

const BASE_URL = ''; // Proxy forwards /v1 to FastAPI in dev

async function handleResponse<T>(res: Response): Promise<T> {
  if (!res.ok) {
    const text = await res.text();
    try {
      const errJson = JSON.parse(text);
      throw new ApiError(
        res.status,
        errJson.message || errJson.detail || `Request failed with status ${res.status}`,
        errJson.error || errJson.code,
        errJson.details || errJson
      );
    } catch (e: any) {
      if (e instanceof ApiError) throw e;
      throw new ApiError(res.status, `Request failed with status ${res.status}: ${text}`);
    }
  }
  if (res.status === 204) return undefined as T;
  return res.json() as Promise<T>;
}

async function fetchAllCursorPages<T>(path: string, pageSize = 100): Promise<T[]> {
  const items: T[] = [];
  let cursor: string | null = null;
  do {
    const params = new URLSearchParams();
    if (cursor) {
      params.set('page_size', String(pageSize));
      params.set('cursor', cursor);
    }
    const query = params.toString();
    const response = await fetch(`${BASE_URL}${path}${query ? `?${query}` : ''}`);
    items.push(...await handleResponse<T[]>(response));
    cursor = response.headers?.get('X-Next-Cursor') ?? null;
  } while (cursor);
  return items;
}

export const api = {
  async fetchCapabilityProviders(): Promise<CapabilityProvidersResponse> {
    return handleResponse(await fetch(`${BASE_URL}/v1/capabilities/providers`));
  },

  async fetchModels(): Promise<ModelCatalog> {
    const res = await fetch(`${BASE_URL}/v1/models`);
    return handleResponse<ModelCatalog>(res);
  },

  async refreshModels(): Promise<ModelCatalog> {
    const res = await fetch(`${BASE_URL}/v1/models/refresh`, { method: 'POST' });
    return handleResponse<ModelCatalog>(res);
  },

  async probeModel(providerId: string, modelId: string): Promise<ModelProbeResponse> {
    const res = await fetch(`${BASE_URL}/v1/models/probe`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ provider_id: providerId, model_id: modelId }),
    });
    return handleResponse<ModelProbeResponse>(res);
  },

  async fetchRoutingProfiles(): Promise<RoutingProfile[]> {
    return handleResponse(await fetch(`${BASE_URL}/v1/routing/profiles`));
  },

  async fetchRoutingProfile(id: string): Promise<RoutingProfile> {
    return handleResponse(await fetch(`${BASE_URL}/v1/routing/profiles/${encodeURIComponent(id)}`));
  },

  async saveRoutingProfile(profile: RoutingProfile): Promise<RoutingProfile> {
    const update = Boolean(profile.id && profile.id !== 'system-balanced');
    const res = await fetch(`${BASE_URL}/v1/routing/profiles${update ? `/${encodeURIComponent(profile.id!)}` : ''}`, {
      method: update ? 'PUT' : 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(profile),
    });
    return handleResponse<RoutingProfile>(res);
  },

  async duplicateRoutingProfile(id: string): Promise<RoutingProfile> {
    return handleResponse(await fetch(`${BASE_URL}/v1/routing/profiles/${encodeURIComponent(id)}/duplicate`, { method: 'POST' }));
  },

  async validateRoutingProfile(id: string): Promise<RoutingProfileValidation> {
    return handleResponse(await fetch(`${BASE_URL}/v1/routing/profiles/${encodeURIComponent(id)}/validate`, { method: 'POST' }));
  },

  async setDefaultRoutingProfile(profileId: string | null): Promise<void> {
    await handleResponse(await fetch(`${BASE_URL}/v1/routing/default`, {
      method: 'PUT', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ profile_id: profileId }),
    }));
  },

  async deleteRoutingProfile(id: string): Promise<void> {
    await handleResponse(await fetch(`${BASE_URL}/v1/routing/profiles/${encodeURIComponent(id)}`, { method: 'DELETE' }));
  },

  async fetchEffectiveRouting(projectName?: string, sessionId?: string): Promise<EffectiveRouting> {
    const params = new URLSearchParams();
    if (projectName) params.set('project_name', projectName);
    if (sessionId) params.set('session_id', sessionId);
    return handleResponse(await fetch(`${BASE_URL}/v1/routing/effective${params.size ? `?${params}` : ''}`));
  },

  async assignProjectRouting(projectName: string, profileId: string): Promise<void> {
    const params = new URLSearchParams({ profile_id: profileId });
    await handleResponse(await fetch(`${BASE_URL}/v1/routing/assignments/${encodeURIComponent(projectName)}?${params}`, { method: 'POST' }));
  },

  async fetchProjectRouting(projectName: string): Promise<{ project_name: string; routing_profile_id: string | null }> {
    return handleResponse(await fetch(`${BASE_URL}/v1/routing/assignments/${encodeURIComponent(projectName)}`));
  },

  async assignSessionRouting(sessionId: string, profileId: string | null): Promise<void> {
    await handleResponse(await fetch(`${BASE_URL}/v1/routing/sessions/${encodeURIComponent(sessionId)}`, {
      method: 'PUT', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ profile_id: profileId }),
    }));
  },

  async fetchSessionRouting(sessionId: string): Promise<{ session_id: string; routing_profile_id: string | null }> {
    return handleResponse(await fetch(`${BASE_URL}/v1/routing/sessions/${encodeURIComponent(sessionId)}`));
  },

  async fetchRoutingPreview(input: {
    role: string;
    context?: Record<string, any>;
    message_override?: string | null;
    reasoning_override?: ReasoningEffort | null;
    profile_draft?: RoutingProfile;
    project_name?: string;
    session_id?: string;
  }): Promise<RoutingDecision> {
    return handleResponse(await fetch(`${BASE_URL}/v1/routing/preview`, {
      method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(input),
    }));
  },

  async fetchSessions(projectName?: string, cursor?: string | null): Promise<{ items: SessionSummary[]; nextCursor: string | null }> {
    const params = new URLSearchParams({ page_size: '25' });
    if (projectName) params.set('project_name', projectName);
    if (cursor) params.set('cursor', cursor);
    const res = await fetch(`${BASE_URL}/v1/sessions?${params.toString()}`);
    const items = await handleResponse<SessionSummary[]>(res);
    return { items, nextCursor: res.headers?.get('X-Next-Cursor') ?? null };
  },

  async fetchSession(sessionId: string, cursor?: string | null): Promise<SessionDetail> {
    const params = new URLSearchParams();
    if (cursor) params.set('cursor', cursor);
    const query = params.size ? `?${params.toString()}` : '';
    const res = await fetch(`${BASE_URL}/v1/sessions/${encodeURIComponent(sessionId)}${query}`);
    return handleResponse<SessionDetail>(res);
  },

  async fetchSessionExecutionState(sessionId: string): Promise<SessionExecutionState> {
    return handleResponse<SessionExecutionState>(await fetch(`${BASE_URL}/v1/sessions/${encodeURIComponent(sessionId)}/state`));
  },

  async previewWorkspaceContext(projectName: string, selectedObjectIds: string[]): Promise<WorkspaceContextPreview> {
    return handleResponse(await fetch(`${BASE_URL}/v1/workspace/projects/${encodeURIComponent(projectName)}/context/preview`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ selected_object_ids: [...new Set(selectedObjectIds)] }),
    }));
  },

  async fetchWorkspaceExecutionHistory(projectName: string, executionCursor?: string | null): Promise<WorkspaceExecutionHistory> {
    const params = new URLSearchParams();
    if (executionCursor) params.set('execution_cursor', executionCursor);
    const query = params.size ? `?${params.toString()}` : '';
    return handleResponse(await fetch(`${BASE_URL}/v1/workspace/projects/${encodeURIComponent(projectName)}/execution${query}`));
  },

  async fetchWorkspaceGraph(projectName: string, executionCursor?: string | null): Promise<WorkspaceGraph> {
    const pageSize = 250;
    const firstParams = new URLSearchParams();
    if (executionCursor) firstParams.set('execution_cursor', executionCursor);
    const firstQueryString = firstParams.toString();
    const firstQuery = firstQueryString ? `?${firstQueryString}` : '';
    const firstPage = await handleResponse<WorkspaceGraph>(await fetch(
      `${BASE_URL}/v1/workspace/projects/${encodeURIComponent(projectName)}/graph${firstQuery}`,
    ));
    const objects = [...firstPage.objects];
    const edges = [...firstPage.edges];
    let objectCursor = firstPage.objects_next_cursor ?? null;
    let edgeCursor = firstPage.edges_next_cursor ?? null;
    let objectsExhausted = !objectCursor;
    let edgesExhausted = !edgeCursor;

    while (!objectsExhausted || !edgesExhausted) {
      const params = new URLSearchParams();
      params.set('object_page_size', String(pageSize));
      params.set('edge_page_size', String(pageSize));
      if (objectCursor) params.set('object_cursor', objectCursor);
      if (objectsExhausted) params.set('objects_exhausted', 'true');
      if (edgeCursor) params.set('edge_cursor', edgeCursor);
      if (edgesExhausted) params.set('edges_exhausted', 'true');
      params.set('include_project_state', 'false');
      if (executionCursor) params.set('execution_cursor', executionCursor);
      const queryString = params.toString();
      const page = await handleResponse<WorkspaceGraph>(await fetch(
        `${BASE_URL}/v1/workspace/projects/${encodeURIComponent(projectName)}/graph?${queryString}`,
      ));
      objects.push(...page.objects);
      edges.push(...page.edges);
      objectCursor = page.objects_next_cursor ?? null;
      edgeCursor = page.edges_next_cursor ?? null;
      objectsExhausted = !objectCursor;
      edgesExhausted = !edgeCursor;
    }

    return { ...firstPage, objects, edges, objects_next_cursor: null };
  },

  async fetchWorkspaceNotes(): Promise<WorkspaceNoteRecord[]> {
    return fetchAllCursorPages<WorkspaceNoteRecord>('/v1/workspace/notes');
  },

  async fetchWorkspaceNotesPage(cursor?: string | null, pageSize = 50): Promise<{ items: WorkspaceNoteRecord[]; nextCursor: string | null }> {
    const params = new URLSearchParams({ page_size: String(pageSize) });
    if (cursor) params.set('cursor', cursor);
    const response = await fetch(`${BASE_URL}/v1/workspace/notes?${params.toString()}`);
    return {
      items: await handleResponse<WorkspaceNoteRecord[]>(response),
      nextCursor: response.headers?.get('X-Next-Cursor') ?? null,
    };
  },

  async createWorkspaceNote(input: Omit<WorkspaceNoteRecord, 'id' | 'created_at' | 'updated_at'>): Promise<WorkspaceNoteRecord> {
    return handleResponse(await fetch(`${BASE_URL}/v1/workspace/notes`, {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(input),
    }));
  },

  async updateWorkspaceNote(id: string, input: Omit<WorkspaceNoteRecord, 'id' | 'created_at' | 'updated_at'>): Promise<WorkspaceNoteRecord> {
    return handleResponse(await fetch(`${BASE_URL}/v1/workspace/notes/${encodeURIComponent(id)}`, {
      method: 'PUT', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(input),
    }));
  },

  async fetchStudySessions(): Promise<StudySessionRecord[]> {
    return fetchAllCursorPages<StudySessionRecord>('/v1/study/sessions');
  },

  async fetchStudySessionsPage(cursor?: string | null): Promise<{ items: StudySessionRecord[]; nextCursor: string | null }> {
    const params = new URLSearchParams({ page_size: '100' });
    if (cursor) params.set('cursor', cursor);
    const response = await fetch(`${BASE_URL}/v1/study/sessions?${params.toString()}`);
    const items = await handleResponse<StudySessionRecord[]>(response);
    return { items, nextCursor: response.headers?.get('X-Next-Cursor') ?? null };
  },

  async startStudySession(trackId: string, trackTitle: string, materialId?: string, materialProjectName?: string): Promise<StudySessionRecord> {
    return handleResponse(await fetch(`${BASE_URL}/v1/study/sessions`, {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        track_id: trackId,
        track_title: trackTitle,
        ...(materialId ? { material_id: materialId } : {}),
        ...(materialProjectName ? { material_project_name: materialProjectName } : {}),
      }),
    }));
  },

  async updateStudySessionReflection(sessionId: string, reflection: string): Promise<StudySessionRecord> {
    return handleResponse(await fetch(`${BASE_URL}/v1/study/sessions/${encodeURIComponent(sessionId)}/reflection`, {
      method: 'PUT',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ reflection }),
    }));
  },

  async fetchStudyCards(): Promise<StudyCardRecord[]> {
    return fetchAllCursorPages<StudyCardRecord>('/v1/study/cards');
  },

  async fetchStudyCardsPage(cursor?: string | null): Promise<{ items: StudyCardRecord[]; nextCursor: string | null }> {
    const params = new URLSearchParams({ page_size: '100' });
    if (cursor) params.set('cursor', cursor);
    const response = await fetch(`${BASE_URL}/v1/study/cards?${params.toString()}`);
    const items = await handleResponse<StudyCardRecord[]>(response);
    return { items, nextCursor: response.headers?.get('X-Next-Cursor') ?? null };
  },

  async createStudyCard(sessionId: string, question: string, answer: string): Promise<StudyCardRecord> {
    return handleResponse(await fetch(`${BASE_URL}/v1/study/sessions/${encodeURIComponent(sessionId)}/cards`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ question, answer }),
    }));
  },

  async updateStudyCard(cardId: string, sessionId: string, question: string, answer: string): Promise<StudyCardRecord> {
    return handleResponse(await fetch(`${BASE_URL}/v1/study/sessions/${encodeURIComponent(sessionId)}/cards/${encodeURIComponent(cardId)}`, {
      method: 'PUT',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ question, answer }),
    }));
  },

  async deleteStudyCard(cardId: string, sessionId: string): Promise<void> {
    await handleResponse(await fetch(`${BASE_URL}/v1/study/sessions/${encodeURIComponent(sessionId)}/cards/${encodeURIComponent(cardId)}`, {
      method: 'DELETE',
    }));
  },

  async completeStudySession(sessionId: string): Promise<StudySessionRecord> {
    return handleResponse(await fetch(`${BASE_URL}/v1/study/sessions/${encodeURIComponent(sessionId)}/complete`, {
      method: 'POST',
    }));
  },

  async fetchWorkspaceLibrary(): Promise<WorkspaceLibraryReferenceRecord[]> {
    return fetchAllCursorPages<WorkspaceLibraryReferenceRecord>('/v1/workspace/library');
  },

  async fetchWorkspaceLibraryPage(cursor?: string | null, pageSize = 50): Promise<{ items: WorkspaceLibraryReferenceRecord[]; nextCursor: string | null }> {
    const params = new URLSearchParams({ page_size: String(pageSize) });
    if (cursor) params.set('cursor', cursor);
    const response = await fetch(`${BASE_URL}/v1/workspace/library?${params.toString()}`);
    return {
      items: await handleResponse<WorkspaceLibraryReferenceRecord[]>(response),
      nextCursor: response.headers?.get('X-Next-Cursor') ?? null,
    };
  },

  async fetchWorkspaceProjects(): Promise<WorkspaceProjectRecord[]> {
    return fetchAllCursorPages<WorkspaceProjectRecord>('/v1/workspace/projects');
  },

  async searchWorkspace(query: string, projectName?: string): Promise<WorkspaceSearchResult[]> {
    const params = new URLSearchParams({ query });
    if (projectName) params.set('project_name', projectName);
    return handleResponse(await fetch(`${BASE_URL}/v1/workspace/search?${params.toString()}`));
  },

  async createWorkspaceProject(input: { id: string; name: string; subtitle: string }): Promise<WorkspaceProjectRecord> {
    return handleResponse(await fetch(`${BASE_URL}/v1/workspace/projects`, {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(input),
    }));
  },

  async fetchAutomations(cursor?: string | null, pageSize = 50): Promise<{
    automations: AutomationRecordResponse[];
    nextCursor: string | null;
  }> {
    const params = new URLSearchParams({ page_size: String(pageSize) });
    if (cursor) params.set('cursor', cursor);
    const response = await fetch(`${BASE_URL}/v1/automations?${params.toString()}`);
    return {
      automations: await handleResponse<AutomationRecordResponse[]>(response),
      nextCursor: response.headers?.get('X-Next-Cursor') ?? null,
    };
  },

  async fetchAutomationStatuses(ids: string[]): Promise<AutomationRecordResponse[]> {
    if (ids.length === 0) return [];
    const params = new URLSearchParams();
    ids.forEach((id) => params.append('automation_ids', id));
    return handleResponse(await fetch(`${BASE_URL}/v1/automations/status?${params.toString()}`));
  },

  async fetchAutomationSummary(): Promise<{ total: number; enabled: number }> {
    return handleResponse(await fetch(`${BASE_URL}/v1/automations/summary`));
  },

  async fetchAutomationRuns(id: string, pageSize = 10, cursor?: string | null): Promise<{
    runs: AutomationExecutionRecord[];
    nextCursor: string | null;
  }> {
    const params = new URLSearchParams({ page_size: String(pageSize) });
    if (cursor) params.set('cursor', cursor);
    const response = await fetch(`${BASE_URL}/v1/automations/${encodeURIComponent(id)}/runs?${params.toString()}`);
    return {
      runs: await handleResponse<AutomationExecutionRecord[]>(response),
      nextCursor: response.headers?.get('X-Next-Cursor') ?? null,
    };
  },

  async createAutomation(input: {
    name: string;
    description: string;
    instruction: string;
    scope: 'global' | 'project';
    project_name?: string;
    interval_seconds: number;
  }): Promise<AutomationRecordResponse> {
    return handleResponse(await fetch(`${BASE_URL}/v1/automations`, {
      method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(input),
    }));
  },

  async setAutomationEnabled(id: string, enabled: boolean): Promise<AutomationRecordResponse> {
    return handleResponse(await fetch(`${BASE_URL}/v1/automations/${encodeURIComponent(id)}`, {
      method: 'PUT', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ enabled }),
    }));
  },

  async runAutomation(id: string): Promise<AutomationRunResponse> {
    return handleResponse(await fetch(`${BASE_URL}/v1/automations/${encodeURIComponent(id)}/run`, { method: 'POST' }));
  },

  async createWorkspaceLibraryReference(input: Omit<WorkspaceLibraryReferenceRecord, 'created_at' | 'updated_at'>): Promise<WorkspaceLibraryReferenceRecord> {
    return handleResponse(await fetch(`${BASE_URL}/v1/workspace/library`, {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(input),
    }));
  },

  async updateWorkspaceLibraryReference(id: string, input: Omit<WorkspaceLibraryReferenceRecord, 'id' | 'created_at' | 'updated_at'>): Promise<WorkspaceLibraryReferenceRecord> {
    return handleResponse(await fetch(`${BASE_URL}/v1/workspace/library/${encodeURIComponent(id)}`, {
      method: 'PUT', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(input),
    }));
  },

  async deleteWorkspaceLibraryReference(id: string): Promise<void> {
    await handleResponse(await fetch(`${BASE_URL}/v1/workspace/library/${encodeURIComponent(id)}`, { method: 'DELETE' }));
  },

  async attachWorkspaceSession(projectName: string, sessionId: string): Promise<{ session_id: string; project_name: string }> {
    return handleResponse(await fetch(`${BASE_URL}/v1/workspace/projects/${encodeURIComponent(projectName)}/sessions/${encodeURIComponent(sessionId)}`, { method: 'POST' }));
  },

  async createWorkspaceObject(projectName: string, input: {
    id?: string;
    object_type: 'manual_note' | 'context_bridge' | 'context_set' | 'conversation_branch';
    title: string;
    content: string;
    metadata_json?: Record<string, unknown>;
    source_object_ids?: string[];
  }): Promise<WorkspaceObject> {
    return handleResponse(await fetch(`${BASE_URL}/v1/workspace/projects/${encodeURIComponent(projectName)}/objects`, {
      method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(input),
    }));
  },

  async deleteWorkspaceObject(projectName: string, objectId: string): Promise<void> {
    await handleResponse(await fetch(`${BASE_URL}/v1/workspace/projects/${encodeURIComponent(projectName)}/objects/${encodeURIComponent(objectId)}`, { method: 'DELETE' }));
  },

  async updateWorkspaceObject(projectName: string, objectId: string, input: {
    title: string; content: string; metadata_json?: Record<string, unknown>;
  }): Promise<WorkspaceObject> {
    return handleResponse(await fetch(`${BASE_URL}/v1/workspace/projects/${encodeURIComponent(projectName)}/objects/${encodeURIComponent(objectId)}`, {
      method: 'PUT', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(input),
    }));
  },

  async createWorkspaceEdge(projectName: string, input: {
    source_object_id: string; target_object_id: string; relation_type: string;
    edge_family: Extract<WorkspaceEdge['edge_family'], 'semantic' | 'context'>; metadata_json?: Record<string, unknown>;
  }): Promise<WorkspaceEdge> {
    return handleResponse(await fetch(`${BASE_URL}/v1/workspace/projects/${encodeURIComponent(projectName)}/edges`, {
      method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(input),
    }));
  },

  async deleteWorkspaceEdges(projectName: string, edgeIds: string[]): Promise<void> {
    await handleResponse(await fetch(`${BASE_URL}/v1/workspace/projects/${encodeURIComponent(projectName)}/edges`, {
      method: 'DELETE',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ edge_ids: edgeIds }),
    }));
  },

  async restoreWorkspaceEdges(
    projectName: string,
    edges: Array<Pick<WorkspaceEdge, 'id' | 'source_object_id' | 'target_object_id' | 'relation_type' | 'edge_family' | 'metadata_json'>>,
  ): Promise<WorkspaceEdge[]> {
    return handleResponse(await fetch(`${BASE_URL}/v1/workspace/projects/${encodeURIComponent(projectName)}/edges/batch-restore`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ edges }),
    }));
  },

  async deleteWorkspaceEdge(projectName: string, edgeId: string): Promise<void> {
    await handleResponse(await fetch(`${BASE_URL}/v1/workspace/projects/${encodeURIComponent(projectName)}/edges/${encodeURIComponent(edgeId)}`, { method: 'DELETE' }));
  },

  async putWorkspaceLayout(projectName: string, layout: Record<string, any>, expectedRevision: number): Promise<WorkspaceLayout> {
    return handleResponse(await fetch(`${BASE_URL}/v1/workspace/projects/${encodeURIComponent(projectName)}/layout`, {
      method: 'PUT', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ layout, expected_revision: expectedRevision }),
    }));
  },

  async sendChat(
    sessionId: string,
    message: string,
    projectName?: string,
    modelOverride?: string | null,
    reasoningOverride?: ReasoningEffort | null,
    contextObjectIds: string[] = [],
    taskType?: 'research' | 'coding' | 'writing' | null,
  ): Promise<ChatResponse> {
    const payload: Record<string, any> = {
      session_id: sessionId,
      message,
    };
    if (projectName) {
      payload.project_name = projectName;
  }

    if (modelOverride) {
      payload.model_override = modelOverride;
    }
    if (reasoningOverride) payload.reasoning_override = reasoningOverride;
    if (contextObjectIds.length > 0) payload.context_object_ids = [...new Set(contextObjectIds)];
    if (taskType) payload.task_type = taskType;

    const res = await fetch(`${BASE_URL}/v1/chat`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload),
    });
    return handleResponse<ChatResponse>(res);
  },

  async fetchPendingRoutingConfirmations(sessionId: string, pageSize = 25, cursor?: string | null): Promise<{
    items: RoutingConfirmationDetail[];
    nextCursor: string | null;
  }> {
    const params = new URLSearchParams({ session_id: sessionId, page_size: String(pageSize) });
    if (cursor) params.set('cursor', cursor);
    const response = await fetch(`${BASE_URL}/v1/routing-confirmations/pending?${params.toString()}`);
    return {
      items: await handleResponse<RoutingConfirmationDetail[]>(response),
      nextCursor: response.headers?.get('X-Next-Cursor') ?? null,
    };
  },

  async fetchRoutingConfirmation(id: string): Promise<RoutingConfirmationDetail> {
    return handleResponse(await fetch(`${BASE_URL}/v1/routing-confirmations/${encodeURIComponent(id)}`));
  },

  async decideRoutingConfirmation(
    id: string,
    decision: 'approved' | 'rejected',
    decisionNotes?: string,
  ): Promise<RoutingConfirmationDecisionResponse> {
    return handleResponse(await fetch(`${BASE_URL}/v1/routing-confirmations/${encodeURIComponent(id)}/decision`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ decision, ...(decisionNotes ? { decision_notes: decisionNotes } : {}) }),
    }));
  },

  async fetchApproval(approvalId: string): Promise<ApprovalDetail> {
    const res = await fetch(`${BASE_URL}/v1/approvals/${encodeURIComponent(approvalId)}`);
    return handleResponse<ApprovalDetail>(res);
  },

  async submitApproval(
    approvalId: string,
    decision: 'approved' | 'rejected' | 'edited',
    decisionNotes?: string,
    editedInput?: Record<string, any>
  ): Promise<ApprovalDecisionResponse> {
    const payload: Record<string, any> = { decision };
    if (decisionNotes) payload.decision_notes = decisionNotes;
    if (editedInput) payload.edited_input = editedInput;

    const res = await fetch(`${BASE_URL}/v1/approvals/${encodeURIComponent(approvalId)}/decision`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload),
    });
    return handleResponse<ApprovalDecisionResponse>(res);
  },

  async fetchRunDetails(runId: string): Promise<RunDetail> {
    const path = `${BASE_URL}/v1/runs/${encodeURIComponent(runId)}`;
    let cursor: string | null = null;
    let run: RunDetail | null = null;
    const events: RunDetail['events'] = [];
    do {
      const params = new URLSearchParams({ page_size: '100' });
      if (cursor) params.set('cursor', cursor);
      const res = await fetch(`${path}?${params.toString()}`);
      const page = await handleResponse<RunDetail>(res);
      run ??= page;
      events.push(...page.events);
      cursor = res.headers?.get('X-Next-Cursor') ?? null;
    } while (cursor);
    return { ...run!, events };
  },

  async fetchRunResearch(runId: string): Promise<ResearchInspectorData> {
    const res = await fetch(`${BASE_URL}/v1/runs/${encodeURIComponent(runId)}/research`);
    return handleResponse<ResearchInspectorData>(res);
  },

  async fetchRunRouting(runId: string): Promise<{ run_id: string; decisions: RunRoutingDecision[] }> {
    return handleResponse(await fetch(`${BASE_URL}/v1/runs/${encodeURIComponent(runId)}/routing`));
  },

  async fetchMemories(projectName?: string, sessionId?: string, cursor?: string | null): Promise<{
    items: MemoryItem[];
    nextCursor: string | null;
  }> {
    const params = new URLSearchParams();
    if (projectName) params.append('project_name', projectName);
    if (sessionId) params.append('session_id', sessionId);
    params.set('page_size', '25');
    if (cursor) params.set('cursor', cursor);

    const queryStr = params.toString() ? `?${params.toString()}` : '';
    const res = await fetch(`${BASE_URL}/v1/memory${queryStr}`);
    return {
      items: await handleResponse<MemoryItem[]>(res),
      nextCursor: res.headers?.get('X-Next-Cursor') ?? null,
    };
  },
};
