import { useState, useRef, useEffect } from 'react'
import { useSandboxStore } from '../../stores/sandboxStore'
import { useToastStore } from '../../stores/toastStore'
import { api } from '../../api/client'
import { Plus, X } from 'lucide-react'

interface Props { onClose: () => void }

export function NewSandboxModal({ onClose }: Props) {
  const { fetch: fetchSandboxes, setActive } = useSandboxStore()
  const toast = useToastStore(s => s.add)
  const [label, setLabel] = useState('')
  const [template, setTemplate] = useState('minimal')
  const [agent, setAgent] = useState('')
  const [toolEnvVars, setToolEnvVars] = useState<{ key: string; value: string }[]>([])
  const [submitting, setSubmitting] = useState(false)
  const [error, setError] = useState('')
  const overlayRef = useRef<HTMLDivElement>(null)
  const inputRef = useRef<HTMLInputElement>(null)

  // Dynamic templates list state
  const [templates, setTemplates] = useState<Array<{ id: string; name: string }>>([])
  const [showCustomTemplateForm, setShowCustomTemplateForm] = useState(false)

  // Custom template registration state
  const [newTemplateId, setNewTemplateId] = useState('')
  const [newTemplateName, setNewTemplateName] = useState('')
  const [newTemplateDesc, setNewTemplateDesc] = useState('')
  const [newTemplatePkgs, setNewTemplatePkgs] = useState('')
  const [newTemplateEnv, setNewTemplateEnv] = useState<{ key: string; value: string }[]>([])

  const loadTemplates = async () => {
    try {
      const list = await api.listTemplates()
      setTemplates(list)
      if (list.length > 0) {
        if (!list.find(t => t.id === template)) {
          setTemplate(list[0].id)
        }
      }
    } catch {
      toast('error', 'Failed to load templates')
    }
  }

  useEffect(() => {
    loadTemplates()
  }, [])

  useEffect(() => {
    if (!showCustomTemplateForm) {
      inputRef.current?.focus()
    }
    const handleKey = (e: KeyboardEvent) => { if (e.key === 'Escape') onClose() }
    document.addEventListener('keydown', handleKey)
    return () => document.removeEventListener('keydown', handleKey)
  }, [showCustomTemplateForm])

  useEffect(() => {
    const handleKey = (e: KeyboardEvent) => {
      if (e.key !== 'Tab' || !overlayRef.current) return
      const focusable = overlayRef.current.querySelectorAll<HTMLElement>('input, button, select, [tabindex]')
      if (focusable.length === 0) return
      const first = focusable[0]
      const last = focusable[focusable.length - 1]
      if (e.shiftKey && document.activeElement === first) { e.preventDefault(); last.focus() }
      else if (!e.shiftKey && document.activeElement === last) { e.preventDefault(); first.focus() }
    }
    document.addEventListener('keydown', handleKey)
    return () => document.removeEventListener('keydown', handleKey)
  }, [])

  const handleSubmit = async () => {
    if (!label.trim()) { setError('Label is required'); return }
    setError('')
    setSubmitting(true)
    try {
      const envObject: Record<string, string> = {}
      toolEnvVars.filter(ve => ve.key.trim()).forEach(ve => { envObject[ve.key.trim()] = ve.value })
      const agentConfig: Record<string, unknown> = {}
      if (agent) agentConfig.provider = agent
      const result = await api.createSandbox({
        label: label.trim(),
        template,
        env: Object.keys(envObject).length > 0 ? envObject : undefined,
        agent_config: Object.keys(agentConfig).length > 0 ? agentConfig : undefined,
      })
      await fetchSandboxes()
      setActive(result.sandbox_id)
      toast('success', `Sandbox "${label.trim()}" created`)
      onClose()
    } catch (err) {
      const msg = err instanceof Error ? err.message : 'Failed to create sandbox'
      setError(msg)
      toast('error', msg)
    } finally { setSubmitting(false) }
  }

  const handleCreateTemplate = async () => {
    if (!newTemplateId.trim() || !newTemplateName.trim()) {
      setError('Template ID and Name are required')
      return
    }
    if (!/^[a-z0-9-]+$/.test(newTemplateId.trim())) {
      setError('Template ID must contain only lowercase letters, numbers, and dashes')
      return
    }
    setError('')
    setSubmitting(true)
    try {
      const envObj: Record<string, string> = {}
      newTemplateEnv.filter(kv => kv.key.trim()).forEach(kv => {
        envObj[kv.key.trim()] = kv.value
      })
      const packagesList = newTemplatePkgs.split(',').map(p => p.trim()).filter(Boolean)
      
      await api.registerTemplate({
        id: newTemplateId.trim(),
        name: newTemplateName.trim(),
        description: newTemplateDesc.trim(),
        packages: packagesList,
        env: envObj,
      })
      
      toast('success', `Custom template "${newTemplateName.trim()}" registered`)
      const list = await api.listTemplates()
      setTemplates(list)
      setTemplate(newTemplateId.trim())
      
      // Reset form
      setNewTemplateId('')
      setNewTemplateName('')
      setNewTemplateDesc('')
      setNewTemplatePkgs('')
      setNewTemplateEnv([])
      setShowCustomTemplateForm(false)
    } catch (err) {
      const msg = err instanceof Error ? err.message : 'Failed to register template'
      setError(msg)
      toast('error', msg)
    } finally {
      setSubmitting(false)
    }
  }

  const addToolEnvVar = () => setToolEnvVars([...toolEnvVars, { key: '', value: '' }])
  const removeToolEnvVar = (i: number) => setToolEnvVars(toolEnvVars.filter((_, idx) => idx !== i))

  if (showCustomTemplateForm) {
    return (
      <div className="confirm-overlay" onClick={() => setShowCustomTemplateForm(false)} role="dialog" aria-modal="true" aria-labelledby="template-modal-title">
        <div className="confirm-dialog" onClick={e => e.stopPropagation()} style={{ maxWidth: 520 }}>
          <h3 id="template-modal-title">Create Custom Template</h3>
          
          {error && <div role="alert" style={{ background: 'rgba(255,59,48,0.08)', border: '1px solid var(--danger)', borderRadius: 4, padding: '10px 14px', color: 'var(--danger)', fontSize: 13, marginBottom: 16 }}>{error}</div>}

          <div style={{ marginBottom: 14 }}>
            <label style={{ fontSize: 13, color: 'var(--mute)', display: 'block', marginBottom: 4 }}>Template ID * (lowercase, no spaces)</label>
            <input className="input" value={newTemplateId} onChange={e => setNewTemplateId(e.target.value)} placeholder="my-python-app" />
          </div>

          <div style={{ marginBottom: 14 }}>
            <label style={{ fontSize: 13, color: 'var(--mute)', display: 'block', marginBottom: 4 }}>Name *</label>
            <input className="input" value={newTemplateName} onChange={e => setNewTemplateName(e.target.value)} placeholder="My Python App" />
          </div>

          <div style={{ marginBottom: 14 }}>
            <label style={{ fontSize: 13, color: 'var(--mute)', display: 'block', marginBottom: 4 }}>Description</label>
            <input className="input" value={newTemplateDesc} onChange={e => setNewTemplateDesc(e.target.value)} placeholder="Custom environment for my python app" />
          </div>

          <div style={{ marginBottom: 14 }}>
            <label style={{ fontSize: 13, color: 'var(--mute)', display: 'block', marginBottom: 4 }}>Pre-installed Packages (comma-separated)</label>
            <input className="input" value={newTemplatePkgs} onChange={e => setNewTemplatePkgs(e.target.value)} placeholder="python3, python3-pip, curl" />
          </div>

          <div style={{ marginBottom: 14 }}>
            <label style={{ fontSize: 13, color: 'var(--mute)', display: 'block', marginBottom: 4 }}>Environment Variables</label>
            {newTemplateEnv.map((kv, i) => (
              <div key={i} style={{ display: 'flex', gap: 6, marginBottom: 6 }}>
                <input className="input" placeholder="KEY" value={kv.key} onChange={e => { const v = [...newTemplateEnv]; v[i].key = e.target.value; setNewTemplateEnv(v) }} style={{ flex: 1 }} aria-label="Variable key" />
                <input className="input" placeholder="value" value={kv.value} onChange={e => { const v = [...newTemplateEnv]; v[i].value = e.target.value; setNewTemplateEnv(v) }} style={{ flex: 1 }} aria-label="Variable value" />
                <button onClick={() => setNewTemplateEnv(newTemplateEnv.filter((_, idx) => idx !== i))} className="btn-icon danger btn-icon-sm" aria-label="Remove variable"><X size={14} /></button>
              </div>
            ))}
            <button onClick={() => setNewTemplateEnv([...newTemplateEnv, { key: '', value: '' }])} className="btn-ghost" style={{ height: 30, fontSize: 12, marginTop: 4, gap: 4 }}><Plus size={12} /> add variable</button>
          </div>

          <div className="confirm-actions">
            <button className="btn-secondary" onClick={() => setShowCustomTemplateForm(false)} disabled={submitting}>Cancel</button>
            <button className="btn-primary" onClick={handleCreateTemplate} disabled={submitting}>
              {submitting ? 'Creating...' : 'Create'}
            </button>
          </div>
        </div>
      </div>
    )
  }

  return (
    <div className="confirm-overlay" ref={overlayRef} onClick={onClose} role="dialog" aria-modal="true" aria-labelledby="modal-title">
      <div className="confirm-dialog" onClick={e => e.stopPropagation()} style={{ maxWidth: 520 }}>
        <h3 id="modal-title">Create New Sandbox</h3>

        {error && <div role="alert" style={{ background: 'rgba(255,59,48,0.08)', border: '1px solid var(--danger)', borderRadius: 4, padding: '10px 14px', color: 'var(--danger)', fontSize: 13, marginBottom: 16 }}>{error}</div>}

        <div style={{ marginBottom: 14 }}>
          <label style={{ fontSize: 13, color: 'var(--mute)', display: 'block', marginBottom: 4 }}>Label *</label>
          <input ref={inputRef} className="input" value={label} onChange={e => setLabel(e.target.value)} placeholder="my-sandbox" onKeyDown={e => { if (e.key === 'Enter') handleSubmit() }} aria-required="true" />
        </div>

        <div style={{ marginBottom: 14 }}>
          <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 4 }}>
            <label style={{ fontSize: 13, color: 'var(--mute)', margin: 0 }}>Template</label>
            <button onClick={() => setShowCustomTemplateForm(true)} className="btn-ghost" style={{ height: 'auto', padding: '2px 6px', fontSize: 11, color: 'var(--accent)' }}>+ custom template</button>
          </div>
          <select className="input" value={template} onChange={e => setTemplate(e.target.value)}>
            {templates.map(t => (
              <option key={t.id} value={t.id}>{t.name}</option>
            ))}
          </select>
        </div>

        <div style={{ marginBottom: 14 }}>
          <label style={{ fontSize: 13, color: 'var(--mute)', display: 'block', marginBottom: 4 }}>Agent</label>
          <select className="input" value={agent} onChange={e => setAgent(e.target.value)}>
            <option value="">none</option>
            <option value="claude-code">claude-code</option>
            <option value="codex">codex</option>
            <option value="opencode">opencode</option>
            <option value="pi">pi</option>
          </select>
        </div>

        <div style={{ marginBottom: 14 }}>
          <label style={{ fontSize: 13, color: 'var(--mute)', display: 'block', marginBottom: 4 }}>Tool Environment Variables</label>
          {toolEnvVars.map((ve, i) => (
            <div key={i} style={{ display: 'flex', gap: 6, marginBottom: 6 }}>
              <input className="input" placeholder="KEY" value={ve.key} onChange={e => { const v = [...toolEnvVars]; v[i].key = e.target.value; setToolEnvVars(v) }} style={{ flex: 1 }} aria-label="Variable key" />
              <input className="input" placeholder="value" value={ve.value} onChange={e => { const v = [...toolEnvVars]; v[i].value = e.target.value; setToolEnvVars(v) }} style={{ flex: 1 }} aria-label="Variable value" />
              <button onClick={() => removeToolEnvVar(i)} className="btn-icon danger btn-icon-sm" aria-label={`Remove ${ve.key || 'variable'}`}><X size={14} /></button>
            </div>
          ))}
          <button onClick={addToolEnvVar} className="btn-ghost" style={{ height: 30, fontSize: 12, marginTop: 4, gap: 4 }}><Plus size={12} /> add variable</button>
        </div>

        <div className="confirm-actions">
          <button className="btn-secondary" onClick={onClose} disabled={submitting}>Cancel</button>
          <button className="btn-primary" onClick={handleSubmit} disabled={submitting}>
            {submitting ? 'Creating...' : 'Create'}
          </button>
        </div>
      </div>
    </div>
  )
}
