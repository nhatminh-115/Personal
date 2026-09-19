import React from 'react'

interface AppLayoutProps {
  sidebar: React.ReactNode
  chat: React.ReactNode
  inspector: React.ReactNode
}

export const AppLayout: React.FC<AppLayoutProps> = ({ sidebar, chat, inspector }) => {
  return (
    <div className="app-container">
      {sidebar}
      {chat}
      {inspector}
    </div>
  )
}
