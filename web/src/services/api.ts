import {
  ApprovalDecisionResponse,
  ApprovalDetail,
  ChatResponse,
  MemoryItem,
  ModelCatalog,
  ModelProbeResponse,
  ResearchInspectorData,
  RunDetail,
  SessionDetail,
  SessionSummary,
  EffectiveRouting,
  RoutingDecision,
  RoutingProfile,
  RunRoutingDecision,
  ReasoningEffort,
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
  return res.json() as Promise<T>;
}

export const api = {
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

  async fetchSessions(): Promise<SessionSummary[]> {
    const res = await fetch(`${BASE_URL}/v1/sessions`);
    return handleResponse<SessionSummary[]>(res);
  },

  async fetchSession(sessionId: string): Promise<SessionDetail> {
    const res = await fetch(`${BASE_URL}/v1/sessions/${encodeURIComponent(sessionId)}`);
    return handleResponse<SessionDetail>(res);
  },

  async sendChat(
    sessionId: string,
    message: string,
    projectName?: string,
    modelOverride?: string | null,
    reasoningOverride?: ReasoningEffort | null
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

    const res = await fetch(`${BASE_URL}/v1/chat`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload),
    });
    return handleResponse<ChatResponse>(res);
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
    const res = await fetch(`${BASE_URL}/v1/runs/${encodeURIComponent(runId)}`);
    return handleResponse<RunDetail>(res);
  },

  async fetchRunResearch(runId: string): Promise<ResearchInspectorData> {
    const res = await fetch(`${BASE_URL}/v1/runs/${encodeURIComponent(runId)}/research`);
    return handleResponse<ResearchInspectorData>(res);
  },

  async fetchRunRouting(runId: string): Promise<{ run_id: string; decisions: RunRoutingDecision[] }> {
    return handleResponse(await fetch(`${BASE_URL}/v1/runs/${encodeURIComponent(runId)}/routing`));
  },

  async fetchMemories(projectName?: string, sessionId?: string): Promise<MemoryItem[]> {
    const params = new URLSearchParams();
    if (projectName) params.append('project_name', projectName);
    if (sessionId) params.append('session_id', sessionId);

    const queryStr = params.toString() ? `?${params.toString()}` : '';
    const res = await fetch(`${BASE_URL}/v1/memory${queryStr}`);
    return handleResponse<MemoryItem[]>(res);
  },
};
