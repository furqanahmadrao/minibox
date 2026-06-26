import { useState } from 'react'
import { Sandbox } from '../../../stores/sandboxStore'
import { useToastStore } from '../../../stores/toastStore'
import { api } from '../../../api/client'
import { RefreshCw, Copy, Link, X } from 'lucide-react'

interface Props { sandbox: Sandbox }

export function OverviewTab({ sandbox }: Props) {
  const toast = useToastStore(s => s.add)
  const [details, setDetails] = useState<any | null>(null)
  const [refreshing, setRefreshing] = useState(false)
  const [ports, setPorts] = useState<{ port: number; host_port: number }[]>([])
  const [newPort, setNewPort] = useState('')
  const [exposing, setExposing] = useState(false)

  const refresh = async () => {
    setRefreshing(true)
    try { const d = await api.getSandbox(sandbox.sandbox_id); setDetails(d) }
    catch { toast('error', 'Failed to load details') }
    finally { setRefreshing(false) }
  }

  const loadPorts = async () => {
    try { const r = await api.listPorts(sandbox.sandbox_id); setPorts(r) }
    catch { /* ports unavailable */ }
  }

  const exposePort = async () => {
    const p = parseInt(newPort)
    if (!p || p < 1 || p > 65535) { toast('error', 'Invalid port (1-65535)'); return }
    setExposing(true)
    try {
      const r = await api.exposePort(sandbox.sandbox_id, p)
      setPorts([...ports, r])
      setNewPort('')
      toast('success', `Port ${p} exposed`)
    } catch { toast('error', 'Failed to expose port') }
    finally { setExposing(false) }
  }

  const removePort = async (p: number) => {
    try { await api.removePort(sandbox.sandbox_id, p); setPorts(ports.filter(pp => pp.port !== p)); toast('success', `Port ${p} removed`) }
    catch { toast('error', 'Failed to remove port') }
  }

  const copy = (text: string) => { navigator.clipboard.writeText(text); toast('success', 'Copied to clipboard') }

  return (
    <div style={{ padding: 24, overflow: 'auto', height: '100%' }}>
      <div style={{ fontSize: 13, lineHeight: 2, marginBottom: 24 }}>
        <div style={{ display: 'flex', justifyContent: 'space-between' }}><span style={{ color: 'var(--mute)' }}>id</span><span className="mono">{sandbox.sandbox_id}</span></div>
        <div style={{ display: 'flex', justifyContent: 'space-between' }}><span style={{ color: 'var(--mute)' }}>label</span><span>{sandbox.label}</span></div>
        <div style={{ display: 'flex', justifyContent: 'space-between' }}><span style={{ color: 'var(--mute)' }}>status</span><span style={{ color: sandbox.status === 'running' ? 'var(--success)' : 'var(--warning)' }}>{sandbox.status}</span></div>
        <div style={{ display: 'flex', justifyContent: 'space-between' }}><span style={{ color: 'var(--mute)' }}>template</span><span>{sandbox.template}</span></div>
        <div style={{ display: 'flex', justifyContent: 'space-between' }}><span style={{ color: 'var(--mute)' }}>cpu</span><span>{sandbox.cpu_cores} cores</span></div>
        <div style={{ display: 'flex', justifyContent: 'space-between' }}><span style={{ color: 'var(--mute)' }}>memory</span><span>{sandbox.memory_mb} MB</span></div>
        <div style={{ display: 'flex', justifyContent: 'space-between' }}><span style={{ color: 'var(--mute)' }}>exec</span><span>{sandbox.exec_count}</span></div>
        <div style={{ display: 'flex', justifyContent: 'space-between' }}><span style={{ color: 'var(--mute)' }}>ttl</span><span>{sandbox.ttl_remaining}s</span></div>
        <div style={{ display: 'flex', justifyContent: 'space-between' }}><span style={{ color: 'var(--mute)' }}>network</span><span>{sandbox.network_mode}</span></div>
        {sandbox.agent_config?.provider && <div style={{ display: 'flex', justifyContent: 'space-between' }}><span style={{ color: 'var(--mute)' }}>agent</span><span className="badge badge-accent">{sandbox.agent_config.provider}</span></div>}
      </div>

      <div style={{ marginBottom: 24 }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 10 }}>
          <span style={{ fontSize: 13, fontWeight: 700, color: 'var(--mute)' }}>Port Forwarding</span>
          <button onClick={loadPorts} className="btn-ghost" style={{ height: 24, padding: '0 6px', fontSize: 11, gap: 4 }}><RefreshCw size={11} /> refresh</button>
        </div>
        {ports.map(p => (
          <div key={p.port} style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 6 }}>
            <span className="badge badge-dark">{p.port}</span>
            <span style={{ color: 'var(--accent)', fontSize: 12, flex: 1 }}>host:{p.host_port}</span>
            <button onClick={() => removePort(p.port)} className="btn-icon btn-icon-sm danger" aria-label={`Remove port ${p.port}`}><X size={12} /></button>
          </div>
        ))}
        <div style={{ display: 'flex', gap: 6, marginTop: 8 }}>
          <input className="input" placeholder="port" value={newPort} onChange={e => setNewPort(e.target.value)} style={{ width: 80 }} onKeyDown={e => { if (e.key === 'Enter') exposePort() }} />
          <button onClick={exposePort} className="btn-primary" disabled={exposing} style={{ height: 30, fontSize: 12, gap: 4 }}><Link size={11} /> expose</button>
        </div>
      </div>

      <div style={{ display: 'flex', gap: 8 }}>
        <button onClick={refresh} className="btn-secondary" disabled={refreshing} style={{ gap: 4 }}><RefreshCw size={12} /> {refreshing ? 'loading...' : 'refresh details'}</button>
        {details && <button onClick={() => copy(JSON.stringify(details, null, 2))} className="btn-ghost" style={{ gap: 4 }}><Copy size={12} /> copy JSON</button>}
      </div>

      {details && (
        <pre style={{ marginTop: 16, fontSize: 12, lineHeight: 1.6, color: 'var(--ink)', background: 'var(--surface-soft)', border: '1px solid var(--hairline)', borderRadius: 4, padding: 16, overflow: 'auto' }}>
          {JSON.stringify(details, null, 2)}
        </pre>
      )}
    </div>
  )
}
