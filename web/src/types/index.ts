export type ToolSupport = 'supported' | 'unsupported' | 'unknown'
export type ProviderKind = 'local' | 'cloud'
export type PrivacyStatus = 'local' | 'cloud' | 'airgap'

export interface ModelInfo {
  id: string
  label: string
  capabilities: string[]
  tool_support: ToolSupport
}

export interface ProviderInfo {
  id: string
  label: string
  kind: ProviderKind
  available: boolean
  base_url: string
  models: ModelInfo[]
  privacy_status: PrivacyStatus
}

export interface ModelCatalog {
  providers: ProviderInfo[]
}

export interface ModelProbeResponse {
  provider_id: string
  model_id: string
  tool_support: ToolSupport
  details: string
}

export interface SessionSummary {
  id: string
  title: string
  created_at: string
  updated_at: string
}

export interface ChatMessage {
  id?: string
  role: 'user' | 'assistant' | 'system' | 'tool'
  content: string
  created_at?: string
  tool_calls?: any[]
  tool_call_id?: string
}

export interface SessionDetail {
  id: string
  title: string
  created_at: string
  updated_at: string
  messages: ChatMessage[]
}

export interface ChatResponse {
  run_id: string
  session_id: string
  status: 'completed' | 'waiting_for_approval' | 'failed' | 'cancelled'
  response?: string
  approval_id?: string
  tool_results: any[]
}

export interface ApprovalDetail {
  id: string
  run_id: string
  session_id: string
  tool_call_id?: string
  tool_name: string
  tool_input: Record<string, any>
  risk_level: string
  status: string
  decision_notes?: string
  created_at: string
  decided_at?: string
}

export interface ApprovalDecisionResponse {
  approval_id: string
  status: string
  run_id: string
  execution_status: string
  final_response?: string
}

export interface RunEvent {
  id: string
  event_type: string
  payload: Record<string, any>
  created_at: string
}

export interface RunDetail {
  id: string
  session_id: string
  status: string
  user_message: string
  final_response?: string
  error_message?: string
  created_at: string
  updated_at: string
  events: RunEvent[]
}

export interface MemoryItem {
  id: string
  session_id?: string
  memory_type: string
  project_name?: string
  key: string
  content: string
  confidence: number
  metadata_json?: Record<string, any>
  created_at: string
}

export interface ResearchInspectorData {
  run_id: string
  child_run_id?: string
  goal?: {
    goal_id?: string
    user_query?: string
    project_name?: string
  }
  queries: Array<{
    query_id?: string
    query_text: string
    search_type?: string
    iteration?: number
    results_count?: number
  }>
  sources: Array<{
    source_id?: string
    canonical_id: string
    title: string
    authors?: string[]
    year?: number
    status?: string
    metadata?: Record<string, any>
  }>
  inspected_source_ids: string[]
  evidence: Array<{
    evidence_id: string
    source_id?: string
    source_title?: string
    source_locator?: string
    extracted_text: string
    confidence?: number
  }>
  claims: Array<{
    claim_id: string
    claim_text: string
    claim_type: string
    evidence_ids?: string[]
  }>
  status: string
}
