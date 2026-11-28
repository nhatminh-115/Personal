import {
  ArrowUp,
  Bot,
  ChevronDown,
  ChevronRight,
  GitBranch,
  Layers3,
  Paperclip,
  Sparkles,
  UserRound,
} from 'lucide-react';
import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import type {
  AIContextItem,
  ApprovalDetail,
  ChatMessage,
  ExecutionStep,
  ModelCatalog,
  ReasoningSelection,
} from '../../types';
import { ApprovalCard } from '../approvals/ApprovalCard';
import { AIContextPanel } from './AIContextPanel';
import { AIRunStrip } from './AIRunStrip';
import { ExecutionSidecar } from './ExecutionSidecar';
import { ResponseProvenance } from './ResponseProvenance';
import { CustomSelect } from '../ui/CustomSelect';
import { friendlyModelName } from '../../lib/modelName';

export interface ChatPaneProps {
  compact?: boolean;
  projectName: string;
  threadTitle: string;
  messages: ChatMessage[];
  messagesNextCursor?: string | null;
  loadingOlderMessages?: boolean;
  onLoadOlderMessages?: () => Promise<void>;
  onMessagesChange: (updater: (messages: ChatMessage[]) => ChatMessage[]) => void;
  contextItems?: AIContextItem[];
  /** Selected live context stays usable before opening the Context object catalog. */
  initialContextObjectIds?: string[];
  initialContextFileContentIds?: string[];
  contextIsLive?: boolean;
  contextHasMore?: boolean;
  loadingOlderContext?: boolean;
  contextLoadError?: string | null;
  contextLoading?: boolean;
  onLoadOlderContext?: () => Promise<void>;
  onRetryContext?: () => void;
  focusedMessageId?: string | null;
  onMessageFocus?: (message: ChatMessage) => void;
  onBranchFromMessage?: (message: ChatMessage) => void;
  onContextObjectFocus?: (nodeId: string) => void;
  onAttachRequest?: () => void;
  onSendMessage?: (text: string, contextObjectIds?: string[], taskType?: 'research' | 'coding' | 'writing', contextFileContentIds?: string[], modelOverride?: string | null, reasoningOverride?: ReasoningSelection | null) => Promise<void>;
  onCancelRun?: () => Promise<boolean>;
  /** Called when user clicks "Start live chat" from a demo thread. */
  onStartLiveChat?: (text: string, contextObjectIds?: string[], taskType?: 'research' | 'coding' | 'writing', contextFileContentIds?: string[], modelOverride?: string | null, reasoningOverride?: ReasoningSelection | null) => Promise<void>;
  modelCatalog?: ModelCatalog;
  selectedModel?: string | null;
  selectedReasoning?: ReasoningSelection | null;
  onSelectModel?: (model: string | null) => void;
  onSelectReasoning?: (reasoning: ReasoningSelection) => void;
  onConnectProvider?: () => void;
  onContextObjectIdsChange?: (objectIds: string[]) => void;
  onContextFileContentIdsChange?: (objectIds: string[]) => void;
  onContextPanelOpenChange?: (open: boolean) => void;
  currentApproval?: ApprovalDetail | null;
  runInProgress?: boolean;
  runCancellationRequested?: boolean;
  onApprovalDecision?: (
    decision: 'approved' | 'rejected' | 'edited',
    notes?: string,
    editedInput?: Record<string, any>
  ) => Promise<void>;
  isLiveThread?: boolean;
}

interface OpenExecution {
  title: string;
  steps: ExecutionStep[];
}

type RunPhase = 'preparing' | 'context' | 'synthesizing';

function mockExecution(): ExecutionStep[] {
  return [
    { id: 'model', label: 'Apply conversation choices', detail: 'Selected model and reasoning', status: 'done' },
    { id: 'context', label: 'Assemble context manifest', detail: 'Thread + linked project objects', status: 'done' },
    { id: 'retrieve', label: 'Retrieve supporting evidence', detail: 'Workspace-local evidence', status: 'done' },
    { id: 'synthesize', label: 'Synthesize response', detail: 'Operational trace only', status: 'done' },
  ];
}

