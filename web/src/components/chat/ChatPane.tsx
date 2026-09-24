import {
  ArrowUp,
  Bot,
  ChevronDown,
  ChevronRight,
  Code2,
  GitBranch,
  Layers3,
  Paperclip,
  Search,
  Sparkles,
  UserRound,
  WandSparkles,
} from 'lucide-react';
import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import type {
  AIContextItem,
  ApprovalDetail,
  AuraWorkMode,
  ChatMessage,
  ContextScope,
  ExecutionStep,
} from '../../types';
import { ApprovalCard } from '../approvals/ApprovalCard';
import { AIContextPanel } from './AIContextPanel';
import { AIRunStrip } from './AIRunStrip';
import { ExecutionSidecar } from './ExecutionSidecar';
import { ResponseProvenance } from './ResponseProvenance';

export interface ChatPaneProps {
  compact?: boolean;
  projectName: string;
  threadTitle: string;
  messages: ChatMessage[];
  onMessagesChange: (updater: (messages: ChatMessage[]) => ChatMessage[]) => void;
  contextItems?: AIContextItem[];
  focusedMessageId?: string | null;
  onMessageFocus?: (message: ChatMessage) => void;
  onBranchFromMessage?: (message: ChatMessage) => void;
  onContextObjectFocus?: (nodeId: string) => void;
  onAttachRequest?: () => void;
  onSendMessage?: (text: string) => Promise<void>;
  /** Called when user clicks "Start live chat" from a demo thread. */
  onStartLiveChat?: (text: string) => Promise<void>;
  currentApproval?: ApprovalDetail | null;
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

type RunPhase = 'routing' | 'context' | 'synthesizing';

const workModes: { id: AuraWorkMode; label: string; icon: typeof Sparkles }[] = [
  { id: 'auto', label: 'Auto', icon: WandSparkles },
  { id: 'research', label: 'Research', icon: Search },
  { id: 'code', label: 'Code', icon: Code2 },
  { id: 'write', label: 'Write', icon: Sparkles },
];

const scopeLabel: Record<ContextScope, string> = {
  branch: 'Current branch',
  project: 'Project',
  selection: 'Selected',
  library: 'Library',
};

const fallbackContext: AIContextItem[] = [
  { id: 'ctx-root', kind: 'turn', title: 'Current thread', detail: 'conversation · ancestry', tokens: 2100, included: true, nodeId: 'root-answer' },
  { id: 'ctx-note', kind: 'note', title: 'Linked project note', detail: 'manual note', tokens: 84, included: true, nodeId: 'note-ttt' },
  { id: 'ctx-file', kind: 'file', title: 'Project files', detail: 'explicitly linked artifacts', tokens: 720, included: false },
];

function routeForMode(mode: AuraWorkMode) {
  if (mode === 'research') return { specialist: 'Research Specialist', reasoning: 'High', label: 'Research · High' };
  if (mode === 'code') return { specialist: 'Coding Specialist', reasoning: 'High', label: 'Coding · High' };
  if (mode === 'write') return { specialist: 'Writing Specialist', reasoning: 'Medium', label: 'Writing · Medium' };
  return { specialist: 'Adaptive Router', reasoning: 'Adaptive', label: 'Auto · Adaptive' };
}

function mockExecution(mode: AuraWorkMode): ExecutionStep[] {
  const route = routeForMode(mode);
  return [
    { id: 'route', label: 'Route request', detail: `${route.specialist} · ${route.reasoning}`, status: 'done' },
    { id: 'context', label: 'Assemble context manifest', detail: 'Thread + linked project objects', status: 'done' },
    { id: 'retrieve', label: mode === 'code' ? 'Inspect code evidence' : 'Retrieve supporting evidence', detail: mode === 'research' ? 'Retained workspace sources' : 'Workspace-local evidence', status: 'done' },
    { id: 'synthesize', label: 'Synthesize response', detail: 'Operational trace only', status: 'done' },
  ];
}

function mockAnswer(mode: AuraWorkMode, prompt: string, includedCount: number) {
  if (mode === 'code') {
    return `Tôi sẽ ưu tiên kiểm chứng bằng artifact thay vì chỉ mô tả. Với ${includedCount} object context hiện tại, tôi sẽ tách implementation evidence khỏi assumption rồi ghi result thành object có thể link lại vào project. Prompt hiện tại là “${prompt}”.`;
  }
  if (mode === 'write') {
    return `Tôi sẽ viết từ đúng context của thread này và giữ claim ở mức có thể truy ngược về note/file/source. ${includedCount} object đang được retain; phần nào không nằm trong manifest sẽ không được giả định là đã có trong context.`;
  }
  if (mode === 'research') {
    return `Tôi sẽ coi đây là câu hỏi literature-boundary. ${includedCount} object đang được dùng làm evidence manifest; kết quả nên được lưu thành note/source object của project để các chat khác có thể reuse thay vì phụ thuộc vào lịch sử của riêng thread này.`;
  }
  return `AURA route prompt này theo context của chat hiện tại nhưng vẫn giữ project artifacts ở dạng explicit manifest. ${includedCount} object đang được retain, nên câu trả lời có thể branch, link hoặc reuse ở chat khác mà không cần biến một conversation thành lịch sử vô hạn.`;
}

export function ChatPane({
  compact = false,
  projectName,
  threadTitle,
  messages,
  onMessagesChange,
  contextItems: suppliedContext,
  focusedMessageId,
  onMessageFocus,
  onBranchFromMessage,
  onContextObjectFocus,
  onAttachRequest,
  onSendMessage,
  onStartLiveChat,
  currentApproval,
  onApprovalDecision,
  isLiveThread = true,
}: ChatPaneProps) {
  const [openExecution, setOpenExecution] = useState<OpenExecution | null>(null);
  const [draft, setDraft] = useState('');
  const [workMode, setWorkMode] = useState<AuraWorkMode>('auto');
  const [scope, setScope] = useState<ContextScope>('branch');
  const [contextItems, setContextItems] = useState<AIContextItem[]>(() => (suppliedContext ?? fallbackContext).map((item) => ({ ...item })));
  const [contextOpen, setContextOpen] = useState(false);
  const [runPhase, setRunPhase] = useState<RunPhase | null>(null);
  const timersRef = useRef<number[]>([]);
  const messageRefs = useRef<Record<string, HTMLDivElement | null>>({});

  useEffect(() => {
    setContextItems((suppliedContext ?? fallbackContext).map((item) => ({ ...item })));
    setContextOpen(false);
  }, [threadTitle, suppliedContext]);

  const includedContext = useMemo(() => contextItems.filter((item) => item.included), [contextItems]);
  const contextTokens = useMemo(() => includedContext.reduce((sum, item) => sum + item.tokens, 0), [includedContext]);
  const activeRoute = routeForMode(workMode);

  const clearRunTimers = useCallback(() => {
    timersRef.current.forEach((timer) => window.clearTimeout(timer));
    timersRef.current = [];
  }, []);

  const stopRun = useCallback(() => {
    clearRunTimers();
    setRunPhase(null);
  }, [clearRunTimers]);

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
    if (!prompt || runPhase) return;

    if (onSendMessage && isLiveThread) {
      setDraft('');
      setContextOpen(false);
      setRunPhase('routing');
      try {
        await onSendMessage(prompt);
      } finally {
        setRunPhase(null);
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
    setContextOpen(false);
    setRunPhase('routing');

    timersRef.current = [
      window.setTimeout(() => setRunPhase('context'), 420),
      window.setTimeout(() => setRunPhase('synthesizing'), 900),
      window.setTimeout(() => {
        const route = routeForMode(workMode);
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
          content: mockAnswer(workMode, prompt, includedContext.length),
          executionLabel: `${route.specialist} · 4 steps`,
          execution: mockExecution(workMode),
          timestamp: 'now',
          specialist: route.specialist,
          status: `${includedContext.length} context objects retained`,
          routeLabel: route.label,
          reasoningLabel: route.reasoning,
          contextTokens,
          provenance,
        };
        onMessagesChange((current) => [...current, assistant]);
        setRunPhase(null);
        timersRef.current = [];
      }, 1550),
    ];
  }, [contextTokens, draft, includedContext, isLiveThread, onMessagesChange, onSendMessage, runPhase, workMode]);


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

