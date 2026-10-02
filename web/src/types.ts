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
  | 'file'
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
  workspaceObjectType?: string;
  workspaceCreatedBy?: string;
  workspaceMetadata?: Record<string, unknown>;
  layer: LayerKey;
  from?: string;
  to?: string;
  bridgeOptions?: {
    conclusions: boolean;
    observations: boolean;
    failed: boolean;
    artifacts: boolean;
    constraints: boolean;
    decisions: boolean;
  };
  bridgeSections?: {
    conclusions: string;
    observations: string;
    failed: string;
    artifacts: string;
    constraints: string;
    decisions: string;
  };
  bridgeNote?: string;
  mergeItems?: string[];
  execution?: ExecutionStep[];
  onCycleDensity?: (id: string) => void;
  onBranch?: (id: string) => void;
  onChangeBody?: (id: string, body: string) => void;
  onSetPrivacyPolicy?: (id: string, policy: RoutingPrivacy | null) => void;
  onBridgeApply?: (id: string) => void;
  onBridgeOption?: (id: string, key: 'conclusions' | 'observations' | 'failed' | 'artifacts' | 'constraints' | 'decisions', value: boolean) => void;
  onBridgeSection?: (id: string, key: 'conclusions' | 'observations' | 'failed' | 'artifacts' | 'constraints' | 'decisions', value: string) => void;
  onContinueMerge?: (id: string) => void;
  onUseWorkspaceContext?: (id: string) => void;
}

export type AuraFlowNode = Node<AuraNodeData>;
export type AuraFlowEdge = Edge<{
  edgeKind?: 'reply' | 'context' | 'semantic' | 'execution';
  workspaceCreatedBy?: string;
  relationType?: string;
  edgeFamily?: WorkspaceEdge['edge_family'];
  contextOrigin?: 'selected' | 'linked';
  workspaceMetadata?: Record<string, unknown>;
  onDelete?: (id: string) => void;
}>;

export interface AIContextItem {
  id: string;
  kind: 'turn' | 'note' | 'paper' | 'claim' | 'code' | 'file';
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
  onBridgeOption?: (id: string, key: 'conclusions' | 'observations' | 'failed' | 'artifacts' | 'constraints' | 'decisions', value: boolean) => void;
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
  messages: SessionMessage[];
}

export interface SessionMessage extends ChatMessage {
  run_id?: string;
  context_manifest?: CompiledContextManifest;
  routing_provenance?: {
    provider?: string;
    model?: string;
    role?: string;
    reasoning_effort?: string;
  };
}

