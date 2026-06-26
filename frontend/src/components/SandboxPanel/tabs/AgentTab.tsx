import { useState, useEffect } from 'react'
import { Sandbox } from '../../../stores/sandboxStore'
import { api } from '../../../api/client'
import { Bot, Send, AlertTriangle, Loader2 } from 'lucide-react'

interface Props { sandbox: Sandbox }

export function AgentTab({ sandbox }: Props) {
  const [input, setInput] = useState('')
  const [messages, setMessages] = useState<Array<{ role: string; content: string }>>([])
  const [sending, setSending] = useState(false)
  const [error, setError] = useState('')
  const [ws, setWs] = useState<WebSocket | null>(null)
  const [wsConnected, setWsConnected] = useState(false)
  const [isInitializing, setIsInitializing] = useState(false)

  const provider = sandbox.agent_config?.provider

  useEffect(() => {
    if (!provider) return

    let socket: WebSocket | null = null
    let active = true

    const connect = () => {
      if (!active) return
      setError('')
      setIsInitializing(true)
      
      const wsProtocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:'
      const token = api.getToken()
      const wsUrl = `${wsProtocol}//${window.location.host}/api/sandbox/${sandbox.sandbox_id}/acp/ws${token ? `?token=${encodeURIComponent(token)}` : ''}`
      
      socket = new WebSocket(wsUrl)
      
      socket.onopen = () => {
        if (!active) return
        setWsConnected(true)
        setIsInitializing(false)
        socket?.send(JSON.stringify({
          type: 'start',
          agent_type: provider,
          api_key: sandbox.agent_config?.api_key || '',
          base_url: sandbox.agent_config?.base_url || '',
          model: sandbox.agent_config?.model || '',
          cwd: '/'
        }))
      }
      
      socket.onmessage = (event) => {
        if (!active) return
        try {
          const msg = JSON.parse(event.data)
          if (msg.type === 'started') {
            // Agent started successfully
          } else if (msg.type === 'update') {
            const update = msg.data
            const type = update.type
            const params = update.data
            
            let textContent = ''
            if (type === 'session/output' && params?.content) {
              textContent = params.content
            } else if (type === 'session/stdout' && params?.content) {
              textContent = params.content
            } else if (type === 'session/stderr' && params?.content) {
              textContent = params.content
            } else if (type === 'session/log' && params?.message) {
              textContent = params.message + '\n'
            } else if (params && typeof params === 'object') {
              textContent = params.content || params.output || params.text || params.message || ''
            } else if (typeof params === 'string') {
              textContent = params
            }
            
            if (textContent) {
              setMessages(prev => {
                const last = prev[prev.length - 1]
                if (last && last.role === 'assistant') {
                  return [...prev.slice(0, -1), { role: 'assistant', content: last.content + textContent }]
                } else {
                  return [...prev, { role: 'assistant', content: textContent }]
                }
              })
            }
          } else if (msg.type === 'done') {
            setSending(false)
          } else if (msg.type === 'error') {
            setError(msg.data)
            setSending(false)
          }
        } catch (e) {
          // Ignore
        }
      }
      
      socket.onerror = () => {
        if (!active) return
        setError('WebSocket error connecting to agent')
        setIsInitializing(false)
        setWsConnected(false)
      }
      
      socket.onclose = () => {
        if (!active) return
        setWsConnected(false)
        setIsInitializing(false)
        setSending(false)
        // Try reconnecting in 5s
        setTimeout(connect, 5000)
      }
      
      setWs(socket)
    }

    connect()

    return () => {
      active = false
      if (socket) {
        socket.close()
      }
    }
  }, [sandbox.sandbox_id, provider])

  if (!provider) {
    return (
      <div style={{ padding: 24, display: 'flex', alignItems: 'center', gap: 8, color: 'var(--mute)', fontSize: 13 }}>
        <Bot size={14} /> No agent configured. Add an agent in sandbox creation or Settings.
      </div>
    )
  }

  const send = () => {
    if (!input.trim() || sending || !ws || !wsConnected) return
    const msg = input.trim()
    setInput('')
    setMessages(prev => [...prev, { role: 'user', content: msg }])
    setSending(true)
    setError('')
    
    // Add empty assistant response to stream into
    setMessages(prev => [...prev, { role: 'assistant', content: '' }])

    ws.send(JSON.stringify({
      type: 'prompt',
      prompt: msg
    }))
  }

  return (
    <div style={{ padding: 24, height: '100%', display: 'flex', flexDirection: 'column' }}>
      <div style={{ marginBottom: 12, fontSize: 13, display: 'flex', alignItems: 'center', justifyContent: 'space-between' }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
          <Bot size={14} /> Agent: <span className="badge badge-accent">{provider}</span>
        </div>
        <div style={{ display: 'flex', alignItems: 'center', gap: 6, fontSize: 11, color: wsConnected ? 'var(--success)' : 'var(--warning)' }}>
          {isInitializing ? (
            <Loader2 size={12} className="animate-spin" />
          ) : (
            <span style={{ width: 6, height: 6, borderRadius: '50%', background: wsConnected ? 'var(--success)' : 'var(--warning)' }} />
          )}
          {isInitializing ? 'Connecting...' : wsConnected ? 'Connected' : 'Disconnected (reconnecting...)'}
        </div>
      </div>

      {error && (
        <div role="alert" style={{ background: 'rgba(255,59,48,0.08)', border: '1px solid var(--danger)', borderRadius: 4, padding: '10px 14px', color: 'var(--danger)', fontSize: 13, marginBottom: 12 }}>
          <AlertTriangle size={13} style={{ marginRight: 6, verticalAlign: -2 }} />
          {error}
        </div>
      )}

      <div style={{ flex: 1, overflow: 'auto', marginBottom: 12 }}>
        {messages.length === 0 && <div style={{ color: 'var(--ash)', fontSize: 13 }}>Send a message to start a conversation with the agent.</div>}
        {messages.map((m, i) => (
          <div key={i} style={{ marginBottom: 10, padding: '10px 14px', background: m.role === 'user' ? 'var(--surface-soft)' : 'var(--surface-card)', borderRadius: 4, fontSize: 13, lineHeight: 1.6, whiteSpace: 'pre-wrap' }}>
            <div style={{ fontSize: 11, color: 'var(--ash)', marginBottom: 4, fontWeight: 700 }}>{m.role === 'user' ? 'You' : provider}</div>
            {m.content || (sending && i === messages.length - 1 ? 'Agent is thinking...' : '(no response)')}
          </div>
        ))}
      </div>

      <div style={{ display: 'flex', gap: 8 }}>
        <input className="input" value={input} onChange={e => setInput(e.target.value)} onKeyDown={e => { if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); send() } }} placeholder={wsConnected ? "Message agent..." : "Connecting to agent..."} style={{ flex: 1 }} disabled={sending || !wsConnected} aria-label="Agent message" />
        <button onClick={send} disabled={sending || !input.trim() || !wsConnected} className="btn-primary" style={{ gap: 4 }}><Send size={12} /> send</button>
      </div>
    </div>
  )
}
