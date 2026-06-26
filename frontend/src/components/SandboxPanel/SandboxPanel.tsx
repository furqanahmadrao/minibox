import { useState } from 'react'
import { useSandboxStore } from '../../stores/sandboxStore'
import { useToastStore } from '../../stores/toastStore'
import { api } from '../../api/client'
import { OverviewTab } from './tabs/OverviewTab'
import { UsageTab } from './tabs/UsageTab'
import { TerminalTab } from './tabs/TerminalTab'
import { WorkspaceTab } from './tabs/WorkspaceTab'
import { DiffTab } from './tabs/DiffTab'
import { LogsTab } from './tabs/LogsTab'
import { SnapshotsTab } from './tabs/SnapshotsTab'
import { SchedulesTab } from './tabs/SchedulesTab'
import { SettingsTab } from './tabs/SettingsTab'
import { AgentTab } from './tabs/AgentTab'
import { BreakpointsTab } from './tabs/BreakpointsTab'
import {
  ArrowLeft, PanelLeftClose, PanelLeftOpen,
  LayoutDashboard, Activity, TerminalSquare, FolderOpen,
  GitCompare, FileText, Camera, Clock, Bot, Settings,
  Pause, Play, Trash2, Circle, AlertOctagon
} from 'lucide-react'

type Tab = 'overview' | 'usage' | 'terminal' | 'workspace' | 'diff' | 'logs' | 'snapshots' | 'schedules' | 'breakpoints' | 'agent' | 'settings'

const TAB_ICONS: Record<Tab, React.ReactNode> = {
  overview: <LayoutDashboard size={14} />,
  usage: <Activity size={14} />,
  terminal: <TerminalSquare size={14} />,
  workspace: <FolderOpen size={14} />,
  diff: <GitCompare size={14} />,
  logs: <FileText size={14} />,
  snapshots: <Camera size={14} />,
  schedules: <Clock size={14} />,
  breakpoints: <AlertOctagon size={14} />,
  agent: <Bot size={14} />,
  settings: <Settings size={14} />,
}

const TABS: { id: Tab; label: string }[] = [
  { id: 'overview', label: 'Overview' },
  { id: 'usage', label: 'Usage' },
  { id: 'terminal', label: 'Terminal' },
  { id: 'workspace', label: 'Workspace' },
  { id: 'diff', label: 'Diff' },
  { id: 'logs', label: 'Logs' },
  { id: 'snapshots', label: 'Snapshots' },
  { id: 'schedules', label: 'Schedules' },
  { id: 'breakpoints', label: 'Breakpoints' },
  { id: 'agent', label: 'Agent' },
  { id: 'settings', label: 'Settings' },
]