export interface WorkspaceObject {
  id: string;
  project_name: string | null;
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

export interface WorkspaceExecutionEvent {
  id: string;
  event_type: string;
  created_at: string;
  agent_role?: string | null;
  specialist?: string | null;
  provider?: string | null;
  model?: string | null;
  tool_name?: string | null;
  tool_call_id?: string | null;
  child_run_id?: string | null;
  status?: string | null;
  success?: boolean | null;
  error_category?: string | null;
  risk_level?: string | null;
  step?: number | null;
  task_type?: string | null;
  profile_id?: string | null;
  profile_version?: number | null;
  winning_scope?: string | null;
  privacy?: string | null;
  fallback_policy?: string | null;
  selection_reason?: string | null;
  reasoning_policy?: string | null;
  reasoning_bounds?: { min?: string | null; max?: string | null } | null;
  selected_effort?: string | null;
  primary_provider?: string | null;
  selected_provider?: string | null;
  candidate_model?: string | null;
  privacy_boundary?: string | null;
  error_type?: string | null;
  proposed_provider?: string | null;
  proposed_model?: string | null;
  trigger_event_id?: string | null;
  automation_id?: string | null;
  automation_name?: string | null;
  context_objects?: Array<{
    object_id: string;
    object_type: string;
    selected_by_user: boolean;
    source_object_ids: string[];
    selected_sections?: Record<string, boolean | null> | null;
  }>;
  context_estimated_tokens?: number | null;
  context_privacy_requirement?: string | null;
}

export interface WorkspaceExecutionTrace {
  run_id: string;
  parent_run_id?: string | null;
  session_id: string;
  user_object_id?: string | null;
  response_object_id?: string | null;
  events: WorkspaceExecutionEvent[];
}

export interface CapabilityProviderMetadata {
  provider_id: string;
  name: string;
  version?: string | null;
  health: 'unknown' | 'healthy' | 'degraded' | 'unavailable' | 'disabled';
  health_checked_at?: string | null;
  enabled: boolean;
  capabilities: string[];
  capability_tools: Record<string, string[]>;
  declared_capability_tools: Record<string, string[]>;
  privacy_boundary: 'unknown' | 'local' | 'cloud' | 'mixed';
  network_requirement: 'unknown' | 'none' | 'local' | 'internet';
  data_touched?: string[] | null;
  permissions?: Array<'read' | 'write' | 'execute'> | null;
  approval_requirement: 'unknown' | 'per_tool_policy' | 'always';
}

export interface CapabilityProvidersResponse {
  providers: CapabilityProviderMetadata[];
}

export interface WorkspaceExecutionHistory {
  execution_traces: WorkspaceExecutionTrace[];
  execution_history_truncated: boolean;
  execution_next_cursor?: string | null;
}

export interface WorkspaceGraph {
  project_name: string;
  objects: WorkspaceObject[];
  edges: WorkspaceEdge[];
  layout: WorkspaceLayout;
  execution_traces?: WorkspaceExecutionTrace[];
  execution_history_truncated?: boolean;
  execution_next_cursor?: string | null;
}

export interface ChatResponse {
  run_id: string;
  session_id: string;
  status: 'completed' | 'waiting_for_approval' | 'waiting_for_routing_confirmation' | 'failed' | 'cancelled';
  response?: string;
  approval_id?: string;
  routing_confirmation_id?: string;
  proposed_provider?: string;
  proposed_model?: string;
  user_message_id?: string;
  assistant_message_id?: string;
  tool_results: any[];
}

export interface RoutingConfirmationDetail {
  id: string;
  root_run_id: string;
  execution_run_id: string;
  session_id: string;
  proposed_provider: string;
  proposed_model: string;
  status: 'pending' | 'approved' | 'rejected';
  decision_notes?: string | null;
  created_at: string;
  decided_at?: string | null;
}

export interface RoutingConfirmationDecisionResponse {
  confirmation_id: string;
  status: 'approved' | 'rejected';
  run_id: string;
  execution_status: string;
  final_response?: string | null;
  next_routing_confirmation_id?: string | null;
  approval_id?: string | null;
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

export interface WorkspaceNoteRecord {
  id: string;
  title: string;
  body: string;
  tags: string[];
  project_names: string[];
  pinned: boolean;
  privacy_policy?: string | null;
  created_at: string;
  updated_at: string;
}

export interface StudySessionRecord {
  id: string;
  track_id: string;
  track_title: string;
  material_id?: string | null;
  material_project_name?: string | null;
  status: 'in_progress' | 'completed';
  reflection: string;
  started_at: string;
  completed_at?: string | null;
}

export interface StudyCardRecord {
  id: string;
  session_id: string;
  question: string;
  answer: string;
  created_at: string;
  updated_at: string;
}

export interface WorkspaceLibraryReferenceRecord {
  id: string;
  name: string;
  kind: 'HTML' | 'PDF' | 'MD' | 'CSV' | 'TXT' | 'JSON' | 'IMAGE' | 'FILE';
  collection: 'Study' | 'Books' | 'Research' | 'Reference';
  detail: string;
  tags: string[];
  project_names: string[];
  size?: number | null;
  mime_type?: string | null;
  created_at: string;
  updated_at: string;
}

export interface WorkspaceProjectRecord {
  id: string;
  name: string;
  subtitle: string;
  created_at: string;
  updated_at: string;
}

export interface WorkspaceSearchResult {
  object_id: string;
  object_type: string;
  title: string;
  excerpt: string;
  project_name: string | null;
  created_by: string;
  verification_status?: string | null;
  updated_at: string;
  source?: 'workspace' | 'connected-folder';
  connection_id?: string;
  connection_name?: string;
  relative_path?: string;
  size?: number;
  mime_type?: string;
}

export interface AutomationRecordResponse {
  id: string;
  name: string;
  description: string;
  instruction: string;
  enabled: boolean;
  scope: 'global' | 'project';
  project_name: string | null;
  interval_seconds: number;
  last_run_at: string | null;
  next_run_at: string;
  created_at: string;
  updated_at: string;
  latest_execution: AutomationExecutionRecord | null;
}

export interface AutomationExecutionRecord {
  event_id: string;
  run_id: string;
  queued_at: string;
  status: string;
  retry_count: number;
}

export interface AutomationRunResponse {
  event_id: string;
  status: 'queued';
}

export interface CompiledContextObject {
  object_id: string;
  object_type: string;
  selected_by_user?: boolean;
  source_object_ids?: string[];
  selected_sections?: Record<string, boolean | null> | null;
}

export interface CompiledContextManifest {
  project_name?: string;
  objects?: CompiledContextObject[];
  estimated_tokens?: number;
  character_count?: number;
  privacy_requirement?: string | null;
  privacy_sources?: Array<{ object_id: string; privacy_policy: RoutingPrivacy }>;
  required_capabilities?: string[];
  required_tool_capabilities?: string[];
  resolved_tool_names?: string[];
  capability_requirements?: Record<string, boolean>;
}

export interface WorkspaceContextPreview extends CompiledContextManifest {
  project_name: string;
  prompt_text: string;
  privacy_requirement?: RoutingPrivacy | null;
  privacy_sources?: Array<{ object_id: string; privacy_policy: RoutingPrivacy }>;
  required_capabilities?: string[];
  available_capabilities?: string[];
  missing_capabilities?: string[];
  requires_tools?: boolean;
  requires_vision?: boolean;
  requires_structured_output?: boolean;
  requires_long_context?: boolean;
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
  context_manifest?: CompiledContextManifest | null;
  memory_privacy_sources?: Array<{ memory_id: string; privacy_policy: RoutingPrivacy }>;
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
