import React, { useState } from 'react'
import { ModelCatalog } from '../../types'
import { api } from '../../services/api'
import { ChevronDown, RefreshCw, Cpu, Cloud } from 'lucide-react'

interface ModelPickerProps {
  catalog: ModelCatalog
  selectedOverride: string | null // e.g. "ollama:llama3.2" or null for Auto
  onSelectModel: (override: string | null) => void
  onCatalogRefresh: (newCatalog: ModelCatalog) => void
}

export const ModelPicker: React.FC<ModelPickerProps> = ({
  catalog,
  selectedOverride,
  onSelectModel,
  onCatalogRefresh,
}) => {
  const [isOpen, setIsOpen] = useState(false)
  const [isRefreshing, setIsRefreshing] = useState(false)
  const [probingModel, setProbingModel] = useState<string | null>(null)
  const [probeMessage, setProbeMessage] = useState<string | null>(null)

  const handleRefresh = async (e: React.MouseEvent) => {
    e.stopPropagation()
    setIsRefreshing(true)
    setProbeMessage(null)
    try {
      const refreshed = await api.refreshModels()
      onCatalogRefresh(refreshed)
    } catch (err: any) {
      console.error('Failed to refresh models', err)
    } finally {
      setIsRefreshing(false)
    }
  }

  const handleProbe = async (providerId: string, modelId: string, e: React.MouseEvent) => {
    e.stopPropagation()
    const probeKey = `${providerId}:${modelId}`
    setProbingModel(probeKey)
    setProbeMessage(null)
    try {
      const res = await api.probeModel(providerId, modelId)
      setProbeMessage(`[${modelId}] ${res.tool_support.toUpperCase()}: ${res.details}`)
      const refreshed = await api.fetchModels()
      onCatalogRefresh(refreshed)
    } catch (err: any) {
      setProbeMessage(`Probe error: ${err.message}`)
    } finally {
      setProbingModel(null)
    }
  }

  // Determine current active label
  const getSelectedLabel = () => {
    if (!selectedOverride) {
      return 'Auto (AURA Dynamic Routing)'
    }
    const [prov, ...modelParts] = selectedOverride.split(':')
    const model = modelParts.join(':')
    const provider = catalog.providers.find((p) => p.id === prov)
    const label = provider ? provider.label : prov
    return `${label} · ${model}`
  }

  const isLocalSelected = selectedOverride?.startsWith('ollama:') || selectedOverride?.startsWith('lmstudio:')

  return (
    <div className="model-picker-wrapper">
      <button
        type="button"
        className="model-picker-trigger"
        onClick={() => setIsOpen(!isOpen)}
        aria-label="Select Model"
      >
        <span className="model-tag">
          {selectedOverride ? (
            isLocalSelected ? (
              <span className="badge-privacy-local">LOCAL</span>
            ) : (
              <span className="badge-privacy-cloud">CLOUD</span>
            )
          ) : (
            <span className="app-badge">AUTO</span>
          )}
          <span style={{ maxWidth: '170px', overflow: 'hidden', textOverflow: 'ellipsis' }}>
            {getSelectedLabel()}
          </span>
        </span>
        <ChevronDown size={14} style={{ opacity: 0.7 }} />
      </button>

      {isOpen && (
        <div className="model-picker-dropdown">
          <div className="picker-group-title">
            <span>Model Selection</span>
            <button
              type="button"
              onClick={handleRefresh}
              disabled={isRefreshing}
              style={{
                background: 'none',
                border: 'none',
                color: 'var(--text-muted)',
                cursor: 'pointer',
                display: 'flex',
                alignItems: 'center',
                gap: 4,
                fontSize: 10,
              }}
              title="Refresh provider discovery"
            >
              <RefreshCw size={11} className={isRefreshing ? 'animate-spin' : ''} />
              {isRefreshing ? 'Scanning...' : 'Refresh'}
            </button>
          </div>

          {probeMessage && (
            <div
              style={{
                padding: '6px 8px',
                fontSize: 11,
                color: '#60a5fa',
                backgroundColor: 'rgba(59, 130, 246, 0.1)',
                borderRadius: 4,
                marginBottom: 6,
              }}
            >
              {probeMessage}
            </div>
          )}

          {/* Option: Auto */}
          <div
            className={`picker-item ${selectedOverride === null ? 'selected' : ''}`}
            onClick={() => {
              onSelectModel(null)
              setIsOpen(false)
            }}
          >
            <div>
              <strong>Auto (Adaptive Policy)</strong>
              <div style={{ fontSize: 11, color: 'var(--text-muted)' }}>
                Routes dynamically based on privacy, task type & capabilities
              </div>
            </div>
          </div>

          <div style={{ height: 1, backgroundColor: 'var(--border-subtle)', margin: '6px 0' }} />

          {/* Group: Local Providers */}
          <div className="picker-group-title">
            <span style={{ display: 'flex', alignItems: 'center', gap: 4 }}>
              <Cpu size={12} /> Local Runtimes
            </span>
          </div>

          {catalog.providers
            .filter((p) => p.kind === 'local' && p.id !== 'mock')
            .map((prov) => (
              <div key={prov.id} style={{ marginBottom: 6 }}>
                <div
                  style={{
                    fontSize: 11,
                    fontWeight: 600,
                    color: prov.available ? 'var(--text-secondary)' : 'var(--text-muted)',
                    padding: '2px 8px',
                    display: 'flex',
                    alignItems: 'center',
                    justifyContent: 'space-between',
                  }}
                >
                  <span style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
                    <span className={`status-dot ${prov.available ? 'green' : 'gray'}`} />
                    {prov.label}
                  </span>
                  <span style={{ fontSize: 10, color: 'var(--text-muted)' }}>
                    {prov.available ? `${prov.models.length} model(s)` : 'Offline'}
                  </span>
                </div>

                {prov.available && prov.models.length > 0 ? (
                  prov.models.map((m) => {
                    const overrideVal = `${prov.id}:${m.id}`
                    const isSelected = selectedOverride === overrideVal
                    const isProbing = probingModel === overrideVal
                    return (
                      <div
                        key={m.id}
                        className={`picker-item ${isSelected ? 'selected' : ''}`}
                        onClick={() => {
                          onSelectModel(overrideVal)
                          setIsOpen(false)
                        }}
                      >
                        <div>
                          <div>{m.label}</div>
                          <div style={{ display: 'flex', alignItems: 'center', gap: 6, marginTop: 2 }}>
                            {m.tool_support === 'supported' && (
                              <span className="badge-tool-supported">✓ Tool Calls</span>
                            )}
                            {m.tool_support === 'unknown' && (
                              <span className="badge-tool-unknown">? Experimental</span>
                            )}
                            {m.tool_support === 'unsupported' && (
                              <span className="badge-tool-unsupported">✕ No Tools</span>
                            )}
                          </div>
                        </div>

                        {m.tool_support === 'unknown' && (
                          <button
                            type="button"
                            onClick={(e) => handleProbe(prov.id, m.id, e)}
                            disabled={isProbing}
                            style={{
                              fontSize: 10,
                              padding: '2px 6px',
                              borderRadius: 3,
                              border: '1px solid var(--border-color)',
                              background: 'transparent',
                              color: 'var(--text-secondary)',
                              cursor: 'pointer',
                            }}
                            title="Test model for structured tool calling"
                          >
                            {isProbing ? 'Testing...' : 'Probe'}
                          </button>
                        )}
                      </div>
                    )
                  })
                ) : (
                  <div style={{ fontSize: 11, color: 'var(--text-muted)', padding: '2px 8px 6px 18px' }}>
                    {prov.available ? 'No models installed' : 'Server not reachable on localhost'}
                  </div>
                )}
              </div>
            ))}

          <div style={{ height: 1, backgroundColor: 'var(--border-subtle)', margin: '6px 0' }} />

          {/* Group: Cloud Providers */}
          <div className="picker-group-title">
            <span style={{ display: 'flex', alignItems: 'center', gap: 4 }}>
              <Cloud size={12} /> Cloud Providers
            </span>
          </div>

          {catalog.providers
            .filter((p) => p.kind === 'cloud')
            .map((prov) => (
              <div key={prov.id}>
                <div
                  style={{
                    fontSize: 11,
                    fontWeight: 600,
                    color: prov.available ? 'var(--text-secondary)' : 'var(--text-muted)',
                    padding: '2px 8px',
                    display: 'flex',
                    alignItems: 'center',
                    justifyContent: 'space-between',
                  }}
                >
                  <span style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
                    <span className={`status-dot ${prov.available ? 'green' : 'gray'}`} />
                    {prov.label}
                  </span>
                  <span style={{ fontSize: 10, color: 'var(--text-muted)' }}>
                    {prov.available ? 'Configured' : 'Missing API Key'}
                  </span>
                </div>

                {prov.available &&
                  prov.models.map((m) => {
                    const overrideVal = `${prov.id}:${m.id}`
                    const isSelected = selectedOverride === overrideVal
                    return (
                      <div
                        key={m.id}
                        className={`picker-item ${isSelected ? 'selected' : ''}`}
                        onClick={() => {
                          onSelectModel(overrideVal)
                          setIsOpen(false)
                        }}
                      >
                        <div>
                          <div>{m.label}</div>
                          <span className="badge-tool-supported" style={{ fontSize: 10 }}>
                            ✓ Standard Agent Support
                          </span>
                        </div>
                        <span className="badge-privacy-cloud">Cloud</span>
                      </div>
                    )
                  })}
              </div>
            ))}
        </div>
      )}
    </div>
  )
}
