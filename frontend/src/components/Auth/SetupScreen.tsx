import { useState, useRef, useEffect } from 'react'
import { useAuthStore } from '../../stores/authStore'
import { useToastStore } from '../../stores/toastStore'
import { Box, Shield, Zap, Clock, AlertTriangle, Check } from 'lucide-react'

interface Props {
  onDone: () => void
}

export function SetupScreen({ onDone }: Props) {
  const { setup } = useAuthStore()
  const toast = useToastStore(s => s.add)
  const [username, setUsername] = useState('')
  const [password, setPassword] = useState('')
  const [confirmPassword, setConfirmPassword] = useState('')
  const [error, setError] = useState('')
  const [loading, setLoading] = useState(false)
  const inputRef = useRef<HTMLInputElement>(null)

  useEffect(() => { inputRef.current?.focus() }, [])

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault()
    if (!username.trim()) { setError('Username is required'); return }
    if (!password) { setError('Password is required'); return }
    if (password.length < 8) { setError('Password must be at least 8 characters'); return }
    if (password !== confirmPassword) { setError('Passwords do not match'); return }
    setLoading(true); setError('')
    try {
      await setup(username.trim(), password)
      toast('success', 'Admin account created — you are now signed in')
      onDone()
    } catch (err) {
      const msg = err instanceof Error ? err.message : 'Setup failed'
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

      {/* Right — setup form */}
      <div style={{ flex: 1, display: 'flex', alignItems: 'center', justifyContent: 'center', padding: 64 }}>
        <form onSubmit={handleSubmit} style={{ width: '100%', maxWidth: 360 }} aria-label="Setup form">
          <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 4 }}>
            <Check size={18} color="var(--success)" />
            <h2 style={{ fontSize: 20, fontWeight: 700 }}>First-time setup</h2>
          </div>
          <p style={{ fontSize: 13, color: 'var(--mute)', marginBottom: 24 }}>
            Create your admin account to get started. This is the only time setup is required.
          </p>

          {error && <div role="alert" style={{ background: 'rgba(255,59,48,0.08)', border: '1px solid var(--danger)', borderRadius: 4, padding: '10px 14px', color: 'var(--danger)', fontSize: 13, marginBottom: 16 }}><AlertTriangle size={13} style={{ marginRight: 6, verticalAlign: -2 }} />{error}</div>}

          <label style={{ fontSize: 13, color: 'var(--mute)', display: 'block', marginBottom: 4 }}>Username</label>
          <input ref={inputRef} className="input" value={username} onChange={e => setUsername(e.target.value)} placeholder="admin" autoFocus aria-label="Username" style={{ marginBottom: 14 }} />

          <label style={{ fontSize: 13, color: 'var(--mute)', display: 'block', marginBottom: 4 }}>Password</label>
          <input className="input" type="password" value={password} onChange={e => setPassword(e.target.value)} placeholder="min 8 characters" aria-label="Password" style={{ marginBottom: 14 }} />

          <label style={{ fontSize: 13, color: 'var(--mute)', display: 'block', marginBottom: 4 }}>Confirm password</label>
          <input className="input" type="password" value={confirmPassword} onChange={e => setConfirmPassword(e.target.value)} placeholder="repeat password" aria-label="Confirm password" style={{ marginBottom: 20 }} />

          <button type="submit" className="btn-primary" disabled={loading} style={{ width: '100%', justifyContent: 'center' }}>
            {loading ? 'Creating...' : 'Create admin account'}
          </button>
        </form>
      </div>
    </div>
  )
}
