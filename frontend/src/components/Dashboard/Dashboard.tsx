import { useState, useEffect } from 'react'
import { useSandboxStore, Sandbox } from '../../stores/sandboxStore'
import { useAuthStore } from '../../stores/authStore'
import { useToastStore } from '../../stores/toastStore'
import { NewSandboxModal } from './NewSandboxModal'
import { AuthManager } from '../Auth/AuthManager'
import { Plus, LogOut, Circle, Trash2, Play, Settings } from 'lucide-react'

export function Dashboard() {
  const { sandboxes, fetch, setActive, destroy, error } = useSandboxStore()
  const { logout } = useAuthStore()
  const toast = useToastStore(s => s.add)
  const [showNew, setShowNew] = useState(false)
  const [confirmId, setConfirmId] = useState<string | null>(null)
  const [showAuth, setShowAuth] = useState(false)

  useEffect(() => {
    fetch()
    const iv = setInterval(fetch, 5000)
    return () => clearInterval(iv)
  }, [])

  useEffect(() => {
    if (error) toast('error', error)
  }, [error])

  if (showAuth) return <AuthManager onClose={() => setShowAuth(false)} />

  const confirmSandbox = sandboxes.find(s => s.sandbox_id === confirmId)

  return (
    <div style={{ minHeight: '100vh', background: 'var(--canvas)' }}>
      <nav style={{ height: 56, display: 'flex', alignItems: 'center', justifyContent: 'space-between', padding: '0 32px', borderBottom: '1px solid var(--hairline)' }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
          <span style={{ fontSize: 18, fontWeight: 700, color: 'var(--accent)' }}>&#9632;</span>
          <span style={{ fontSize: 16, fontWeight: 700 }}>minibox</span>
        </div>
        <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
          <span style={{ fontSize: 12, color: 'var(--mute)' }}>{sandboxes.length} sandbox{sandboxes.length !== 1 ? 'es' : ''}</span>
          <button onClick={() => setShowAuth(true)} className="btn-ghost" aria-label="Server settings" style={{ height: 32, padding: '0 10px', fontSize: 12, gap: 6 }}><Settings size={14} /> settings</button>
          <button onClick={logout} className="btn-ghost" aria-label="Log out" style={{ height: 32, padding: '0 10px', fontSize: 12, gap: 6 }}><LogOut size={14} /> logout</button>
          <button onClick={() => setShowNew(true)} className="btn-primary" style={{ gap: 6 }}><Plus size={14} /> new sandbox</button>
        </div>
      </nav>

      <div style={{ maxWidth: 960, margin: '0 auto', padding: '48px 32px' }}>
        {sandboxes.length === 0 ? (
          <div style={{ textAlign: 'center', padding: '96px 0' }}>
            <div style={{ color: 'var(--ash)', marginBottom: 16 }}><Circle size={48} strokeWidth={1} /></div>
            <div style={{ fontSize: 14, color: 'var(--mute)', marginBottom: 8 }}>No sandboxes running</div>
            <div style={{ fontSize: 13, color: 'var(--ash)', marginBottom: 24 }}>Click "new sandbox" to create one</div>
            <button onClick={() => setShowNew(true)} className="btn-primary" style={{ gap: 6 }}><Plus size={14} /> create sandbox</button>
          </div>
        ) : (
          <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fill, minmax(280px, 1fr))', gap: 12 }}>
            {sandboxes.map(sb => (
              <SandboxCard key={sb.sandbox_id} sandbox={sb} onOpen={() => setActive(sb.sandbox_id)} onDestroy={() => setConfirmId(sb.sandbox_id)} />
            ))}
          </div>
        )}
      </div>

      {showNew && <NewSandboxModal onClose={() => setShowNew(false)} />}

      {confirmId && confirmSandbox && (
        <div className="confirm-overlay" onClick={() => setConfirmId(null)}>
          <div className="confirm-dialog" onClick={e => e.stopPropagation()} role="alertdialog" aria-labelledby="confirm-title" aria-describedby="confirm-desc">
            <h3 id="confirm-title">Destroy sandbox?</h3>
            <p id="confirm-desc">
              This will permanently destroy <strong>{confirmSandbox.label || confirmSandbox.sandbox_id.slice(0, 12)}</strong> and all its data. This action cannot be undone.
            </p>
            <div className="confirm-actions">
              <button className="btn-secondary" onClick={() => setConfirmId(null)}>Cancel</button>
              <button className="btn-danger" onClick={() => { destroy(confirmId); setConfirmId(null); toast('success', 'Sandbox destroyed') }}>Destroy</button>
            </div>
          </div>
        </div>
      )}
    </div>
  )
}

function SandboxCard({ sandbox: s, onOpen, onDestroy }: { sandbox: Sandbox; onOpen: () => void; onDestroy: () => void }) {
  const statusColor = { running: 'var(--success)', paused: 'var(--warning)', destroyed: 'var(--danger)' }[s.status] || 'var(--ash)'

  const fmtTTL = (sec: number) => {
    if (sec <= 0) return 'expired'
    if (sec < 60) return `${sec}s`
    const m = Math.floor(sec / 60)
    return m > 60 ? `${Math.floor(m / 60)}h ${m % 60}m` : `${m}m`
  }

  return (
    <div style={{ background: 'var(--surface-soft)', border: '1px solid var(--hairline)', padding: '16px 20px', borderRadius: 4 }}>
      <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: 12 }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
          <Circle size={10} fill={statusColor} color={statusColor} />
          <span style={{ fontWeight: 700, fontSize: 14 }}>{s.label || s.sandbox_id.slice(0, 12)}</span>
        </div>
        <span className="badge badge-dark">{s.template}</span>
      </div>

      <div style={{ fontSize: 13, lineHeight: 2 }}>
        <div style={{ display: 'flex', justifyContent: 'space-between' }}><span style={{ color: 'var(--mute)' }}>status</span><span style={{ color: statusColor }}>{s.status}</span></div>
        <div style={{ display: 'flex', justifyContent: 'space-between' }}><span style={{ color: 'var(--mute)' }}>cpu</span><span>{s.cpu_cores} cores</span></div>
        <div style={{ display: 'flex', justifyContent: 'space-between' }}><span style={{ color: 'var(--mute)' }}>memory</span><span>{s.memory_mb} MB</span></div>
        <div style={{ display: 'flex', justifyContent: 'space-between' }}><span style={{ color: 'var(--mute)' }}>exec</span><span>{s.exec_count} calls</span></div>
        <div style={{ display: 'flex', justifyContent: 'space-between' }}><span style={{ color: 'var(--mute)' }}>ttl</span><span>{fmtTTL(s.ttl_remaining)}</span></div>
        {s.agent_config?.provider && <div style={{ display: 'flex', justifyContent: 'space-between' }}><span style={{ color: 'var(--mute)' }}>agent</span><span style={{ color: 'var(--accent)' }}>{s.agent_config.provider}</span></div>}
      </div>

      <div style={{ display: 'flex', gap: 8, marginTop: 12 }}>
        <button onClick={onOpen} className="btn-primary" style={{ flex: 1, justifyContent: 'center', gap: 6 }}><Play size={12} /> open</button>
        <button onClick={onDestroy} className="btn-icon danger" aria-label="Destroy sandbox"><Trash2 size={14} /></button>
      </div>
    </div>
  )
}