        {!isLiveThread ? (
          <div className="chat-demo-banner">
            <Sparkles size={13} />
            <span>This is a <strong>demo thread</strong>. Replies shown here are illustrative and were not sent to the backend.</span>
            {onStartLiveChat ? (
              <button
                className="demo-start-live-button"
                type="button"
                onClick={() => { void onStartLiveChat(draft.trim()); }}
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
                    <strong>{isUser ? 'You' : 'AURA'}</strong>
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
        {runPhase ? <AIRunStrip phase={runPhase} specialist={activeRoute.specialist} onStop={stopRun} /> : null}
        <div className="chat-composer chat-composer--ai">
          {contextOpen ? (
            <AIContextPanel
              items={contextItems}
              scope={scope}
              onScopeChange={setScope}
              onToggleItem={(id) => setContextItems((current) => current.map((item) => item.id === id ? { ...item, included: !item.included } : item))}
              onClose={() => setContextOpen(false)}
            />
          ) : null}

          <div className="ai-composer-toolbar">
            <div className="ai-mode-switch" role="group" aria-label="AURA work mode">
              {workModes.map(({ id, label, icon: Icon }) => (
                <button key={id} type="button" className={workMode === id ? 'is-active' : ''} onClick={() => setWorkMode(id)}>
                  <Icon size={11} /> {label}
                </button>
              ))}
            </div>
            <span className="ai-route-preview"><Sparkles size={11} /> {activeRoute.specialist} · {activeRoute.reasoning}</span>
          </div>

          <textarea
            value={draft}
            onChange={(event) => setDraft(event.target.value)}
            onKeyDown={(event) => {
              if (event.key === 'Enter' && !event.shiftKey) {
                event.preventDefault();
                submit();
              }
            }}
            placeholder="Ask AURA in this chat…"
            rows={compact ? 2 : 3}
          />

          <div className="chat-composer__footer">
            <div className="composer-tools">
              <button className="icon-button" type="button" aria-label="Attach project object" title="Attach project file or object" onClick={onAttachRequest}><Paperclip size={16} /></button>
              <button className={`composer-context ${contextOpen ? 'is-active' : ''}`} type="button" onClick={() => setContextOpen((value) => !value)}>
                <span className="composer-context__icon"><Layers3 size={13} /></span>
                <span className="composer-context__copy">
                  <strong>Context</strong>
                  <small>{scopeLabel[scope]}</small>
                </span>
                <span className="composer-context__stats">{includedContext.length} objects · {(contextTokens / 1000).toFixed(1)}k</span>
                <ChevronDown className="composer-context__chevron" size={11} />
              </button>
            </div>
            <button className="send-button" type="button" onClick={submit} aria-label="Send" disabled={!draft.trim() || Boolean(runPhase)}>
              <ArrowUp size={17} />
            </button>
          </div>
        </div>
      </div>

      {openExecution ? <ExecutionSidecar title={openExecution.title} steps={openExecution.steps} onClose={() => setOpenExecution(null)} /> : null}
    </div>
  );
}