function mockAnswer(prompt: string, includedCount: number) {
  return `Đây là phản hồi minh họa trong demo thread. ${includedCount} object context đang được giữ lại. Prompt hiện tại là “${prompt}”.`;
}

export function ChatPane({
  compact = false,
  projectName,
  threadTitle,
  messages,
  messagesNextCursor,
  loadingOlderMessages = false,
  onLoadOlderMessages,
  onMessagesChange,
  contextItems: suppliedContext,
  initialContextObjectIds,
  initialContextFileContentIds,
  contextIsLive = false,
  contextHasMore = false,
  loadingOlderContext = false,
  contextLoadError = null,
  contextLoading = false,
  onLoadOlderContext,
  onRetryContext,
  focusedMessageId,
  onMessageFocus,
  onBranchFromMessage,
  onContextObjectFocus,
  onAttachRequest,
  onSendMessage,
  onCancelRun,
  onStartLiveChat,
  onContextObjectIdsChange,
  onContextFileContentIdsChange,
  onContextPanelOpenChange,
  currentApproval,
  runInProgress = false,
  runCancellationRequested = false,
  onApprovalDecision,
  isLiveThread = true,
  modelCatalog = { providers: [] },
  selectedModel = null,
  selectedReasoning = 'auto',
  onSelectModel,
  onSelectReasoning,
  onConnectProvider,
}: ChatPaneProps) {
  const [openExecution, setOpenExecution] = useState<OpenExecution | null>(null);
  const [draft, setDraft] = useState('');
  const [composerExpanded, setComposerExpanded] = useState(false);
  const [contextItems, setContextItems] = useState<AIContextItem[]>(() => (suppliedContext ?? []).map((item) => ({ ...item })));
  const [contextOpen, setContextOpen] = useState(false);
  const [runPhase, setRunPhase] = useState<RunPhase | null>(null);
  const [stoppingRun, setStoppingRun] = useState(false);
  const timersRef = useRef<number[]>([]);
  const messageRefs = useRef<Record<string, HTMLDivElement | null>>({});

  useEffect(() => {
    setContextItems((suppliedContext ?? []).map((item) => ({ ...item })));
  }, [suppliedContext]);

  useEffect(() => {
    if (!runPhase && !runInProgress && stoppingRun) setStoppingRun(false);
  }, [runInProgress, runPhase, stoppingRun]);

  useEffect(() => {
    setContextOpen(false);
    onContextPanelOpenChange?.(false);
  }, [threadTitle, onContextPanelOpenChange]);

  const includedContext = useMemo(() => contextItems.filter((item) => item.included), [contextItems]);
  const contextTokens = useMemo(() => includedContext.reduce((sum, item) => sum + item.tokens, 0), [includedContext]);
  const initialSelectedContextIds = [...new Set([
    ...(initialContextObjectIds ?? []),
    ...(initialContextFileContentIds ?? []),
  ])];
  const selectedContextCount = isLiveThread && contextItems.length === 0 && initialContextObjectIds !== undefined
    ? initialSelectedContextIds.length
    : includedContext.length;
  const contextEstimateAvailable = selectedContextCount === includedContext.length;
  const modelProviders = Array.isArray(modelCatalog?.providers) ? modelCatalog.providers : [];
  const availableModels = modelProviders.filter((provider) => provider.available && Array.isArray(provider.models)).flatMap((provider) => provider.models.map((model) => ({
    value: `${provider.id}:${model.id}`,
    label: `${friendlyModelName(model.label || model.id)} · ${provider.label}`,
    description: `${provider.kind === 'local' ? 'On this device' : 'Cloud model'}${model.context_window ? ` · ${Math.round(model.context_window / 1000)}k context` : ''}`,
    disabled: false,
  })));
  const [selectedProviderId, selectedModelId] = selectedModel?.split(':') ?? [];
  const selectedModelInfo = selectedProviderId && selectedModelId
    ? modelProviders.find((provider) => provider.id === selectedProviderId)?.models?.find((model) => model.id === selectedModelId)
    : undefined;
  const modelOptions = [
    { value: '', label: 'Automatic', description: 'Choose automatically for this conversation' },
    ...availableModels,
    ...(selectedModel && !availableModels.some((option) => option.value === selectedModel)
      ? [{ value: selectedModel, label: `${friendlyModelName(selectedModelId ?? 'Saved model')} · unavailable`, description: 'This saved model is not currently available', disabled: true }]
      : []),
  ];
  const reasoningUnavailable = selectedModelInfo?.reasoning_support === 'fixed_by_model'
    || selectedModelInfo?.reasoning_support === 'unsupported'
    || !selectedModelInfo
    || selectedModelInfo.reasoning_support === 'unknown';
  const reasoningCeiling = selectedModelInfo?.reasoning_support;
  const reasoningEfforts = ['low', 'medium', 'high', 'max'] as const;
  const supportedReasoning = reasoningCeiling && reasoningEfforts.includes(reasoningCeiling as typeof reasoningEfforts[number])
    ? reasoningEfforts.slice(0, reasoningEfforts.indexOf(reasoningCeiling as typeof reasoningEfforts[number]) + 1)
    : [];
  const reasoningOptions = [
    { value: 'auto', label: 'Auto', description: selectedModel ? 'Use the selected model’s default reasoning' : 'Use the default reasoning setting' },
    ...supportedReasoning.map((value) => ({
      value,
      label: value[0].toUpperCase() + value.slice(1),
      description: value === 'max' ? 'Use maximum reasoning effort' : `Use ${value} reasoning effort`,
    })),
  ];

  const clearRunTimers = useCallback(() => {
    timersRef.current.forEach((timer) => window.clearTimeout(timer));
    timersRef.current = [];
  }, []);

  const stopRun = useCallback(() => {
    if (isLiveThread) {
      if (!onCancelRun || stoppingRun) return;
      setStoppingRun(true);
      void onCancelRun().then(() => setStoppingRun(false)).catch(() => setStoppingRun(false));
      return;
    }
    clearRunTimers();
    setRunPhase(null);
  }, [clearRunTimers, isLiveThread, onCancelRun, stoppingRun]);

  useEffect(() => () => clearRunTimers(), [clearRunTimers]);

  useEffect(() => {
    if (!focusedMessageId) return;
    messageRefs.current[focusedMessageId]?.scrollIntoView({ behavior: 'smooth', block: 'center' });
  }, [focusedMessageId, messages.length]);

  useEffect(() => {
    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key !== 'Escape') return;
      setOpenExecution(null);
      setContextOpen(false);
    };
    window.addEventListener('keydown', onKeyDown);
    return () => window.removeEventListener('keydown', onKeyDown);
  }, []);

  const submit = useCallback(async () => {
    const prompt = draft.trim();
    if (!prompt || runPhase || runInProgress) return;

    if (onSendMessage && isLiveThread) {
      setDraft('');
      setComposerExpanded(false);
      setContextOpen(false);
      onContextPanelOpenChange?.(false);
      setRunPhase('preparing');
      try {
        await onSendMessage(
          prompt,
          includedContext.map((item) => item.nodeId).filter((id): id is string => Boolean(id)),
          undefined,
          includedContext.filter((item) => item.fileContentIncluded).map((item) => item.nodeId).filter((id): id is string => Boolean(id)),
          selectedModel,
          selectedReasoning,
        );
      } finally {
        setRunPhase(null);
        setStoppingRun(false);
      }
      return;
    }

    // Demo threads (isLiveThread=false) fall through to mock path.
    // The "Start live chat" CTA button is the ONLY way to invoke onStartLiveChat.
    const nonce = Date.now();
    const userMessage: ChatMessage = {
      id: `runtime-user-${nonce}`,
      role: 'user',
      branch: 'Root',
      nodeId: `runtime-user-node-${nonce}`,
      content: prompt,
      timestamp: 'now',
      status: 'Sent',
    };

    onMessagesChange((current) => [...current, userMessage]);
    setDraft('');
    setComposerExpanded(false);
    setContextOpen(false);
    onContextPanelOpenChange?.(false);
    setRunPhase('preparing');

    timersRef.current = [
      window.setTimeout(() => setRunPhase('context'), 420),
      window.setTimeout(() => setRunPhase('synthesizing'), 900),
      window.setTimeout(() => {
        const provenance = includedContext.slice(0, 4).map((item) => ({
          id: `prov-${item.id}-${nonce}`,
          label: item.title,
          detail: item.detail,
          kind: item.kind === 'code' ? ('artifact' as const) : ('context' as const),
          nodeId: item.nodeId,
        }));
        const assistant: ChatMessage = {
          id: `runtime-aura-${nonce}`,
          role: 'assistant',
          branch: 'Root',
          nodeId: `runtime-aura-node-${nonce}`,
          content: mockAnswer(prompt, includedContext.length),
          executionLabel: 'Demo response · 4 steps',
          execution: mockExecution(),
          timestamp: 'now',
          specialist: 'Demo assistant',
          status: `${includedContext.length} context objects retained`,
          contextTokens,
          provenance,
        };
        onMessagesChange((current) => [...current, assistant]);
        setRunPhase(null);
        timersRef.current = [];
      }, 1550),
    ];
  }, [contextTokens, draft, includedContext, isLiveThread, onContextPanelOpenChange, onMessagesChange, onSendMessage, runInProgress, runPhase, selectedModel, selectedReasoning]);


  return (
    <div className={`chat-pane ${compact ? 'chat-pane--compact' : ''}`}>
      <div className="chat-thread">
        <div className="chat-thread__intro">
          <div className="chat-thread__intro-icon"><Sparkles size={16} /></div>
          <div>
            <span>{projectName}</span>
            <h2>{threadTitle}</h2>
          </div>
        </div>

        <div className="branch-divider"><span>Conversation thread</span></div>

        {isLiveThread && messagesNextCursor ? (
          <button
            className="load-older-messages"
            type="button"
            disabled={loadingOlderMessages}
            onClick={() => { void onLoadOlderMessages?.(); }}
          >
            {loadingOlderMessages ? 'Loading older messages…' : 'Load older messages'}
          </button>
        ) : null}

        {!isLiveThread ? (
          <div className="chat-demo-banner">
            <Sparkles size={13} />
            <span>This is a <strong>demo thread</strong>. Replies shown here are illustrative and were not sent to the backend.</span>
            {onStartLiveChat ? (
              <button
                className="demo-start-live-button"
                type="button"
                onClick={() => { void onStartLiveChat(draft.trim(), [], undefined, undefined, selectedModel, selectedReasoning); }}
              >
                Start live chat
              </button>
            ) : null}
          </div>
        ) : null}

        {messages.length === 0 ? (
          <div className="chat-empty-thread">
            <Sparkles size={20} />
            <strong>New project chat</strong>
            <span>This thread starts clean. Project files, notes and explicit context can still be attached without inheriting another chat.</span>
          </div>
        ) : null}

        {messages.map((message) => {
          const isUser = message.role === 'user';
          return (
            <div
              ref={(element) => { if (message.id) messageRefs.current[message.id] = element; }}
              key={message.id || `msg-${message.content.slice(0, 10)}`}
              className={`chat-message chat-message--${message.role} ${focusedMessageId === message.id ? 'is-focused' : ''}`}
              onClick={() => onMessageFocus?.(message)}
            >
              <div className="chat-message__meta">
                <span className="chat-message__identity">
                  <span className="chat-message__avatar">{isUser ? <UserRound size={12} /> : <Bot size={12} />}</span>
                  <span>
                    <strong>{isUser ? 'You' : 'Kuractus'}</strong>
                    {!isUser && message.specialist ? <small>{message.specialist}</small> : null}
                  </span>
                </span>
                <span className="chat-message__meta-right">
                  {message.branch && message.branch !== 'Root' ? <small>Branch {message.branch}</small> : null}
                  {message.timestamp ? <time>{message.timestamp}</time> : null}
                </span>
              </div>

              <div className="chat-message__bubble glow-surface"><p>{message.content}</p></div>

              {!isUser ? (
                <ResponseProvenance
                  route={message.routeLabel ?? (message.specialist ? `${message.specialist} · Adaptive` : undefined)}
                  reasoning={message.reasoningLabel}
                  contextTokens={message.contextTokens}
                  items={message.provenance}
                  onFocusObject={onContextObjectFocus}
                />
              ) : null}

              <div className="chat-message__status-row">
                {message.status ? <span>{message.status}</span> : null}
                {message.contextObjectIds?.length ? <span>{message.contextObjectIds.length} selected context object{message.contextObjectIds.length === 1 ? '' : 's'}</span> : null}
                {message.role === 'assistant' ? (
                  <div className="chat-message__footer">
                    {message.executionLabel && message.execution ? (
                      <button
                        className="execution-chip"
                        type="button"
                        onClick={(event) => {
                          event.stopPropagation();
                          setOpenExecution({ title: message.executionLabel ?? 'Execution', steps: message.execution ?? [] });
                        }}
                      >
                        {message.execution?.some((step) => step.status === 'running') ? <span className="running-dot" /> : <Sparkles size={12} />}
                        <span>{message.executionLabel}</span>
                        <ChevronRight size={12} />
                      </button>
                    ) : null}
                    <button
                      className="message-action"
                      type="button"
                      onClick={(event) => {
                        event.stopPropagation();
                        onBranchFromMessage?.(message);
                      }}
                    >
                      <GitBranch size={12} /> Branch from here
                    </button>
                  </div>
                ) : null}
              </div>
            </div>
          );
        })}

        {currentApproval ? (
          <ApprovalCard
            approval={currentApproval}
            onDecision={onApprovalDecision || (async () => {})}
          />
        ) : null}
      </div>

      <div className="chat-composer-wrap">
        {runPhase || runInProgress ? <AIRunStrip phase={runPhase ?? 'preparing'} specialist="Preparing response" onStop={isLiveThread ? onCancelRun ? stopRun : undefined : stopRun} stopping={stoppingRun} stopRequested={runCancellationRequested} /> : null}
        <div
          className={`chat-composer chat-composer--ai ${composerExpanded ? 'is-expanded' : 'is-collapsed'}`}
          onMouseDownCapture={() => setComposerExpanded(true)}
          onFocusCapture={() => setComposerExpanded(true)}
          onBlurCapture={(event) => {
            if (event.currentTarget.contains(event.relatedTarget as Node | null)) return;
            if (!draft.trim() && !contextOpen) setComposerExpanded(false);
          }}
        >
          {contextOpen ? (
            <AIContextPanel
              items={contextItems}
              contextIsLive={contextIsLive}
              hasMore={contextHasMore}
              loading={contextLoading}
              loadingOlder={loadingOlderContext}
              loadError={contextLoadError}
              onLoadOlder={onLoadOlderContext}
              onRetry={onRetryContext}
              onToggleItem={(id) => {
                const selected = contextItems.find((item) => item.id === id);
                const willInclude = selected ? !selected.included : false;
                const next = contextItems.map((item) => item.id === id
                  ? { ...item, included: willInclude, fileContentIncluded: willInclude ? item.fileContentIncluded : false }
                  : item);
                setContextItems(next);
                if (contextIsLive) {
                  onContextObjectIdsChange?.(next.filter((item) => item.included).map((item) => item.nodeId).filter((nodeId): nodeId is string => Boolean(nodeId)));
                  onContextFileContentIdsChange?.(next.filter((item) => item.fileContentIncluded).map((item) => item.nodeId).filter((nodeId): nodeId is string => Boolean(nodeId)));
                }
              }}
              onToggleFileContent={(id, include) => {
                const next = contextItems.map((item) => item.nodeId === id
                  ? { ...item, included: include || item.included, fileContentIncluded: include }
                  : item);
                setContextItems(next);
                if (contextIsLive) {
                  onContextObjectIdsChange?.(next.filter((item) => item.included).map((item) => item.nodeId).filter((nodeId): nodeId is string => Boolean(nodeId)));
                  onContextFileContentIdsChange?.(next.filter((item) => item.fileContentIncluded).map((item) => item.nodeId).filter((nodeId): nodeId is string => Boolean(nodeId)));
                }
              }}
              onFocusItem={(nodeId) => {
                setContextOpen(false);
                onContextObjectFocus?.(nodeId);
              }}
              onClose={() => setContextOpen(false)}
            />
          ) : null}

          <textarea
            value={draft}
            onChange={(event) => { setDraft(event.target.value); setComposerExpanded(true); }}
            onKeyDown={(event) => {
              if (event.key === 'Enter' && !event.shiftKey) {
                event.preventDefault();
                submit();
              }
            }}
            placeholder="Ask Kuractus in this chat…"
            rows={composerExpanded ? compact ? 2 : 3 : 1}
          />

          <div className="chat-composer__footer">
            <div className="composer-tools">
              <button className="icon-button" type="button" aria-label="Attach project object" title="Attach project file or object" onClick={onAttachRequest}><Paperclip size={16} /></button>
              <button className={`composer-context ${contextOpen ? 'is-active' : ''}`} type="button" onClick={() => {
                const next = !contextOpen;
                setContextOpen(next);
                onContextPanelOpenChange?.(next);
              }}>
                <span className="composer-context__icon"><Layers3 size={13} /></span>
                <span className="composer-context__copy">
                  <strong>Context</strong>
                  <small>{contextIsLive ? 'Project objects' : 'Demo examples'}</small>
                </span>
                <span className="composer-context__stats">{contextEstimateAvailable
                  ? `${selectedContextCount} objects · ~${(contextTokens / 1000).toFixed(1)}k estimated tokens`
                  : `${selectedContextCount} selected · open Context to inspect`}</span>
                <ChevronDown className="composer-context__chevron" size={11} />
              </button>
            </div>
            <div className="composer-actions">
              {!availableModels.length && onConnectProvider ? <button className="composer-connect-provider" type="button" onClick={onConnectProvider}>Connect provider</button> : null}
              <div className="composer-ai-controls">
                <CustomSelect
                  className="composer-model-select"
                  value={selectedModel ?? ''}
                  options={modelOptions}
                  onChange={(value) => onSelectModel?.(value || null)}
                  ariaLabel="Conversation model"
                  label="Model"
                  title="Choose a model for this conversation"
                />
                <CustomSelect
                  className="composer-reasoning-select"
                  value={selectedReasoning ?? ''}
                  options={reasoningOptions}
                  onChange={(value) => onSelectReasoning?.(value as ReasoningSelection)}
                  ariaLabel="Conversation reasoning"
                  label="Reasoning"
                  title={reasoningUnavailable ? 'Choose a model with reasoning controls to set an effort.' : 'Choose reasoning effort for this conversation'}
                />
              </div>
              <button className="send-button" type="button" onClick={submit} aria-label="Send" disabled={!draft.trim() || Boolean(runPhase || runInProgress)}>
                <ArrowUp size={17} />
              </button>
            </div>
          </div>
        </div>
      </div>

      {openExecution ? <ExecutionSidecar title={openExecution.title} steps={openExecution.steps} onClose={() => setOpenExecution(null)} /> : null}
    </div>
  );
}
