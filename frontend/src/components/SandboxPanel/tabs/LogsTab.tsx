import { useState } from 'react'
import { api } from '../../../api/client'
import { useToastStore } from '../../../stores/toastStore'
import { Search, AlertTriangle } from 'lucide-react'

interface Props { sandboxId: string }

export function LogsTab({ sandboxId }: Props) {
  const toast = useToastStore(s => s.add)
  const [logType] = useState('both')
  const [lines, setLines] = useState<string[]>([])
  const [filter, setFilter] = useState('')
  const [error, setError] = useState('')

  const load = async () => {
    try {
      const r = await api.exec(sandboxId, logType === 'stdout' ? 'cat /dev/stdout' : logType === 'stderr' ? 'cat /dev/stderr' : 'echo Use stdout or stderr tab')
      setLines(r.stdout.split('\n').filter(Boolean)); setError('')
    } catch { setError('Failed to load logs'); toast('error', 'Failed to load logs') }
  }

  const filtered = filter ? lines.filter(l => l.toLowerCase().includes(filter.toLowerCase())) : lines

  return (
    <div style={{ padding: 24, height: '100%', display: 'flex', flexDirection: 'column' }}>
      <div style={{ display: 'flex', gap: 8, marginBottom: 12 }}>
        <button onClick={load} className="btn-secondary" style={{ fontSize: 13, gap: 4 }}>load logs</button>
        <div style={{ position: 'relative', flex: 1 }}>
          <Search size={12} style={{ position: 'absolute', left: 10, top: '50%', transform: 'translateY(-50%)', color: 'var(--ash)' }} />
          <input className="input" placeholder="filter logs" value={filter} onChange={e => setFilter(e.target.value)} style={{ paddingLeft: 30 }} aria-label="Filter logs" />
        </div>
      </div>

      {error && <div role="alert" style={{ background: 'rgba(255,59,48,0.08)', border: '1px solid var(--danger)', borderRadius: 4, padding: '10px 14px', color: 'var(--danger)', fontSize: 13, marginBottom: 12 }}><AlertTriangle size={13} style={{ marginRight: 6, verticalAlign: -2 }} />{error}</div>}

      <pre style={{ flex: 1, fontSize: 12, lineHeight: 1.6, background: 'var(--surface-soft)', border: '1px solid var(--hairline)', borderRadius: 4, padding: 16, overflow: 'auto', fontFamily: 'var(--mono)' }}>
        {filtered.length > 0 ? filtered.join('\n') : 'No logs'}
      </pre>
    </div>
  )
}
