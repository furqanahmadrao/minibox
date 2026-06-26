import { useState, useEffect } from 'react'
import { api } from '../../../api/client'
import { useToastStore } from '../../../stores/toastStore'
import { Clock, Trash2, AlertTriangle } from 'lucide-react'

interface Props { sandboxId: string }

export function SchedulesTab({ sandboxId }: Props) {
  const toast = useToastStore(s => s.add)
  const [schedules, setSchedules] = useState<Array<{ id: string; name: string; command: string; schedule: string; enabled: boolean }>>([])
  const [name, setName] = useState('')
  const [cmd, setCmd] = useState('')
  const [cron, setCron] = useState('')
  const [creating, setCreating] = useState(false)
  const [confirmId, setConfirmId] = useState<string | null>(null)
  const [error, setError] = useState('')

  const load = async () => {
    try { const r = await api.listSchedules(sandboxId); setSchedules(r) }
    catch { setError('Failed to load schedules'); toast('error', 'Failed to load schedules') }
  }

  useEffect(() => {
    load()
  }, [sandboxId])

  const create = async () => {
    if (!cmd.trim() || !cron.trim()) return
    setCreating(true); setError('')
    try { await api.createSchedule(sandboxId, name.trim() || cmd.trim(), cmd.trim(), cron.trim()); setCmd(''); setCron(''); setName(''); await load(); toast('success', 'Schedule created') }
    catch { setError('Failed to create schedule'); toast('error', 'Failed to create schedule') }
    finally { setCreating(false) }
  }

  const remove = async (sid: string) => {
    try { await api.deleteSchedule(sandboxId, sid); setConfirmId(null); await load(); toast('success', 'Schedule deleted') }
    catch { setError('Failed to delete schedule'); toast('error', 'Failed to delete schedule') }
  }

  return (
    <div style={{ padding: 24 }}>
      <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr 1fr auto', gap: 8, marginBottom: 16 }}>
        <input className="input" placeholder="name" value={name} onChange={e => setName(e.target.value)} aria-label="Schedule name" />
        <input className="input" placeholder="command" value={cmd} onChange={e => setCmd(e.target.value)} aria-label="Cron command" />
        <input className="input" placeholder="* * * * *" value={cron} onChange={e => setCron(e.target.value)} aria-label="Cron expression" />
        <button onClick={create} disabled={creating || !cmd.trim()} className="btn-primary" style={{ gap: 4 }}><Clock size={12} /> {creating ? 'creating...' : 'create'}</button>
      </div>

      {error && <div role="alert" style={{ background: 'rgba(255,59,48,0.08)', border: '1px solid var(--danger)', borderRadius: 4, padding: '10px 14px', color: 'var(--danger)', fontSize: 13, marginBottom: 16 }}><AlertTriangle size={13} style={{ marginRight: 6, verticalAlign: -2 }} />{error}</div>}

      {schedules.map(s => (
        <div key={s.id} style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', padding: '10px 14px', background: 'var(--surface-soft)', border: '1px solid var(--hairline)', borderRadius: 4, marginBottom: 6 }}>
          <div style={{ flex: 1 }}>
            <span style={{ fontWeight: 700, marginRight: 12 }}>{s.name}</span>
            <span className="mono" style={{ fontSize: 13 }}>{s.command}</span>
            <div style={{ fontSize: 12, color: 'var(--ash)', marginTop: 2 }}>{s.schedule}</div>
          </div>
          <button onClick={() => setConfirmId(s.id)} className="btn-icon danger" aria-label={`Delete schedule ${s.name}`}><Trash2 size={14} /></button>
        </div>
      ))}

      <button onClick={load} className="btn-ghost" style={{ marginTop: 8, fontSize: 12 }}>refresh</button>

      {confirmId && (
        <div className="confirm-overlay" onClick={() => setConfirmId(null)}>
          <div className="confirm-dialog" onClick={e => e.stopPropagation()} role="alertdialog" aria-labelledby="confirm-title" aria-describedby="confirm-desc">
            <h3 id="confirm-title">Delete schedule?</h3>
            <p id="confirm-desc">This will permanently remove the scheduled command.</p>
            <div className="confirm-actions">
              <button className="btn-secondary" onClick={() => setConfirmId(null)}>Cancel</button>
              <button className="btn-danger" onClick={() => remove(confirmId)}>Delete</button>
            </div>
          </div>
        </div>
      )}
    </div>
  )
}
