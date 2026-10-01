import type { Edge, Node } from '@xyflow/react';

export type WorkspaceMode = 'chat' | 'board' | 'split';
export type AuraWorkMode = 'auto' | 'research' | 'code' | 'write';
export type ContextScope = 'branch' | 'project' | 'selection' | 'library';
export type NodeDensity = 'collapsed' | 'compact' | 'full';
export type AuraNodeKind =
  | 'user'
  | 'answer'
  | 'note'
  | 'bridge'
  | 'merge'
  | 'execution-result'
  | 'paper'
  | 'code-result'
  | 'execution';

export type LayerKey = 'conversation' | 'knowledge' | 'execution';

export interface ExecutionStep {
  id: string;
  label: string;
  detail?: string;
  status: 'done' | 'running' | 'queued' | 'failed';
  children?: ExecutionStep[];
  payload?: Record<string, any>;
}

export interface AuraNodeData extends Record<string, unknown> {
  kind: AuraNodeKind;
  branch?: 'Root' | 'A' | 'B' | 'C';
  eyebrow?: string;
  title: string;
  body: string;
  summary?: string;
  density: NodeDensity;
  manual?: boolean;
  sourceCount?: number;
  tokens?: string;
  accent?: 'cyan' | 'purple' | 'amber' | 'green' | 'slate';
  chip?: string;
  running?: boolean;
  messageId?: string;
  layer: LayerKey;
  from?: string;
  to?: string;
  bridgeOptions?: {
    conclusions: boolean;
    observations: boolean;
    failed: boolean;
    artifacts: boolean;
  };
  bridgeNote?: string;
  mergeItems?: string[];
  execution?: ExecutionStep[];
  onCycleDensity?: (id: string) => void;
  onBranch?: (id: string) => void;
  onChangeBody?: (id: string, body: string) => void;
  onBridgeApply?: (id: string) => void;
  onBridgeOption?: (id: string, key: 'conclusions' | 'observations' | 'failed' | 'artifacts', value: boolean) => void;
  onContinueMerge?: (id: string) => void;
}

export type AuraFlowNode = Node<AuraNodeData>;
export type AuraFlowEdge = Edge<{
  edgeKind?: 'reply' | 'context' | 'semantic' | 'execution';
  onDelete?: (id: string) => void;
}>;

export interface AIContextItem {
  id: string;
  kind: 'turn' | 'note' | 'paper' | 'code' | 'file';
  title: string;
  detail: string;
  tokens: number;
  included: boolean;
  nodeId?: string;
}

export interface AIProvenanceItem {
  id: string;
  label: string;
  detail: string;
  kind: 'source' | 'context' | 'artifact';
  nodeId?: string;
}

export interface ChatMessage {
  id?: string;
  role: 'user' | 'assistant' | 'system' | 'tool';
  content: string;
  branch?: 'Root' | 'A' | 'B' | 'C';
  nodeId?: string;
  executionLabel?: string;
  execution?: ExecutionStep[];
  timestamp?: string;
  created_at?: string;
  specialist?: string;
  status?: string;
  routeLabel?: string;
  reasoningLabel?: string;
  contextTokens?: number;
  contextObjectIds?: string[];
  provenance?: AIProvenanceItem[];
  tool_calls?: any[];
  tool_call_id?: string;
  onCycleDensity?: (id: string) => void;
  onBranch?: (id: string) => void;
  onChangeBody?: (id: string, body: string) => void;
  onBridgeApply?: (id: string) => void;
  onBridgeOption?: (id: string, key: 'conclusions' | 'observations' | 'failed' | 'artifacts', value: boolean) => void;
  onContinueMerge?: (id: string) => void;
}

export interface ToastMessage {
  id: number;
  title: string;
  detail?: string;
}

// Backend Integration Types
export type ToolSupport = 'supported' | 'unsupported' | 'unknown';
export type ProviderKind = 'local' | 'cloud';
export type PrivacyStatus = 'local' | 'cloud' | 'airgap';

export interface ModelInfo {
  id: string;
  label: string;
  capabilities: string[];
  tool_support: ToolSupport;
  context_window?: number | null;
  reasoning_support?: 'instant' | 'low' | 'medium' | 'high' | 'max' | 'fixed_by_model' | 'unsupported' | 'unknown' | null;
  vision_support?: boolean | null;
  structured_output_support?: boolean | null;
}

export interface ProviderInfo {
  id: string;
  label: string;
  kind: ProviderKind;
  available: boolean;
  base_url: string;
  models: ModelInfo[];
  privacy_status: PrivacyStatus;
}

export interface ModelCatalog {
  providers: ProviderInfo[];
}

export interface ModelProbeResponse {
  provider_id: string;
  model_id: string;
  tool_support: ToolSupport;
  details: string;
}

export interface SessionSummary {
  id: string;
  title: string;
  created_at: string;
  updated_at: string;
}

export interface SessionDetail {
  id: string;
  title: string;
  created_at: string;
  updated_at: string;
  messages: ChatMessage[];
}

export interface WorkspaceObject {
  id: string;
  project_name: string;
  session_id?: string | null;
  source_message_id?: string | null;
  object_type: string;
  created_by: string;
  title: string;
  content: string;
  metadata_json: Record<string, unknown>;
  created_at: string;
  updated_at: string;
}

