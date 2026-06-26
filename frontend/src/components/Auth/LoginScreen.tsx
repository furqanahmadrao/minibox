import { useState } from 'react'
import { useAuthStore } from '../../stores/authStore'
import { useToastStore } from '../../stores/toastStore'
import { Box, Shield, Zap, Clock, AlertTriangle } from 'lucide-react'

interface Props {
  onSetup: () => void
  needsSetup: boolean
}

export function LoginScreen({ onSetup, needsSetup }: Props) {
  const { login } = useAuthStore()
  const toast = useToastStore(s => s.add)
  const [username, setUsername] = useState('')
  const [password, setPassword] = useState('')
  const [error, setError] = useState('')
  const [loading, setLoading] = useState(false)

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault()
    if (!username || !password) { setError('Username and password required'); return }
    setLoading(true); setError('')
    try { await login(username, password) }
    catch (err) {
      const msg = err instanceof Error ? err.message : 'Login failed'
      setError(msg); toast('error', msg)
    } finally { setLoading(false) }
  }

  return (
    <div style={{ minHeight: '100vh', display: 'flex', background: 'var(--canvas)' }}>
      {/* Left — product info */}
      <div style={{ flex: 1, display: 'flex', flexDirection: 'column', justifyContent: 'center', padding: '64px 80px', background: 'var(--surface-soft)', borderRight: '1px solid var(--hairline)' }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: 12, marginBottom: 12 }}>
          <div style={{ width: 48, height: 48, background: 'var(--accent)', borderRadius: 8, display: 'flex', alignItems: 'center', justifyContent: 'center' }}><Box size={24} color="white" /></div>
          <span style={{ fontSize: 28, fontWeight: 700 }}>minibox</span>
        </div>
        <p style={{ fontSize: 14, color: 'var(--mute)', lineHeight: 1.7, maxWidth: 440, marginBottom: 32 }}>
          Isolated sandboxes for AI agents. Run code safely with granular resource limits, network controls, and persistent storage.
        </p>
        <div style={{ display: 'flex', flexDirection: 'column', gap: 20, maxWidth: 400 }}>
          {[
            { icon: <Shield size={18} color="var(--success)" />, title: 'Isolation', desc: 'bubblewrap sandboxing with seccomp, cgroups, and namespace controls' },
            { icon: <Zap size={18} color="var(--accent)" />, title: 'Fast Execution', desc: 'Sub-second sandbox startup with namespace-based isolation' },
            { icon: <Clock size={18} color="var(--warning)" />, title: 'Persistent State', desc: 'Workspace snapshots survive sandbox restarts and resets' },
          ].map((f, i) => (
            <div key={i} style={{ display: 'flex', gap: 14 }}>
              <div style={{ width: 36, height: 36, background: 'var(--surface-card)', borderRadius: 6, display: 'flex', alignItems: 'center', justifyContent: 'center', flexShrink: 0 }}>{f.icon}</div>
              <div><div style={{ fontWeight: 700, fontSize: 14, marginBottom: 2 }}>{f.title}</div><div style={{ fontSize: 13, color: 'var(--mute)', lineHeight: 1.5 }}>{f.desc}</div></div>
            </div>
          ))}
        </div>
      </div>

      {/* Right — login form */}
      <div style={{ flex: 1, display: 'flex', alignItems: 'center', justifyContent: 'center', padding: 64 }}>
        <form onSubmit={handleSubmit} style={{ width: '100%', maxWidth: 360 }} aria-label="Login form">
          <h2 style={{ fontSize: 20, fontWeight: 700, marginBottom: 4 }}>Sign in</h2>
          <p style={{ fontSize: 13, color: 'var(--mute)', marginBottom: 24 }}>Enter your credentials to access minibox.</p>

          {error && <div role="alert" style={{ background: 'rgba(255,59,48,0.08)', border: '1px solid var(--danger)', borderRadius: 4, padding: '10px 14px', color: 'var(--danger)', fontSize: 13, marginBottom: 16 }}><AlertTriangle size={13} style={{ marginRight: 6, verticalAlign: -2 }} />{error}</div>}

          <label style={{ fontSize: 13, color: 'var(--mute)', display: 'block', marginBottom: 4 }}>Username</label>
          <input className="input" value={username} onChange={e => setUsername(e.target.value)} placeholder="admin" autoFocus aria-label="Username" style={{ marginBottom: 14 }} />

          <label style={{ fontSize: 13, color: 'var(--mute)', display: 'block', marginBottom: 4 }}>Password</label>
          <input className="input" type="password" value={password} onChange={e => setPassword(e.target.value)} placeholder="password" aria-label="Password" style={{ marginBottom: 20 }} />

          <button type="submit" className="btn-primary" disabled={loading} style={{ width: '100%', justifyContent: 'center' }}>
            {loading ? 'Signing in...' : 'Sign in'}
          </button>

          {needsSetup && (
            <div style={{ textAlign: 'center', marginTop: 16 }}>
              <button type="button" onClick={onSetup} className="btn-ghost" style={{ fontSize: 13, color: 'var(--accent)' }}>
                First time? Set up admin account
              </button>
            </div>
          )}
        </form>
      </div>
    </div>
  )
}