export function SandboxPanel() {
  const { activeId, sandboxes, openDashboard, destroy } = useSandboxStore()
  const toast = useToastStore(s => s.add)
  const [tab, setTab] = useState<Tab>('terminal')
  const [sidebarOpen, setSidebarOpen] = useState(true)
  const [confirmDestroy, setConfirmDestroy] = useState(false)
  const sandbox = sandboxes.find(s => s.sandbox_id === activeId)

  if (!activeId || !sandbox) { openDashboard(); return null }

  const statusColor = { running: 'var(--success)', paused: 'var(--warning)' }[sandbox.status] || 'var(--ash)'

  return (
    <div style={{ height: '100vh', display: 'flex', background: 'var(--canvas)' }}>
      {/* Sidebar */}
      <div className={`sidebar ${sidebarOpen ? 'expanded' : ''}`} role="navigation" aria-label="Sandbox list">
        <button onClick={openDashboard} className="sidebar-item" aria-label="Back to dashboard" title="Dashboard">
          <ArrowLeft size={14} />
          {sidebarOpen && <span>Dashboard</span>}
        </button>
        <button onClick={() => setSidebarOpen(!sidebarOpen)} className="sidebar-item" aria-label={sidebarOpen ? 'Collapse sidebar' : 'Expand sidebar'} title={sidebarOpen ? 'Collapse' : 'Expand'}>
          {sidebarOpen ? <PanelLeftClose size={14} /> : <PanelLeftOpen size={14} />}
          {sidebarOpen && <span>Collapse</span>}
        </button>
        <div className="sidebar-divider" />
        {sandboxes.filter(s => s.sandbox_id !== activeId).map(s => (
          <button key={s.sandbox_id} onClick={() => useSandboxStore.getState().setActive(s.sandbox_id)} className="sidebar-item" aria-label={`Switch to ${s.label || s.sandbox_id}`} title={s.label || s.sandbox_id}>
            <Circle size={8} fill={s.status === 'running' ? 'var(--success)' : 'var(--ash)'} color={s.status === 'running' ? 'var(--success)' : 'var(--ash)'} />
            {sidebarOpen && <span style={{ overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>{s.label || s.sandbox_id.slice(0, 12)}</span>}
          </button>
        ))}
      </div>

      {/* Main */}
      <div style={{ flex: 1, display: 'flex', flexDirection: 'column', overflow: 'hidden' }}>
        {/* Header */}
        <div style={{ display: 'flex', alignItems: 'center', padding: '0 16px', borderBottom: '1px solid var(--hairline)', gap: 12, height: 48 }}>
          <Circle size={10} fill={statusColor} color={statusColor} />
          <span style={{ fontWeight: 700, fontSize: 14 }}>{sandbox.label || sandbox.sandbox_id}</span>
          <span className="badge badge-dark">{sandbox.template}</span>
          {sandbox.agent_config?.provider && <span className="badge badge-accent">{sandbox.agent_config.provider}</span>}
          <div style={{ flex: 1 }} />
          <button onClick={() => sandbox.status === 'running' ? api.pauseSandbox(sandbox.sandbox_id) : api.resumeSandbox(sandbox.sandbox_id)} className="btn-ghost" aria-label={sandbox.status === 'running' ? 'Pause sandbox' : 'Resume sandbox'} style={{ height: 28, padding: '0 10px', fontSize: 12, gap: 4 }}>
            {sandbox.status === 'running' ? <><Pause size={12} /> pause</> : <><Play size={12} /> resume</>}
          </button>
          <button onClick={() => setConfirmDestroy(true)} className="btn-ghost" aria-label="Destroy sandbox" style={{ height: 28, padding: '0 10px', fontSize: 12, color: 'var(--danger)', gap: 4 }}>
            <Trash2 size={12} /> destroy
          </button>
        </div>

        {/* Tab bar */}
        <div role="tablist" aria-label="Sandbox tabs" style={{ display: 'flex', borderBottom: '1px solid var(--hairline)', padding: '0 12px', overflowX: 'auto' }}>
          {TABS.map(t => (
            <button key={t.id} role="tab" aria-selected={tab === t.id} aria-controls={`panel-${t.id}`} onClick={() => setTab(t.id)} className={`tab ${tab === t.id ? 'tab-active' : ''}`} style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
              {TAB_ICONS[t.id]}
              {t.label}
            </button>
          ))}
        </div>

        {/* Content */}
        <div id={`panel-${tab}`} role="tabpanel" style={{ flex: 1, overflow: 'hidden' }}>
          {tab === 'overview' && <OverviewTab sandbox={sandbox} />}
          {tab === 'usage' && <UsageTab sandboxId={activeId} />}
          {tab === 'terminal' && <TerminalTab sandboxId={activeId} />}
          {tab === 'workspace' && <WorkspaceTab sandboxId={activeId} />}
          {tab === 'diff' && <DiffTab sandboxId={activeId} />}
          {tab === 'logs' && <LogsTab sandboxId={activeId} />}
          {tab === 'snapshots' && <SnapshotsTab sandboxId={activeId} />}
          {tab === 'schedules' && <SchedulesTab sandboxId={activeId} />}
          {tab === 'breakpoints' && <BreakpointsTab sandboxId={activeId} sandboxStatus={sandbox.status} onResume={() => api.resumeSandbox(sandbox.sandbox_id)} />}
          {tab === 'agent' && <AgentTab sandbox={sandbox} />}
          {tab === 'settings' && <SettingsTab sandbox={sandbox} />}
        </div>
      </div>

      {confirmDestroy && (
        <div className="confirm-overlay" onClick={() => setConfirmDestroy(false)}>
          <div className="confirm-dialog" onClick={e => e.stopPropagation()} role="alertdialog" aria-labelledby="confirm-title" aria-describedby="confirm-desc">
            <h3 id="confirm-title">Destroy sandbox?</h3>
            <p id="confirm-desc">
              This will permanently destroy <strong>{sandbox.label || sandbox.sandbox_id.slice(0, 12)}</strong> and all its data. This action cannot be undone.
            </p>
            <div className="confirm-actions">
              <button className="btn-secondary" onClick={() => setConfirmDestroy(false)}>Cancel</button>
              <button className="btn-danger" onClick={() => { destroy(sandbox.sandbox_id); setConfirmDestroy(false); toast('success', 'Sandbox destroyed') }}>Destroy</button>
            </div>
          </div>
        </div>
      )}
    </div>
  )
}
