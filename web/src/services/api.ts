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
    modelOverride?: string | null
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

  async fetchMemories(projectName?: string, sessionId?: string): Promise<MemoryItem[]> {
    const params = new URLSearchParams();
    if (projectName) params.append('project_name', projectName);
    if (sessionId) params.append('session_id', sessionId);

    const queryStr = params.toString() ? `?${params.toString()}` : '';
    const res = await fetch(`${BASE_URL}/v1/memory${queryStr}`);
    return handleResponse<MemoryItem[]>(res);
  },
};
