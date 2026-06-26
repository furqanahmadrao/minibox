import { useState, useEffect, useRef } from 'react'
import { api } from '../../../api/client'
import { useToastStore } from '../../../stores/toastStore'
import { AlertTriangle, RefreshCw, Cpu, HardDrive, Clock, Terminal } from 'lucide-react'

interface Props { sandboxId: string }

interface HistoryPoint {
  cpu: number
  memory: number
  time: string
}

export function UsageTab({ sandboxId }: Props) {
  const toast = useToastStore(s => s.add)
  const [stats, setStats] = useState<any>(null)
  const [history, setHistory] = useState<HistoryPoint[]>([])
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState('')
  const intervalRef = useRef<any>(null)

  const fetchStats = async (isFirst = false) => {
    if (isFirst) setLoading(true)
    try {
      const r = await api.getSandboxStats(sandboxId)
      setStats(r)
      
      const newPoint: HistoryPoint = {
        cpu: r.cpu_percent || 0,
        memory: r.memory_mb || 0,
        time: new Date().toLocaleTimeString([], { hour: '2-digit', minute: '2-digit', second: '2-digit' })
      }
      
      setHistory(prev => {
        const next = [...prev, newPoint]
        if (next.length > 20) {
          next.shift() // Keep only last 20 points
        }
        return next
      })
      setError('')
    } catch {
      if (isFirst) {
        setError('Failed to load usage statistics')
        toast('error', 'Failed to load usage statistics')
      }
    } finally {
      if (isFirst) setLoading(false)
    }
  }

  useEffect(() => {
    // Initial fetch
    fetchStats(true)
    
    // Set up polling interval
    intervalRef.current = setInterval(() => {
      fetchStats(false)
    }, 2000)
    
    return () => {
      if (intervalRef.current) {
        clearInterval(intervalRef.current)
      }
    }
  }, [sandboxId])

  // Helper to generate SVG path
  const getSvgPath = (data: number[], width: number, height: number, maxVal: number) => {
    if (data.length < 2) return { linePath: '', areaPath: '' }
    const points = data.map((val, idx) => {
      const x = (idx / (data.length - 1)) * width
      const ratio = maxVal > 0 ? val / maxVal : 0
      const y = height - ratio * (height - 10) - 5
      return { x, y }
    })
    
    const linePath = `M ${points[0].x} ${points[0].y} ` + points.slice(1).map(p => `L ${p.x} ${p.y}`).join(' ')
    const areaPath = `${linePath} L ${points[points.length - 1].x} ${height} L ${points[0].x} ${height} Z`
    
    return { linePath, areaPath }
  }

  const cpuData = history.map(h => h.cpu)
  const memData = history.map(h => h.memory)
  const maxMemLimit = stats?.memory_limit_mb || 512

  const cpuPaths = getSvgPath(cpuData, 400, 120, 100)
  const memPaths = getSvgPath(memData, 400, 120, maxMemLimit)

  return (
    <div style={{ padding: 24, height: '100%', overflowY: 'auto' }}>
      {error && (
        <div role="alert" style={{ 
          background: 'rgba(239, 68, 68, 0.1)', 
          border: '1px solid var(--danger)', 
          borderRadius: 4, 
          padding: '10px 14px', 
          color: 'var(--danger)', 
          fontSize: 13, 
          marginBottom: 16 
        }}>
          <AlertTriangle size={13} style={{ marginRight: 6, verticalAlign: -2 }} />
          {error}
        </div>
      )}

      {loading && !stats ? (
        <div style={{ color: 'var(--mute)', fontSize: 13, display: 'flex', alignItems: 'center', gap: 8 }}>
          <RefreshCw size={16} className="spin-anim" /> Loading usage monitor...
        </div>
      ) : stats ? (
        <div style={{ display: 'flex', flexDirection: 'column', gap: 24 }}>
          {/* Top Numeric Cards */}
          <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fill, minmax(200px, 1fr))', gap: 12 }}>
            {[
              { label: 'CPU Usage', value: `${(stats.cpu_percent || 0).toFixed(1)}%`, icon: <Cpu size={16} />, color: 'var(--accent)' },
              { label: 'Memory Used', value: `${stats.memory_mb || 0} MB / ${maxMemLimit} MB`, icon: <HardDrive size={16} />, color: 'var(--accent)' },
              { label: 'Disk Space', value: `${stats.disk_mb || 0} MB`, icon: <HardDrive size={16} />, color: 'var(--warning)' },
              { label: 'Total Executions', value: `${stats.exec_count || 0}`, icon: <Terminal size={16} />, color: 'var(--danger)' },
              { label: 'Uptime', value: `${Math.floor((stats.uptime_seconds || 0) / 60)}m ${Math.floor((stats.uptime_seconds || 0) % 60)}s`, icon: <Clock size={16} />, color: 'var(--ink)' },
            ].map(s => (
              <div key={s.label} style={{ 
                background: 'var(--surface-soft)', 
                border: '1px solid var(--hairline)', 
                borderRadius: 6, 
                padding: '16px 20px',
                display: 'flex',
                alignItems: 'center',
                justifyContent: 'space-between',
                boxShadow: '0 4px 20px rgba(0,0,0,0.15)',
                backdropFilter: 'blur(10px)'
              }}>
                <div>
                  <div style={{ fontSize: 11, color: 'var(--mute)', marginBottom: 4, fontWeight: 500 }}>{s.label}</div>
                  <div style={{ fontSize: 20, fontWeight: 700, color: s.color }}>{s.value}</div>
                </div>
                <div style={{ color: 'var(--mute)', background: 'var(--surface-card)', padding: 8, borderRadius: '50%' }}>
                  {s.icon}
                </div>
              </div>
            ))}
          </div>

          {/* SVG Line Charts */}
          <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(380px, 1fr))', gap: 16 }}>
            {/* CPU Chart */}
            <div style={{ 
              background: 'var(--surface-soft)', 
              border: '1px solid var(--hairline)', 
              borderRadius: 8, 
              padding: 20,
              boxShadow: '0 4px 20px rgba(0,0,0,0.15)',
              backdropFilter: 'blur(10px)'
            }}>
              <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: 16 }}>
                <span style={{ fontSize: 13, fontWeight: 700, color: 'var(--ink)' }}>CPU History</span>
                <span style={{ fontSize: 12, color: 'var(--accent)', fontWeight: 600 }}>{(stats.cpu_percent || 0).toFixed(1)}%</span>
              </div>
              <div style={{ height: 130, width: '100%', position: 'relative' }}>
                {cpuData.length > 1 ? (
                  <svg viewBox="0 0 400 120" style={{ width: '100%', height: '100%', overflow: 'visible' }}>
                    <defs>
                      <linearGradient id="cpuGrad" x1="0" y1="0" x2="0" y2="1">
                        <stop offset="0%" stopColor="var(--accent)" stopOpacity="0.25" />
                        <stop offset="100%" stopColor="var(--accent)" stopOpacity="0" />
                      </linearGradient>
                    </defs>
                    {/* Gridlines */}
                    <line x1="0" y1="30" x2="400" y2="30" stroke="var(--hairline)" strokeDasharray="3,3" />
                    <line x1="0" y1="60" x2="400" y2="60" stroke="var(--hairline)" strokeDasharray="3,3" />
                    <line x1="0" y1="90" x2="400" y2="90" stroke="var(--hairline)" strokeDasharray="3,3" />
                    {/* Area */}
                    <path d={cpuPaths.areaPath} fill="url(#cpuGrad)" />
                    {/* Line */}
                    <path d={cpuPaths.linePath} fill="none" stroke="var(--accent)" strokeWidth="2" strokeLinecap="round" />
                  </svg>
                ) : (
                  <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'center', height: '100%', color: 'var(--mute)', fontSize: 12 }}>
                    Waiting for data points...
                  </div>
                )}
              </div>
            </div>

            {/* Memory Chart */}
            <div style={{ 
              background: 'var(--surface-soft)', 
              border: '1px solid var(--hairline)', 
              borderRadius: 8, 
              padding: 20,
              boxShadow: '0 4px 20px rgba(0,0,0,0.15)',
              backdropFilter: 'blur(10px)'
            }}>
              <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: 16 }}>
                <span style={{ fontSize: 13, fontWeight: 700, color: 'var(--ink)' }}>Memory History</span>
                <span style={{ fontSize: 12, color: 'var(--accent)', fontWeight: 600 }}>{stats.memory_mb || 0} MB</span>
              </div>
              <div style={{ height: 130, width: '100%', position: 'relative' }}>
                {memData.length > 1 ? (
                  <svg viewBox="0 0 400 120" style={{ width: '100%', height: '100%', overflow: 'visible' }}>
                    <defs>
                      <linearGradient id="memGrad" x1="0" y1="0" x2="0" y2="1">
                        <stop offset="0%" stopColor="var(--accent)" stopOpacity="0.25" />
                        <stop offset="100%" stopColor="var(--accent)" stopOpacity="0" />
                      </linearGradient>
                    </defs>
                    {/* Gridlines */}
                    <line x1="0" y1="30" x2="400" y2="30" stroke="var(--hairline)" strokeDasharray="3,3" />
                    <line x1="0" y1="60" x2="400" y2="60" stroke="var(--hairline)" strokeDasharray="3,3" />
                    <line x1="0" y1="90" x2="400" y2="90" stroke="var(--hairline)" strokeDasharray="3,3" />
                    {/* Area */}
                    <path d={memPaths.areaPath} fill="url(#memGrad)" />
                    {/* Line */}
                    <path d={memPaths.linePath} fill="none" stroke="var(--accent)" strokeWidth="2" strokeLinecap="round" />
                  </svg>
                ) : (
                  <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'center', height: '100%', color: 'var(--mute)', fontSize: 12 }}>
                    Waiting for data points...
                  </div>
                )}
              </div>
            </div>
          </div>
        </div>
      ) : (
        <div style={{ color: 'var(--mute)', fontSize: 13 }}>No statistics available.</div>
      )}
    </div>
  )
}
