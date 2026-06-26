import { useState, useEffect } from 'react'
import { api } from '../../../api/client'
import { useToastStore } from '../../../stores/toastStore'
import { AlertOctagon, Trash2, Plus, RefreshCw, Play, ShieldAlert, BellRing } from 'lucide-react'

interface Props { 
  sandboxId: string
  sandboxStatus: string
  onResume: () => void
}

interface Breakpoint {
  id: string
  sandbox_id: string
  pattern: string
  action: string
  created_at: number
  hit_count: number
}

export function BreakpointsTab({ sandboxId, sandboxStatus, onResume }: Props) {
  const toast = useToastStore(s => s.add)
  const [breakpoints, setBreakpoints] = useState<Breakpoint[]>([])
  const [pattern, setPattern] = useState('')
  const [action, setAction] = useState('pause') // pause, block, notify
  const [loading, setLoading] = useState(false)
  const [submitting, setSubmitting] = useState(false)
  const [error, setError] = useState('')

  const load = async () => {
    setLoading(true)
    setError('')
    try {
      const res = await api.listBreakpoints(sandboxId)
      setBreakpoints(res)
    } catch (e) {
      setError('Failed to load breakpoints')
      toast('error', 'Failed to retrieve breakpoints')
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => {
    load()
  }, [sandboxId])

  const handleAdd = async (e: React.FormEvent) => {
    e.preventDefault()
    if (!pattern.trim() || submitting) return
    setSubmitting(true)
    setError('')
    try {
      await api.createBreakpoint(sandboxId, pattern.trim(), action)
      setPattern('')
      toast('success', 'Breakpoint added successfully')
      await load()
    } catch (err: any) {
      setError(err.message || 'Failed to add breakpoint')
      toast('error', 'Failed to create breakpoint')
    } finally {
      setSubmitting(false)
    }
  }

  const handleDelete = async (bpId: string) => {
    try {
      await api.deleteBreakpoint(sandboxId, bpId)
      toast('success', 'Breakpoint removed')
      await load()
    } catch (err) {
      toast('error', 'Failed to remove breakpoint')
    }
  }

  const getActionBadge = (act: string) => {
    switch (act) {
      case 'block':
        return <span className="badge badge-danger" style={{ display: 'inline-flex', alignItems: 'center', gap: 4 }}><ShieldAlert size={10} /> block</span>
      case 'notify':
        return <span className="badge badge-accent" style={{ display: 'inline-flex', alignItems: 'center', gap: 4 }}><BellRing size={10} /> notify</span>
      default:
        return <span className="badge badge-warning" style={{ display: 'inline-flex', alignItems: 'center', gap: 4 }}><Play size={10} /> pause</span>
    }
  }

  return (
    <div style={{ padding: 24, height: '100%', display: 'flex', flexDirection: 'column', overflowY: 'auto' }}>
      {/* Paused take-over warning */}
      {sandboxStatus === 'paused' && (
        <div style={{ 
          background: 'rgba(245, 158, 11, 0.1)', 
          border: '1px solid var(--warning)', 
          borderRadius: 6, 
          padding: '16px 20px', 
          marginBottom: 20,
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'space-between',
          boxShadow: '0 4px 20px rgba(0,0,0,0.15)',
          backdropFilter: 'blur(10px)'
        }}>
          <div style={{ display: 'flex', alignItems: 'center', gap: 12 }}>
            <AlertOctagon size={24} color="var(--warning)" />
            <div>
              <div style={{ fontWeight: 700, color: 'var(--warning)', fontSize: 14 }}>Sandbox Intercepted & Paused</div>
              <div style={{ fontSize: 12, color: 'var(--mute)', marginTop: 2 }}>
                An executing command hit a breakpoint. You can inspect the workspace/terminal or resume execution.
              </div>
            </div>
          </div>
          <button onClick={onResume} className="btn-primary" style={{ gap: 6, height: 32, background: 'var(--warning)', border: '1px solid var(--warning)' }}>
            <Play size={12} fill="white" /> Resume Execution
          </button>
        </div>
      )}

      {/* Title */}
      <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: 16 }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
          <AlertOctagon size={16} color="var(--accent)" />
          <span style={{ fontSize: 13, fontWeight: 700, textTransform: 'uppercase', letterSpacing: '1px', color: 'var(--mute)' }}>
            Breakpoint Manager
          </span>
        </div>
        <button onClick={load} disabled={loading} className="btn-ghost" style={{ gap: 4, height: 28, fontSize: 11 }}>
          <RefreshCw size={11} className={loading ? 'spin-anim' : ''} /> Refresh
        </button>
      </div>

      {error && (
        <div role="alert" style={{ background: 'rgba(239, 68, 68, 0.1)', border: '1px solid var(--danger)', borderRadius: 4, padding: '10px 14px', color: 'var(--danger)', fontSize: 13, marginBottom: 16 }}>
          <AlertOctagon size={13} style={{ marginRight: 6, verticalAlign: -2 }} />
          {error}
        </div>
      )}

      {/* Main Layout: Add form on left, active list on right */}
      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(300px, 1fr))', gap: 20, flex: 1 }}>
        {/* Creation Form */}
        <form onSubmit={handleAdd} style={{ 
          background: 'var(--surface-soft)', 
          border: '1px solid var(--hairline)', 
          borderRadius: 6, 
          padding: 20,
          display: 'flex',
          flexDirection: 'column',
          gap: 14,
          maxHeight: 300,
          boxShadow: '0 4px 20px rgba(0,0,0,0.15)',
          backdropFilter: 'blur(10px)'
        }}>
          <div style={{ fontSize: 12, fontWeight: 700, color: 'var(--mute)', textTransform: 'uppercase', letterSpacing: '0.5px' }}>
            Add Execution Breakpoint
          </div>
          
          <div>
            <label style={{ fontSize: 11, color: 'var(--mute)', display: 'block', marginBottom: 4 }} htmlFor="pattern-input">
              Command Regex Pattern *
            </label>
            <input 
              id="pattern-input"
              className="input" 
              placeholder="e.g. rm -rf, git push" 
              value={pattern} 
              onChange={e => setPattern(e.target.value)} 
              disabled={submitting}
              style={{ height: 32, fontSize: 12 }} 
              required
            />
          </div>

          <div>
            <label style={{ fontSize: 11, color: 'var(--mute)', display: 'block', marginBottom: 4 }} htmlFor="action-select">
              Action *
            </label>
            <select 
              id="action-select"
              className="input" 
              value={action} 
              onChange={e => setAction(e.target.value)} 
              disabled={submitting}
              style={{ height: 32, fontSize: 12 }}
            >
              <option value="pause">Pause Sandbox (Human Intervention)</option>
              <option value="block">Block Command (Abrupt Stop)</option>
              <option value="notify">Notify Only (Audit Event)</option>
            </select>
          </div>

          <button type="submit" className="btn-primary" disabled={submitting || !pattern.trim()} style={{ alignSelf: 'flex-end', height: 32, fontSize: 12, gap: 6, padding: '0 16px', marginTop: 6 }}>
            <Plus size={14} /> Add Breakpoint
          </button>
        </form>

        {/* Breakpoints List */}
        <div style={{ 
          background: 'var(--surface-soft)', 
          border: '1px solid var(--hairline)', 
          borderRadius: 6, 
          padding: 20,
          display: 'flex',
          flexDirection: 'column',
          boxShadow: '0 4px 20px rgba(0,0,0,0.15)',
          backdropFilter: 'blur(10px)'
        }}>
          <div style={{ fontSize: 12, fontWeight: 700, color: 'var(--mute)', marginBottom: 12, textTransform: 'uppercase', letterSpacing: '0.5px' }}>
            Active Breakpoints ({breakpoints.length})
          </div>

          <div style={{ flex: 1, overflowY: 'auto', display: 'flex', flexDirection: 'column', gap: 8 }}>
            {breakpoints.length === 0 ? (
              <div style={{ color: 'var(--ash)', fontSize: 12, padding: '16px 0', textAlign: 'center' }}>
                No active breakpoints configured.
              </div>
            ) : (
              breakpoints.map(bp => (
                <div key={bp.id} style={{ 
                  display: 'flex', 
                  alignItems: 'center', 
                  justifyContent: 'space-between', 
                  padding: '12px 14px', 
                  background: 'var(--surface-card)', 
                  border: '1px solid var(--hairline)', 
                  borderRadius: 4 
                }}>
                  <div style={{ display: 'flex', flexDirection: 'column', gap: 4, flex: 1 }}>
                    <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
                      <span className="mono" style={{ fontSize: 12, fontWeight: 700, color: '#f8fafc' }}>
                        {bp.pattern}
                      </span>
                      {getActionBadge(bp.action)}
                    </div>
                    <div style={{ fontSize: 11, color: 'var(--mute)' }}>
                      Hits: <span style={{ fontWeight: 700, color: bp.hit_count > 0 ? 'var(--accent)' : 'var(--mute)' }}>{bp.hit_count}</span>
                    </div>
                  </div>
                  <button onClick={() => handleDelete(bp.id)} className="btn-icon danger" aria-label={`Delete breakpoint ${bp.pattern}`}>
                    <Trash2 size={14} />
                  </button>
                </div>
              ))
            )}
          </div>
        </div>
      </div>
    </div>
  )
}
