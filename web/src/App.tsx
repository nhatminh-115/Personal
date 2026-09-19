import React, { useState, useEffect, useCallback } from 'react'
import { AppLayout } from './components/layout/AppLayout'
import { Sidebar } from './components/sidebar/Sidebar'
import { ChatView } from './components/chat/ChatView'
import { Inspector } from './components/inspector/Inspector'
import { api } from './services/api'
import {
  ApprovalDetail,
  ChatMessage,
  MemoryItem,
  ModelCatalog,
  ResearchInspectorData,
  RunDetail,
  SessionSummary,
} from './types'

function generateUUID(): string {
  if (typeof crypto !== 'undefined' && crypto.randomUUID) {
    return crypto.randomUUID()
  }
  return 'xxxxxxxx-xxxx-4xxx-yxxx-xxxxxxxxxxxx'.replace(/[xy]/g, (c) => {
    const r = (Math.random() * 16) | 0
    const v = c === 'x' ? r : (r & 0x3) | 0x8
    return v.toString(16)
  })
}

export const App: React.FC = () => {
  // State: Sessions & Active Session
  const [sessions, setSessions] = useState<SessionSummary[]>([])
  const [activeSessionId, setActiveSessionId] = useState<string>(() => `sess-${generateUUID().slice(0, 8)}`)
  const [activeProjectName, setActiveProjectName] = useState<string>('Atlas_Architecture')
  const [messages, setMessages] = useState<ChatMessage[]>([])

  // State: Model Catalog & Selected Override
  const [catalog, setCatalog] = useState<ModelCatalog>({ providers: [] })
  const [selectedModelOverride, setSelectedModelOverride] = useState<string | null>(null)

  // State: Active Run, Approvals & Inspector
  const [currentRunId, setCurrentRunId] = useState<string | null>(null)
  const [currentRunStatus, setCurrentRunStatus] = useState<string | null>(null)
  const [currentApproval, setCurrentApproval] = useState<ApprovalDetail | null>(null)
  const [runDetail, setRunDetail] = useState<RunDetail | null>(null)
  const [researchData, setResearchData] = useState<ResearchInspectorData | null>(null)
  const [memories, setMemories] = useState<MemoryItem[]>([])
  const [isInspectorOpen, setIsInspectorOpen] = useState<boolean>(true)

  // 1. Initial Data Load
  const loadInitialData = useCallback(async () => {
    try {
      const [modelsData, sessionsData] = await Promise.all([
        api.fetchModels().catch(() => ({ providers: [] })),
        api.fetchSessions().catch(() => []),
      ])
      setCatalog(modelsData)
      setSessions(sessionsData)
    } catch (e) {
      console.error('Error loading initial data', e)
    }
  }, [])

  useEffect(() => {
    loadInitialData()
  }, [loadInitialData])

  // 2. Load memories when project changes
  useEffect(() => {
    if (activeProjectName) {
      api.fetchMemories(activeProjectName).then(setMemories).catch(() => setMemories([]))
    }
  }, [activeProjectName])

  // 3. Load conversation when activeSessionId changes
  const loadSession = useCallback(async (sessionId: string) => {
    setActiveSessionId(sessionId)
    setCurrentRunId(null)
    setCurrentRunStatus(null)
    setCurrentApproval(null)
    setRunDetail(null)
    setResearchData(null)

    try {
      const detail = await api.fetchSession(sessionId)
      setMessages(detail.messages || [])
    } catch {
      setMessages([])
    }
  }, [])

  // 4. Handle "New Chat"
  const handleNewChat = () => {
    const newId = `sess-${generateUUID().slice(0, 8)}`
    setActiveSessionId(newId)
    setMessages([])
    setCurrentRunId(null)
    setCurrentRunStatus(null)
    setCurrentApproval(null)
    setRunDetail(null)
    setResearchData(null)
  }

  // 5. Send Chat Message
  const handleSendMessage = async (text: string) => {
    const userMsg: ChatMessage = {
      role: 'user',
      content: text,
      created_at: new Date().toISOString(),
    }
    setMessages((prev) => [...prev, userMsg])
    setCurrentRunStatus('running')

    try {
      const resp = await api.sendChat(
        activeSessionId,
        text,
        activeProjectName || undefined,
        selectedModelOverride
      )

      setCurrentRunId(resp.run_id)
      setCurrentRunStatus(resp.status)

      if (resp.status === 'waiting_for_approval' && resp.approval_id) {
        // Fetch approval details
        const appDetail = await api.fetchApproval(resp.approval_id)
        setCurrentApproval(appDetail)
      } else {
        setCurrentApproval(null)
        if (resp.response) {
          const assistantMsg: ChatMessage = {
            role: 'assistant',
            content: resp.response,
            created_at: new Date().toISOString(),
          }
          setMessages((prev) => [...prev, assistantMsg])
        }
      }

      // Update Inspector data
      if (resp.run_id) {
        refreshInspectorData(resp.run_id)
      }

      // Refresh sessions list
      api.fetchSessions().then(setSessions).catch(() => {})
      if (activeProjectName) {
        api.fetchMemories(activeProjectName).then(setMemories).catch(() => {})
      }
    } catch (err: any) {
      setCurrentRunStatus('failed')
      const errorMsg: ChatMessage = {
        role: 'assistant',
        content: `Error: ${err.message || 'Execution failed'}`,
        created_at: new Date().toISOString(),
      }
      setMessages((prev) => [...prev, errorMsg])
    }
  }

  // 6. Handle Approval Decision
  const handleApprovalDecision = async (
    decision: 'approved' | 'rejected' | 'edited',
    notes?: string,
    editedInput?: Record<string, any>
  ) => {
    if (!currentApproval) return

    setCurrentRunStatus('running')
    try {
      const decisionResp = await api.submitApproval(
        currentApproval.id,
        decision,
        notes,
        editedInput
      )

      setCurrentRunStatus(decisionResp.execution_status)

      if (decisionResp.execution_status === 'waiting_for_approval' && decisionResp.approval_id) {
        // Next approval in multi-tool cycle
        const nextApp = await api.fetchApproval(decisionResp.approval_id)
        setCurrentApproval(nextApp)
      } else {
        setCurrentApproval(null)
        if (decisionResp.final_response) {
          const assistantMsg: ChatMessage = {
            role: 'assistant',
            content: decisionResp.final_response,
            created_at: new Date().toISOString(),
          }
          setMessages((prev) => [...prev, assistantMsg])
        }
      }

      if (currentRunId) {
        refreshInspectorData(currentRunId)
      }
      if (activeProjectName) {
        api.fetchMemories(activeProjectName).then(setMemories).catch(() => {})
      }
    } catch (err: any) {
      setCurrentRunStatus('failed')
      console.error('Approval decision error:', err)
    }
  }

  // 7. Refresh Inspector Data
  const refreshInspectorData = async (runId: string) => {
    try {
      const [rDetail, rResearch] = await Promise.all([
        api.fetchRunDetails(runId).catch(() => null),
        api.fetchRunResearch(runId).catch(() => null),
      ])
      if (rDetail) setRunDetail(rDetail)
      if (rResearch) setResearchData(rResearch)
    } catch (e) {
      console.error('Failed to load inspector data', e)
    }
  }

  return (
    <AppLayout
      sidebar={
        <Sidebar
          sessions={sessions}
          activeSessionId={activeSessionId}
          activeProjectName={activeProjectName}
          catalog={catalog}
          selectedModelOverride={selectedModelOverride}
          onNewChat={handleNewChat}
          onSelectSession={loadSession}
          onProjectChange={setActiveProjectName}
          onSelectModel={setSelectedModelOverride}
          onCatalogRefresh={setCatalog}
        />
      }
      chat={
        <ChatView
          messages={messages}
          activeSessionId={activeSessionId}
          activeProjectName={activeProjectName}
          selectedModelOverride={selectedModelOverride}
          currentRunStatus={currentRunStatus}
          currentApproval={currentApproval}
          isInspectorOpen={isInspectorOpen}
          onToggleInspector={() => setIsInspectorOpen(!isInspectorOpen)}
          onSendMessage={handleSendMessage}
          onApprovalDecision={handleApprovalDecision}
        />
      }
      inspector={
        <Inspector
          isOpen={isInspectorOpen}
          runDetail={runDetail}
          researchData={researchData}
          memories={memories}
          onClose={() => setIsInspectorOpen(false)}
        />
      }
    />
  )
}

export default App
