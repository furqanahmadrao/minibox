import { useState, useEffect } from 'react'
import { api } from '../../../api/client'
import { useToastStore } from '../../../stores/toastStore'
import { GitCompare, GitCommit, AlertTriangle, RefreshCw, CheckCircle2 } from 'lucide-react'

interface Props { sandboxId: string }

export function DiffTab({ sandboxId }: Props) {
  const toast = useToastStore(s => s.add)
  const [gitStatus, setGitStatus] = useState('')
  const [gitDiff, setGitDiff] = useState('')
  const [loading, setLoading] = useState(false)
  const [committing, setCommitting] = useState(false)
  const [commitMessage, setCommitMessage] = useState('')
  const [error, setError] = useState('')

  const load = async () => {
    setLoading(true)
    setError('')
    try {
      const statusRes = await api.exec(sandboxId, 'git status')
      const diffRes = await api.exec(sandboxId, 'git diff')
      setGitStatus(statusRes.stdout || statusRes.stderr || 'No status output')
      setGitDiff(diffRes.stdout || '')
    } catch (e) {
      setError('Failed to check Git diff')
      toast('error', 'Failed to retrieve Git changes')
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => {
    load()
  }, [sandboxId])

  const handleCommit = async (e: React.FormEvent) => {
    e.preventDefault()
    if (!commitMessage.trim() || committing) return
    setCommitting(true)
    try {
      const msg = commitMessage.trim().replace(/"/g, '\\"')
      const addRes = await api.exec(sandboxId, 'git add .')
      if (addRes.exit_code !== 0) throw new Error(addRes.stderr || 'Failed to stage changes')
      
      const commitRes = await api.exec(sandboxId, `git commit -m "${msg}"`)
      if (commitRes.exit_code !== 0) throw new Error(commitRes.stderr || 'Failed to commit changes')
      
      toast('success', 'Changes committed successfully')
      setCommitMessage('')
      await load()
    } catch (err: any) {
      toast('error', err.message || 'Failed to commit changes')
    } finally {
      setCommitting(false)
    }
  }

  const hasChanges = gitDiff.trim().length > 0 || gitStatus.includes('Changes not staged') || gitStatus.includes('Untracked files')

  return (
    <div style={{ padding: 24, height: '100%', display: 'flex', flexDirection: 'column', overflowY: 'auto' }}>
      {/* Control Bar */}
      <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: 16, gap: 12 }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
          <GitCompare size={16} color="var(--accent)" />
          <span style={{ fontSize: 13, fontWeight: 700, textTransform: 'uppercase', letterSpacing: '1px', color: 'var(--mute)' }}>
            Git Workspace Diff
          </span>
        </div>
        <button onClick={load} disabled={loading} className="btn-secondary" style={{ gap: 4, height: 32, fontSize: 12 }}>
          <RefreshCw size={12} className={loading ? 'spin-anim' : ''} /> {loading ? 'Checking...' : 'Refresh'}
        </button>
      </div>

      {error && (
        <div role="alert" style={{ background: 'rgba(239, 68, 68, 0.1)', border: '1px solid var(--danger)', borderRadius: 4, padding: '10px 14px', color: 'var(--danger)', fontSize: 13, marginBottom: 16 }}>
          <AlertTriangle size={13} style={{ marginRight: 6, verticalAlign: -2 }} />
          {error}
        </div>
      )}

      {/* Main Grid: Status + Commit Form on left/top, Diff contents on right/bottom */}
      <div style={{ display: 'flex', flexDirection: 'column', gap: 16, flex: 1 }}>
        <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(300px, 1fr))', gap: 16 }}>
          {/* Status Panel */}
          <div style={{ background: 'var(--surface-soft)', border: '1px solid var(--hairline)', borderRadius: 6, padding: 16 }}>
            <div style={{ fontSize: 12, fontWeight: 700, color: 'var(--mute)', marginBottom: 8, textTransform: 'uppercase' }}>Git Status</div>
            <pre style={{ margin: 0, padding: 0, fontSize: 12, lineHeight: 1.5, fontFamily: 'var(--mono)', color: 'var(--ink)', whiteSpace: 'pre-wrap', overflowX: 'auto' }}>
              {gitStatus || 'Loading status...'}
            </pre>
          </div>

          {/* Commit Panel */}
          {hasChanges && (
            <form onSubmit={handleCommit} style={{ background: 'var(--surface-soft)', border: '1px solid var(--hairline)', borderRadius: 6, padding: 16, display: 'flex', flexDirection: 'column', gap: 10 }}>
              <div style={{ fontSize: 12, fontWeight: 700, color: 'var(--mute)', textTransform: 'uppercase' }}>Commit Changes</div>
              <input 
                className="input" 
                placeholder="Commit message..." 
                value={commitMessage} 
                onChange={e => setCommitMessage(e.target.value)} 
                disabled={committing}
                style={{ height: 32, fontSize: 12 }} 
                required
                aria-label="Commit message"
              />
              <button type="submit" className="btn-primary" disabled={committing || !commitMessage.trim()} style={{ alignSelf: 'flex-end', height: 32, fontSize: 12, gap: 6, padding: '0 16px' }}>
                <GitCommit size={14} /> {committing ? 'Committing...' : 'Commit Work'}
              </button>
            </form>
          )}
        </div>

        {/* Diff Output */}
        <div style={{ flex: 1, background: 'var(--surface-soft)', border: '1px solid var(--hairline)', borderRadius: 6, display: 'flex', flexDirection: 'column', overflow: 'hidden' }}>
          <div style={{ borderBottom: '1px solid var(--hairline)', padding: '10px 16px', fontSize: 12, fontWeight: 700, color: 'var(--mute)', textTransform: 'uppercase' }}>
            Uncommitted Changes
          </div>
          <div style={{ flex: 1, overflow: 'auto', padding: '12px 8px', background: 'var(--surface-dark-elevated)' }}>
            {gitDiff.trim() ? (
              gitDiff.split('\n').map((line, idx) => {
                let color = 'var(--ink)'
                let background = 'transparent'
                if (line.startsWith('+') && !line.startsWith('+++')) {
                  color = '#4ade80' // neon green
                  background = 'rgba(74, 222, 128, 0.05)'
                } else if (line.startsWith('-') && !line.startsWith('---')) {
                  color = '#f87171' // neon red
                  background = 'rgba(248, 113, 113, 0.05)'
                } else if (line.startsWith('@@')) {
                  color = '#38bdf8' // neon blue
                  background = 'rgba(56, 189, 248, 0.03)'
                } else if (line.startsWith('diff') || line.startsWith('index') || line.startsWith('---') || line.startsWith('+++')) {
                  color = 'var(--mute)'
                  background = 'rgba(255, 255, 255, 0.02)'
                }
                return (
                  <div key={idx} style={{ color, background, fontFamily: 'var(--mono)', fontSize: 12, lineHeight: '1.6', padding: '0 8px', whiteSpace: 'pre-wrap' }}>
                    {line}
                  </div>
                )
              })
            ) : !loading ? (
              <div style={{ display: 'flex', flexDirection: 'column', alignItems: 'center', justifyContent: 'center', height: '100%', padding: '24px 0', color: 'var(--mute)' }}>
                <CheckCircle2 size={32} color="var(--success)" strokeWidth={1.5} style={{ marginBottom: 8 }} />
                <span style={{ fontSize: 13 }}>Workspace is completely clean</span>
              </div>
            ) : (
              <div style={{ color: 'var(--ash)', fontSize: 12, padding: 8 }}>Loading diff output...</div>
            )}
          </div>
        </div>
      </div>
    </div>
  )
}
