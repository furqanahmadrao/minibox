import { useState, useEffect } from 'react'
import { api } from '../../../api/client'
import { useToastStore } from '../../../stores/toastStore'
import { Camera, RotateCcw, AlertTriangle } from 'lucide-react'

interface Props { sandboxId: string }

export function SnapshotsTab({ sandboxId }: Props) {
  const toast = useToastStore(s => s.add)
  const [snapshots, setSnapshots] = useState<Array<{ snapshot_id: string; label: string; size: number; created_at: number }>>([])
  const [label, setLabel] = useState('')
  const [creating, setCreating] = useState(false)
  const [restoring, setRestoring] = useState<string | null>(null)
  const [error, setError] = useState('')

  const load = async () => {
    try { const r = await api.listSnapshots(sandboxId); setSnapshots(r) }
    catch { setError('Failed to load snapshots'); toast('error', 'Failed to load snapshots') }
  }

  useEffect(() => {
    load()
  }, [sandboxId])

  const create = async () => {
    if (!label.trim()) return
    setCreating(true); setError('')
    try { await api.createSnapshot(sandboxId, label.trim()); setLabel(''); await load(); toast('success', 'Snapshot created') }
    catch { setError('Failed to create snapshot'); toast('error', 'Failed to create snapshot') }
    finally { setCreating(false) }
  }

  const restore = async (sid: string) => {
    setRestoring(sid); setError('')
    try { await api.restoreSnapshot(sandboxId, sid); toast('success', 'Snapshot restored') }
    catch { setError('Failed to restore snapshot'); toast('error', 'Failed to restore snapshot') }
    finally { setRestoring(null) }
  }

  return (
    <div style={{ padding: 24 }}>
      <div style={{ display: 'flex', gap: 8, marginBottom: 16 }}>
        <input className="input" placeholder="snapshot label" value={label} onChange={e => setLabel(e.target.value)} onKeyDown={e => { if (e.key === 'Enter') create() }} aria-label="Snapshot label" />
        <button onClick={create} disabled={creating || !label.trim()} className="btn-primary" style={{ gap: 4 }}><Camera size={12} /> {creating ? 'creating...' : 'create'}</button>
      </div>

      {error && <div role="alert" style={{ background: 'rgba(255,59,48,0.08)', border: '1px solid var(--danger)', borderRadius: 4, padding: '10px 14px', color: 'var(--danger)', fontSize: 13, marginBottom: 16 }}><AlertTriangle size={13} style={{ marginRight: 6, verticalAlign: -2 }} />{error}</div>}

      <div style={{ fontSize: 13, fontWeight: 700, color: 'var(--mute)', marginBottom: 8 }}>Snapshots ({snapshots.length})</div>
      {snapshots.length === 0 && <div style={{ color: 'var(--ash)', fontSize: 13 }}>No snapshots yet</div>}

      {snapshots.map(s => (
        <div key={s.snapshot_id} style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', padding: '10px 14px', background: 'var(--surface-soft)', border: '1px solid var(--hairline)', borderRadius: 4, marginBottom: 6 }}>
          <div>
            <span style={{ fontWeight: 700 }}>{s.label}</span>
            <span style={{ color: 'var(--ash)', marginLeft: 12, fontSize: 12 }}>{new Date(s.created_at * 1000).toLocaleString()}</span>
          </div>
          <button onClick={() => restore(s.snapshot_id)} disabled={restoring === s.snapshot_id} className="btn-ghost" style={{ fontSize: 12, gap: 4 }}><RotateCcw size={11} /> {restoring === s.snapshot_id ? 'restoring...' : 'restore'}</button>
        </div>
      ))}

      <button onClick={load} className="btn-ghost" style={{ marginTop: 8, fontSize: 12 }}>refresh</button>
    </div>
  )
}
