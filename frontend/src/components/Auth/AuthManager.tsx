import { useState, useEffect, useRef } from 'react'
import { api } from '../../api/client'
import { useToastStore } from '../../stores/toastStore'
import {
  ArrowLeft, Users, Key, Plus, Trash2,
  AlertTriangle, Settings, FileCode, Save, Terminal,
  Loader2, X
} from 'lucide-react'

interface Props { onClose: () => void }

type Tab = 'users' | 'keys' | 'templates' | 'configs' | 'logs'
const TABS: { id: Tab; label: string; icon: React.ReactNode }[] = [
  { id: 'users', label: 'Users', icon: <Users size={14} /> },
  { id: 'keys', label: 'API Keys', icon: <Key size={14} /> },
  { id: 'templates', label: 'Templates', icon: <FileCode size={14} /> },
  { id: 'configs', label: 'Configurations', icon: <Settings size={14} /> },
  { id: 'logs', label: 'Server Logs', icon: <Terminal size={14} /> },
]

export function AuthManager({ onClose }: Props) {
  const toast = useToastStore(s => s.add)
  const [tab, setTab] = useState<Tab>('users')
  
  // State variables
  const [users, setUsers] = useState<Array<{ username: string; role: string; created_at: number }>>([])
  const [keys, setKeys] = useState<Array<{ key: string; name: string; scopes: string[]; created_at: number; last_used?: number }>>([])
  const [audit, setAudit] = useState<Array<{ event: string; user: string; timestamp: number; details?: any }>>([])
  const [templates, setTemplates] = useState<Array<{ id: string; name: string; description: string; packages?: string[]; is_custom?: boolean; env?: Record<string, string> }>>([])
  const [configData, setConfigData] = useState<any>(null)
  
  // Creation / editing states
  const [newKeyName, setNewKeyName] = useState('')
  const [creating, setCreating] = useState(false)
  const [savingConfig, setSavingConfig] = useState(false)
  const [error, setError] = useState('')
  
  // Log stream states
  const [logLines, setLogLines] = useState<string[]>([])
  const [activeSubTab, setActiveSubTab] = useState<'console' | 'audit'>('console')
  const logsEndRef = useRef<HTMLDivElement>(null)

  // Template CRUD state
  const [editingTemplate, setEditingTemplate] = useState<any>(null)
  const [showTemplateModal, setShowTemplateModal] = useState(false)
  const [tplId, setTplId] = useState('')
  const [tplName, setTplName] = useState('')
  const [tplDesc, setTplDesc] = useState('')
  const [tplPkgs, setTplPkgs] = useState('')
  const [tplEnv, setTplEnv] = useState<{ key: string; value: string }[]>([])

  // Load functions
  const loadUsers = async () => { try { const r = await api.listUsers(); setUsers(r) } catch { toast('error', 'Failed to load users') } }
  const loadKeys = async () => { try { const r = await api.listApiKeys(); setKeys(r) } catch { toast('error', 'Failed to load API keys') } }
  const loadAudit = async () => { try { const r = await api.getAuditLog(); setAudit(r) } catch { toast('error', 'Failed to load audit log') } }
  
  const loadTemplates = async () => {
    try {
      const r = await api.listTemplates()
      setTemplates(r)
    } catch {
      toast('error', 'Failed to load templates')
    }
  }

  const loadConfig = async () => {
    try {
      const r = await api.getConfig()
      setConfigData(r)
    } catch {
      toast('error', 'Failed to load configuration')
    }
  }

  // Load active tab data
  useEffect(() => {
    setError('')
    if (tab === 'users') loadUsers()
    else if (tab === 'keys') loadKeys()
    else if (tab === 'templates') loadTemplates()
    else if (tab === 'configs') loadConfig()
    else if (tab === 'logs') loadAudit()
  }, [tab])

  // Logs WebSocket Connection
  useEffect(() => {
    if (tab !== 'logs' || activeSubTab !== 'console') return

    const wsProtocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:'
    const token = api.getToken()
    const wsUrl = `${wsProtocol}//${window.location.host}/api/admin/logs${token ? `?token=${encodeURIComponent(token)}` : ''}`
    
    let ws: WebSocket | null = null
    let active = true

    const connectLogs = () => {
      if (!active) return
      ws = new WebSocket(wsUrl)
      
      ws.onmessage = (event) => {
        if (!active) return
        setLogLines(prev => [...prev.slice(-499), event.data])
      }

      ws.onclose = () => {
        if (active) setTimeout(connectLogs, 3000)
      }
    }

    connectLogs()

    return () => {
      active = false
      if (ws) ws.close()
    }
  }, [tab, activeSubTab])

  // Scroll to bottom on raw log update
  useEffect(() => {
    if (activeSubTab === 'console') {
      logsEndRef.current?.scrollIntoView({ behavior: 'smooth' })
    }
  }, [logLines, activeSubTab])

  // API Key management
  const createKey = async () => {
    if (!newKeyName.trim()) return
    setCreating(true); setError('')
    try {
      await api.createApiKey(newKeyName.trim(), ['developer'])
      setNewKeyName('')
      await loadKeys()
      toast('success', 'API key created')
    } catch (e) {
      const m = e instanceof Error ? e.message : 'Failed to create key'
      setError(m)
      toast('error', m)
    } finally {
      setCreating(false)
    }
  }

  const deleteKey = async (key: string) => {
    try {
      await api.deleteApiKey(key)
      await loadKeys()
      toast('success', 'API key deleted')
    } catch {
      toast('error', 'Failed to delete API key')
    }
  }

  // Config Update Action
  const saveConfig = async () => {
    setSavingConfig(true)
    setError('')
    try {
      const updates = {
        sandbox: {
          default_ttl: parseInt(configData.sandbox.default_ttl),
          max_concurrent: parseInt(configData.sandbox.max_concurrent),
          default_cpu_cores: parseFloat(configData.sandbox.default_cpu_cores),
          default_memory_mb: parseInt(configData.sandbox.default_memory_mb),
          default_isolation_level: configData.sandbox.default_isolation_level,
          git_username: configData.sandbox.git_username,
          git_email: configData.sandbox.git_email,
        },
        security: {
          rate_limit_rpm: parseInt(configData.security.rate_limit_rpm),
        },
        network: {
          default_mode: configData.network.default_mode,
          dns_servers: typeof configData.network.dns_servers === 'string'
            ? configData.network.dns_servers.split(',').map((s: string) => s.trim()).filter(Boolean)
            : configData.network.dns_servers,
        }
      }
      await api.updateConfig(updates)
      toast('success', 'Server configurations saved successfully')
    } catch (e) {
      const m = e instanceof Error ? e.message : 'Failed to save configurations'
      setError(m)
      toast('error', m)
    } finally {
      setSavingConfig(false)
    }
  }

  // Open template CRUD modal
  const openTemplateModal = (tpl?: any) => {
    setError('')
    if (tpl) {
      setEditingTemplate(tpl)
      setTplId(tpl.id)
      setTplName(tpl.name)
      setTplDesc(tpl.description || '')
      setTplPkgs(tpl.packages ? tpl.packages.join(', ') : '')
      const envArr = tpl.env ? Object.entries(tpl.env).map(([k, v]) => ({ key: k, value: String(v) })) : []
      setTplEnv(envArr)
    } else {
      setEditingTemplate(null)
      setTplId('')
      setTplName('')
      setTplDesc('')
      setTplPkgs('')
      setTplEnv([])
    }
    setShowTemplateModal(true)
  }

  // Save/Update template
  const saveTemplate = async () => {
    if (!tplId.trim() || !tplName.trim()) {
      setError('Template ID and Name are required')
      return
    }
    setError('')
    try {
      const envObj: Record<string, string> = {}
      tplEnv.filter(kv => kv.key.trim()).forEach(kv => { envObj[kv.key.trim()] = kv.value })
      const packagesList = tplPkgs.split(',').map(p => p.trim()).filter(Boolean)
      
      const payload = {
        id: tplId.trim(),
        name: tplName.trim(),
        description: tplDesc.trim(),
        packages: packagesList,
        env: envObj,
      }

      if (editingTemplate) {
        await api.updateTemplate(tplId, payload)
        toast('success', 'Custom template updated')
      } else {
        await api.registerTemplate(payload)
        toast('success', 'Custom template created')
      }
      
      setShowTemplateModal(false)
      loadTemplates()
    } catch (e) {
      const m = e instanceof Error ? e.message : 'Failed to save template'
      setError(m)
      toast('error', m)
    }
  }

  // Delete Custom Template
  const deleteTemplate = async (id: string) => {
    try {
      await api.deleteTemplate(id)
      toast('success', 'Custom template deleted')
      loadTemplates()
    } catch {
      toast('error', 'Failed to delete template')
    }
  }

  return (
    <div style={{ minHeight: '100vh', background: 'var(--canvas)', padding: '24px 32px', maxWidth: 960, margin: '0 auto', display: 'flex', flexDirection: 'column' }}>
      <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: 16 }}>
        <button onClick={onClose} className="btn-ghost" style={{ gap: 4, fontSize: 13 }}><ArrowLeft size={14} /> back to dashboard</button>
        <span style={{ fontSize: 11, color: 'var(--ash)' }}>Minibox Control Panel</span>
      </div>
      <h2 style={{ fontSize: 18, fontWeight: 700, marginBottom: 20, display: 'flex', alignItems: 'center', gap: 8 }}><Settings size={18} /> Server Settings Manager</h2>

      <div role="tablist" style={{ display: 'flex', gap: 0, borderBottom: '1px solid var(--hairline)', marginBottom: 20 }}>
        {TABS.map(t => (
          <button key={t.id} role="tab" aria-selected={tab === t.id} onClick={() => setTab(t.id)} className={`tab ${tab === t.id ? 'tab-active' : ''}`} style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
            {t.icon} {t.label}
          </button>
        ))}
      </div>

      {error && <div role="alert" style={{ background: 'rgba(255,59,48,0.08)', border: '1px solid var(--danger)', borderRadius: 4, padding: '10px 14px', color: 'var(--danger)', fontSize: 13, marginBottom: 16 }}><AlertTriangle size={13} style={{ marginRight: 6, verticalAlign: -2 }} />{error}</div>}

      {/* Users Tab */}
      {tab === 'users' && (
        <div>
          <div style={{ fontSize: 13, color: 'var(--mute)', marginBottom: 12 }}>Registered users: {users.length}</div>
          {users.map(u => (
            <div key={u.username} style={{ display: 'flex', alignItems: 'center', gap: 12, padding: '10px 14px', background: 'var(--surface-soft)', border: '1px solid var(--hairline)', borderRadius: 4, marginBottom: 6 }}>
              <span style={{ fontWeight: 700 }}>{u.username}</span>
              <span className="badge badge-accent">{u.role}</span>
              <span style={{ color: 'var(--ash)', fontSize: 12, flex: 1 }}>{new Date(u.created_at * 1000).toLocaleDateString()}</span>
            </div>
          ))}
        </div>
      )}

      {/* API Keys Tab */}
      {tab === 'keys' && (
        <div>
          <div style={{ display: 'flex', gap: 8, marginBottom: 16 }}>
            <input className="input" placeholder="key name" value={newKeyName} onChange={e => setNewKeyName(e.target.value)} onKeyDown={e => { if (e.key === 'Enter') createKey() }} aria-label="API key name" />
            <button onClick={createKey} disabled={creating || !newKeyName.trim()} className="btn-primary" style={{ gap: 4 }}><Plus size={12} /> {creating ? 'creating...' : 'create key'}</button>
          </div>
          {keys.map(k => (
            <div key={k.key} style={{ display: 'flex', alignItems: 'center', gap: 12, padding: '10px 14px', background: 'var(--surface-soft)', border: '1px solid var(--hairline)', borderRadius: 4, marginBottom: 6 }}>
              <span style={{ fontWeight: 700 }}>{k.name}</span>
              <span className="mono" style={{ fontSize: 12, color: 'var(--ash)' }}>{k.key.slice(0, 12)}...</span>
              <span style={{ fontSize: 12, color: 'var(--ash)' }}>{new Date(k.created_at * 1000).toLocaleDateString()}</span>
              <div style={{ flex: 1 }} />
              <button onClick={() => deleteKey(k.key)} className="btn-icon danger" aria-label={`Delete API key ${k.name}`}><Trash2 size={14} /></button>
            </div>
          ))}
        </div>
      )}

      {/* Templates Management Tab */}
      {tab === 'templates' && (
        <div>
          <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 16 }}>
            <div style={{ fontSize: 13, color: 'var(--mute)' }}>Installed templates: {templates.length}</div>
            <button onClick={() => openTemplateModal()} className="btn-primary btn-sm" style={{ gap: 4 }}><Plus size={12} /> Add Custom Template</button>
          </div>

          <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fill, minmax(280px, 1fr))', gap: 12 }}>
            {templates.map(t => (
              <div key={t.id} style={{ background: 'var(--surface-soft)', border: '1px solid var(--hairline)', padding: '14px 18px', borderRadius: 4, display: 'flex', flexDirection: 'column', minHeight: 120 }}>
                <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start', marginBottom: 6 }}>
                  <span style={{ fontWeight: 700, fontSize: 14 }}>{t.name}</span>
                  <span className={`badge ${t.is_custom ? 'badge-accent' : 'badge-dark'}`}>{t.is_custom ? 'custom' : 'builtin'}</span>
                </div>
                <p style={{ fontSize: 12, color: 'var(--ash)', flex: 1, margin: '0 0 12px 0', lineHeight: 1.4 }}>{t.description}</p>
                {t.packages && t.packages.length > 0 && (
                  <div style={{ fontSize: 11, color: 'var(--mute)', marginBottom: 12, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
                    <strong>Pkgs:</strong> {t.packages.join(', ')}
                  </div>
                )}
                {t.is_custom && (
                  <div style={{ display: 'flex', gap: 8, alignSelf: 'flex-end' }}>
                    <button onClick={() => openTemplateModal(t)} className="btn-ghost btn-sm" style={{ fontSize: 11, padding: '2px 8px', height: 24 }}>edit</button>
                    <button onClick={() => deleteTemplate(t.id)} className="btn-ghost btn-sm" style={{ fontSize: 11, padding: '2px 8px', height: 24, color: 'var(--danger)' }}>delete</button>
                  </div>
                )}
              </div>
            ))}
          </div>
        </div>
      )}

      {/* Global Configurations Tab */}
      {tab === 'configs' && configData && (
        <div style={{ display: 'flex', flexDirection: 'column', gap: 20 }}>
          {/* General settings */}
          <div style={{ background: 'var(--surface-soft)', border: '1px solid var(--hairline)', padding: 18, borderRadius: 4 }}>
            <h3 style={{ fontSize: 14, fontWeight: 700, marginBottom: 12, color: 'var(--accent)' }}>General Defaults</h3>
            <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 12 }}>
              <div>
                <label style={{ fontSize: 12, color: 'var(--mute)', display: 'block', marginBottom: 4 }}>Default Sandbox TTL (seconds)</label>
                <input className="input" type="number" value={configData.sandbox.default_ttl} onChange={e => { const d = { ...configData }; d.sandbox.default_ttl = e.target.value; setConfigData(d) }} />
              </div>
              <div>
                <label style={{ fontSize: 12, color: 'var(--mute)', display: 'block', marginBottom: 4 }}>Max Concurrent Sandboxes</label>
                <input className="input" type="number" value={configData.sandbox.max_concurrent} onChange={e => { const d = { ...configData }; d.sandbox.max_concurrent = e.target.value; setConfigData(d) }} />
              </div>
              <div>
                <label style={{ fontSize: 12, color: 'var(--mute)', display: 'block', marginBottom: 4 }}>Default CPU Cores</label>
                <input className="input" type="number" step="0.5" value={configData.sandbox.default_cpu_cores} onChange={e => { const d = { ...configData }; d.sandbox.default_cpu_cores = e.target.value; setConfigData(d) }} />
              </div>
              <div>
                <label style={{ fontSize: 12, color: 'var(--mute)', display: 'block', marginBottom: 4 }}>Default Memory (MB)</label>
                <input className="input" type="number" value={configData.sandbox.default_memory_mb} onChange={e => { const d = { ...configData }; d.sandbox.default_memory_mb = e.target.value; setConfigData(d) }} />
              </div>
              <div>
                <label style={{ fontSize: 12, color: 'var(--mute)', display: 'block', marginBottom: 4 }}>Git Config Username</label>
                <input className="input" value={configData.sandbox.git_username} onChange={e => { const d = { ...configData }; d.sandbox.git_username = e.target.value; setConfigData(d) }} />
              </div>
              <div>
                <label style={{ fontSize: 12, color: 'var(--mute)', display: 'block', marginBottom: 4 }}>Git Config Email</label>
                <input className="input" value={configData.sandbox.git_email} onChange={e => { const d = { ...configData }; d.sandbox.git_email = e.target.value; setConfigData(d) }} />
              </div>
            </div>
          </div>

          {/* Security configs */}
          <div style={{ background: 'var(--surface-soft)', border: '1px solid var(--hairline)', padding: 18, borderRadius: 4 }}>
            <h3 style={{ fontSize: 14, fontWeight: 700, marginBottom: 12, color: 'var(--accent)' }}>Security & Protection</h3>
            <div>
              <label style={{ fontSize: 12, color: 'var(--mute)', display: 'block', marginBottom: 4 }}>Global API Rate Limit (Requests per minute)</label>
              <input className="input" type="number" value={configData.security.rate_limit_rpm} onChange={e => { const d = { ...configData }; d.security.rate_limit_rpm = e.target.value; setConfigData(d) }} style={{ maxWidth: '50%' }} />
            </div>
          </div>

          {/* Network configs */}
          <div style={{ background: 'var(--surface-soft)', border: '1px solid var(--hairline)', padding: 18, borderRadius: 4 }}>
            <h3 style={{ fontSize: 14, fontWeight: 700, marginBottom: 12, color: 'var(--accent)' }}>Networking Defaults</h3>
            <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 12 }}>
              <div>
                <label style={{ fontSize: 12, color: 'var(--mute)', display: 'block', marginBottom: 4 }}>Network Mode</label>
                <select className="input" value={configData.network.default_mode} onChange={e => { const d = { ...configData }; d.network.default_mode = e.target.value; setConfigData(d) }}>
                  <option value="isolated">isolated (no egress)</option>
                  <option value="egress-only">egress-only (proxied)</option>
                  <option value="full">full (unrestricted)</option>
                </select>
              </div>
              <div>
                <label style={{ fontSize: 12, color: 'var(--mute)', display: 'block', marginBottom: 4 }}>DNS Servers (comma-separated)</label>
                <input className="input" value={configData.network.dns_servers} onChange={e => { const d = { ...configData }; d.network.dns_servers = e.target.value; setConfigData(d) }} />
              </div>
            </div>
          </div>

          <button onClick={saveConfig} disabled={savingConfig} className="btn-primary" style={{ gap: 6, alignSelf: 'flex-start' }}>
            {savingConfig ? <Loader2 size={14} className="animate-spin" /> : <Save size={14} />}
            {savingConfig ? 'Saving...' : 'Save Configurations'}
          </button>
        </div>
      )}

      {/* Logs and Audits Tab */}
      {tab === 'logs' && (
        <div style={{ flex: 1, display: 'flex', flexDirection: 'column', minHeight: 400 }}>
          <div style={{ display: 'flex', gap: 8, marginBottom: 14, borderBottom: '1px solid var(--hairline)' }}>
            <button onClick={() => setActiveSubTab('console')} className={`btn-ghost btn-sm`} style={{ borderBottom: activeSubTab === 'console' ? '2px solid var(--accent)' : 'none', borderRadius: 0, height: 32 }}>Raw Console Logs</button>
            <button onClick={() => setActiveSubTab('audit')} className={`btn-ghost btn-sm`} style={{ borderBottom: activeSubTab === 'audit' ? '2px solid var(--accent)' : 'none', borderRadius: 0, height: 32 }}>System Audit timeline</button>
          </div>

          {activeSubTab === 'console' && (
            <div style={{ flex: 1, background: '#0a0a0c', border: '1px solid var(--hairline)', borderRadius: 4, padding: 14, fontFamily: 'monospace', fontSize: 12, overflow: 'auto', maxHeight: 450, color: '#f1f1f1', whiteSpace: 'pre-wrap', lineHeight: 1.5 }}>
              {logLines.length === 0 && <div style={{ color: 'var(--ash)' }}>No console output recorded yet...</div>}
              {logLines.map((line, idx) => (
                <div key={idx}>{line}</div>
              ))}
              <div ref={logsEndRef} />
            </div>
          )}

          {activeSubTab === 'audit' && (
            <div>
              {audit.length === 0 && <div style={{ color: 'var(--ash)', fontSize: 13 }}>No audit logs recorded.</div>}
              {audit.map((a, i) => (
                <div key={i} style={{ padding: '10px 14px', background: 'var(--surface-soft)', border: '1px solid var(--hairline)', borderRadius: 4, marginBottom: 6 }}>
                  <div style={{ display: 'flex', gap: 12, alignItems: 'center' }}>
                    <span className="badge badge-dark">{a.event}</span>
                    <span style={{ fontSize: 12 }}>{a.user || 'system'}</span>
                    <span style={{ fontSize: 12, color: 'var(--ash)' }}>{new Date(a.timestamp * 1000).toLocaleString()}</span>
                  </div>
                  {a.details && <div style={{ fontSize: 12, marginTop: 4, color: 'var(--mute)' }}>{JSON.stringify(a.details)}</div>}
                </div>
              ))}
            </div>
          )}
        </div>
      )}

      {/* Templates CRUD Modal */}
      {showTemplateModal && (
        <div className="confirm-overlay" onClick={() => setShowTemplateModal(false)} role="dialog" aria-modal="true" aria-labelledby="tpl-modal-title">
          <div className="confirm-dialog" onClick={e => e.stopPropagation()} style={{ maxWidth: 520 }}>
            <h3 id="tpl-modal-title">{editingTemplate ? 'Edit Custom Template' : 'Create Custom Template'}</h3>

            <div style={{ marginBottom: 14 }}>
              <label style={{ fontSize: 12, color: 'var(--mute)', display: 'block', marginBottom: 4 }}>Template ID *</label>
              <input className="input" value={tplId} onChange={e => setTplId(e.target.value)} disabled={editingTemplate !== null} placeholder="e.g. python-data-app" />
            </div>

            <div style={{ marginBottom: 14 }}>
              <label style={{ fontSize: 12, color: 'var(--mute)', display: 'block', marginBottom: 4 }}>Name *</label>
              <input className="input" value={tplName} onChange={e => setTplName(e.target.value)} placeholder="e.g. Python Data App" />
            </div>

            <div style={{ marginBottom: 14 }}>
              <label style={{ fontSize: 12, color: 'var(--mute)', display: 'block', marginBottom: 4 }}>Description</label>
              <input className="input" value={tplDesc} onChange={e => setTplDesc(e.target.value)} placeholder="Template description..." />
            </div>

            <div style={{ marginBottom: 14 }}>
              <label style={{ fontSize: 12, color: 'var(--mute)', display: 'block', marginBottom: 4 }}>Packages (comma-separated)</label>
              <input className="input" value={tplPkgs} onChange={e => setTplPkgs(e.target.value)} placeholder="e.g. python3, git, curl" />
            </div>

            <div style={{ marginBottom: 14 }}>
              <label style={{ fontSize: 12, color: 'var(--mute)', display: 'block', marginBottom: 4 }}>Environment Variables</label>
              {tplEnv.map((kv, i) => (
                <div key={i} style={{ display: 'flex', gap: 6, marginBottom: 6 }}>
                  <input className="input" placeholder="KEY" value={kv.key} onChange={e => { const v = [...tplEnv]; v[i].key = e.target.value; setTplEnv(v) }} style={{ flex: 1 }} />
                  <input className="input" placeholder="value" value={kv.value} onChange={e => { const v = [...tplEnv]; v[i].value = e.target.value; setTplEnv(v) }} style={{ flex: 1 }} />
                  <button onClick={() => setTplEnv(tplEnv.filter((_, idx) => idx !== i))} className="btn-icon danger btn-icon-sm"><X size={14} /></button>
                </div>
              ))}
              <button onClick={() => setTplEnv([...tplEnv, { key: '', value: '' }])} className="btn-ghost" style={{ height: 30, fontSize: 12, marginTop: 4, gap: 4 }}><Plus size={12} /> add variable</button>
            </div>

            <div className="confirm-actions">
              <button className="btn-secondary" onClick={() => setShowTemplateModal(false)}>Cancel</button>
              <button className="btn-primary" onClick={saveTemplate}>Save</button>
            </div>
          </div>
        </div>
      )}
    </div>
  )
}
