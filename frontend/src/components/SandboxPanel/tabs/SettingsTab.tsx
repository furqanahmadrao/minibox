import { useState } from 'react'
import { Sandbox } from '../../../stores/sandboxStore'
import { useToastStore } from '../../../stores/toastStore'
import { api } from '../../../api/client'
import { Shield, AlertTriangle, Save } from 'lucide-react'

interface Props { sandbox: Sandbox }

const TABS = ['General', 'Security', 'Network'] as const
type Tab = typeof TABS[number]

export function SettingsTab({ sandbox }: Props) {
  const [tab, setTab] = useState<Tab>('General')
  const [error, setError] = useState('')

  return (
    <div style={{ padding: 24, height: '100%', overflow: 'auto' }}>
      <div style={{ borderBottom: '1px solid var(--hairline)', display: 'flex', gap: 0, marginBottom: 20 }}>
        {TABS.map(t => (
          <button key={t} onClick={() => setTab(t)} className={`tab ${tab === t ? 'tab-active' : ''}`}>{t}</button>
        ))}
      </div>

      {error && <div role="alert" style={{ background: 'rgba(255,59,48,0.08)', border: '1px solid var(--danger)', borderRadius: 4, padding: '10px 14px', color: 'var(--danger)', fontSize: 13, marginBottom: 16 }}><AlertTriangle size={13} style={{ marginRight: 6, verticalAlign: -2 }} />{error}</div>}

      {tab === 'General' && <GeneralSettings sandbox={sandbox} onError={setError} />}
      {tab === 'Security' && <SecuritySettings sandbox={sandbox} onError={setError} />}
      {tab === 'Network' && <NetworkSettings sandbox={sandbox} onError={setError} />}
    </div>
  )
}

function GeneralSettings({ sandbox, onError }: { sandbox: Sandbox; onError: (e: string) => void }) {
  const toast = useToastStore(s => s.add)
  const [label, setLabel] = useState(sandbox.label)
  const [ttl, setTtl] = useState(String(sandbox.ttl))

  const save = async () => {
    try { await api.updateSandbox(sandbox.sandbox_id, { label, ttl: parseInt(ttl) }); toast('success', 'Settings saved') }
    catch (e) { const m = e instanceof Error ? e.message : 'Failed to save'; onError(m); toast('error', m) }
  }

  return (
    <div>
      <label style={{ fontSize: 13, color: 'var(--mute)', display: 'block', marginBottom: 4 }}>Label</label>
      <input className="input" value={label} onChange={e => setLabel(e.target.value)} style={{ marginBottom: 14 }} />
      <label style={{ fontSize: 13, color: 'var(--mute)', display: 'block', marginBottom: 4 }}>TTL (seconds)</label>
      <input className="input" type="number" value={ttl} onChange={e => setTtl(e.target.value)} style={{ marginBottom: 14 }} />
      <button onClick={save} className="btn-primary" style={{ gap: 4 }}><Save size={12} /> save</button>
    </div>
  )
}

function SecuritySettings({ sandbox, onError }: { sandbox: Sandbox; onError: (e: string) => void }) {
  const toast = useToastStore(s => s.add)
  const sec = sandbox.security

  const save = async () => {
    try { await api.updateSandbox(sandbox.sandbox_id, { security: sec }); toast('success', 'Security settings saved') }
    catch (e) { const m = e instanceof Error ? e.message : 'Failed to save'; onError(m); toast('error', m) }
  }

  return (
    <div>
      <div style={{ fontSize: 13, color: 'var(--mute)', display: 'flex', alignItems: 'center', gap: 6, marginBottom: 14 }}><Shield size={13} /> Isolation: {sec?.isolation_level || 'default'}</div>
      <div style={{ fontSize: 13, marginBottom: 8 }}>Seccomp: {sec?.seccomp_profile || 'default'}</div>
      <div style={{ fontSize: 13, marginBottom: 8 }}>Max processes: {sec?.max_processes || 'unlimited'}</div>
      <div style={{ fontSize: 13, marginBottom: 14 }}>Max open files: {sec?.max_open_files || 'unlimited'}</div>
      <button onClick={save} className="btn-primary" style={{ gap: 4 }}><Save size={12} /> save</button>
    </div>
  )
}

function NetworkSettings({ sandbox, onError }: { sandbox: Sandbox; onError: (e: string) => void }) {
  const toast = useToastStore(s => s.add)
  const net = sandbox.network_config

  const save = async () => {
    try { await api.updateSandbox(sandbox.sandbox_id, { network_config: net }); toast('success', 'Network settings saved') }
    catch (e) { const m = e instanceof Error ? e.message : 'Failed to save'; onError(m); toast('error', m) }
  }

  return (
    <div>
      <div style={{ fontSize: 13, marginBottom: 8 }}>Mode: {net?.mode || sandbox.network_mode}</div>
      <div style={{ fontSize: 13, marginBottom: 8 }}>DNS filtering: {net?.dns_filtering ? 'enabled' : 'disabled'}</div>
      <div style={{ fontSize: 13, marginBottom: 8 }}>Enforce iptables: {net?.enforce_iptables ? 'yes' : 'no'}</div>
      {net?.blocked_ports && net.blocked_ports.length > 0 && <div style={{ fontSize: 13, marginBottom: 8 }}>Blocked ports: {net.blocked_ports.join(', ')}</div>}
      {net?.egress_allowlist && net.egress_allowlist.length > 0 && <div style={{ fontSize: 13, marginBottom: 14 }}>Egress allowlist: {net.egress_allowlist.join(', ')}</div>}
      <button onClick={save} className="btn-primary" style={{ gap: 4 }}><Save size={12} /> save</button>
    </div>
  )
}
