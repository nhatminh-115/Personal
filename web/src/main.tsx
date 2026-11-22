import React from 'react'
import ReactDOM from 'react-dom/client'
import '@xyflow/react/dist/style.css'
import './styles.css'
import './desktop.css'
import App from './App'
import { invoke, isTauri } from '@tauri-apps/api/core'
import { setApiToken } from './services/api'

function mount() {
  ReactDOM.createRoot(document.getElementById('root')!).render(
    <React.StrictMode>
      <App />
    </React.StrictMode>,
  )
}

if (isTauri()) {
  void Promise.all([
    invoke<string>('desktop_api_token').then((token) => setApiToken(token)).catch(() => false),
    invoke<{ phase: string }>('desktop_status').then((status) => {
      if (status.phase !== 'ready') window.sessionStorage.setItem('aura:desktop-awaiting-api-ready', '1')
    }).catch(() => window.sessionStorage.setItem('aura:desktop-awaiting-api-ready', '1')),
  ]).finally(mount)
} else {
  mount()
}