export interface WorkspaceEdge {
  id: string;
  project_name: string;
  source_object_id: string;
  target_object_id: string;
  relation_type: string;
  edge_family: 'semantic' | 'context' | 'execution' | 'provenance';
  created_by: string;
  metadata_json: Record<string, unknown>;
  created_at: string;
}

export interface WorkspaceLayout {
  project_name: string;
  layout: Record<string, any>;
  revision: number;
  updated_at?: string | null;
}

export interface WorkspaceGraph {
  project_name: string;
  objects: WorkspaceObject[];
  edges: WorkspaceEdge[];
  layout: WorkspaceLayout;
}

export interface ChatResponse {
  run_id: string;
  session_id: string;
  status: 'completed' | 'waiting_for_approval' | 'failed' | 'cancelled';
  response?: string;
  approval_id?: string;
  user_message_id?: string;
  assistant_message_id?: string;
  tool_results: any[];
}

export interface ApprovalDetail {
  id: string;
  run_id: string;
  session_id: string;
  tool_call_id?: string;
  tool_name: string;
  tool_input: Record<string, any>;
  risk_level: string;
  status: string;
  decision_notes?: string;
  created_at: string;
  decided_at?: string;
}

export interface ApprovalDecisionResponse {
  approval_id: string;
  status: string;
  run_id: string;
  execution_status: string;
  final_response?: string;
}

export interface RunEvent {
  id: string;
  event_type: string;
  payload: Record<string, any>;
  created_at: string;
}

export interface RunDetail {
  id: string;
  session_id: string;
  status: string;
  user_message: string;
  final_response?: string;
  error_message?: string;
  created_at: string;
  updated_at: string;
  events: RunEvent[];
}

export type RoutingPrivacy = 'public' | 'internal' | 'confidential' | 'local_only';
export type RoutingFallback = 'none' | 'same_provider_only' | 'local_only' | 'cloud_allowed' | 'ask_before_cloud';
export type ReasoningEffort = 'instant' | 'low' | 'medium' | 'high' | 'max';
export type WinningScope = 'message' | 'session' | 'project' | 'default' | 'system' | 'draft';
export interface RoutingReasoningConfig {
  policy: 'fixed' | 'adaptive';
  effort: ReasoningEffort;
  min_effort?: ReasoningEffort | null;
  max_effort?: ReasoningEffort | null;
}
export interface RoutingRoute {
  model_override?: string | null;
  provider_override?: string | null;
  reasoning: RoutingReasoningConfig;
  privacy_policy?: RoutingPrivacy | null;
  fallback_policy?: RoutingFallback | null;
}
export interface RoutingProfile {
  id?: string | null;
  name: string;
  version: number;
  is_active: boolean;
  is_default: boolean;
  global_privacy_policy: RoutingPrivacy;
  global_fallback_policy: RoutingFallback;
  cost_preference: 'low' | 'normal';
  latency_preference: 'low' | 'normal';
  routes: Record<string, RoutingRoute>;
}
export interface EffectiveRouting {
  profile: RoutingProfile;
  winning_scope: WinningScope;
  session_id?: string | null;
  project_name?: string | null;
}
export interface RoutingDecision {
  provider: string;
  model: string;
  reason: string;
  reasoning_effort?: string | null;
  profile_id?: string | null;
  profile_name: string;
  profile_version: number;
  winning_scope: WinningScope;
  privacy: RoutingPrivacy;
  fallback: RoutingFallback;
  role: string;
  task_route?: string | null;
  warnings: string[];
}
export interface RoutingProfileValidation {
  valid: boolean;
  profile_id: string;
  errors: string[];
}
export interface RunRoutingDecision {
  run_id: string;
  parent_run_id?: string | null;
  snapshot: Record<string, any>;
  model_selection?: Record<string, any> | null;
  reasoning_selection?: Record<string, any> | null;
  fallback_events: Array<{ event_type: string; payload: Record<string, any> }>;
}

export interface MemoryItem {
  id: string;
  session_id?: string;
  memory_type: string;
  project_name?: string;
  key: string;
  content: string;
  confidence: number;
  metadata_json?: Record<string, any>;
  created_at: string;
}

export interface ResearchInspectorData {
  run_id: string;
  child_run_id?: string;
  goal?: {
    goal_id?: string;
    user_query?: string;
    project_name?: string;
  };
  queries: Array<{
    query_id?: string;
    query_text: string;
    search_type?: string;
    iteration?: number;
    results_count?: number;
  }>;
  sources: Array<{
    source_id?: string;
    canonical_id: string;
    title: string;
    authors?: string[];
    year?: number;
    status?: string;
    metadata?: Record<string, any>;
  }>;
  inspected_source_ids: string[];
  evidence: Array<{
    evidence_id: string;
    source_id?: string;
    source_title?: string;
    source_locator?: string;
    extracted_text: string;
    confidence?: number;
  }>;
  claims: Array<{
    claim_id: string;
    claim_text: string;
    claim_type: string;
    evidence_ids?: string[];
  }>;
  status: string;
}
