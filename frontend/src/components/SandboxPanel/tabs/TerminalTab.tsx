import { useCallback, useEffect, useRef, useState } from 'react'
import { Terminal } from '@xterm/xterm'
import { FitAddon } from '@xterm/addon-fit'
import { WebLinksAddon } from '@xterm/addon-web-links'
import '@xterm/xterm/css/xterm.css'

export function TerminalTab({ sandboxId }: { sandboxId: string }) {
  const ref = useRef<HTMLDivElement>(null)
  const termRef = useRef<Terminal | null>(null)
  const wsRef = useRef<WebSocket | null>(null)
  const [status, setStatus] = useState<'connecting' | 'connected' | 'disconnected' | 'error'>('connecting')
  const [reconnectKey, setReconnectKey] = useState(0)

  const connect = useCallback((term: Terminal, fit: FitAddon) => {
    // Close existing WS
    if (wsRef.current) {
      wsRef.current.close()
      wsRef.current = null
    }

    const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:'
    const wsUrl = `${protocol}//${window.location.host}/api/sandbox/${sandboxId}/terminal`
    setStatus('connecting')

    const ws = new WebSocket(wsUrl)
    ws.binaryType = 'arraybuffer'
    wsRef.current = ws

    ws.onopen = () => {
      setStatus('connected')
      const dims = fit.proposeDimensions()
      if (dims) {
        ws.send(JSON.stringify({ type: 'resize', cols: dims.cols, rows: dims.rows }))
      }
      term.focus()
    }

    ws.onmessage = (ev) => {
      if (ev.data instanceof ArrayBuffer) {
        term.write(new Uint8Array(ev.data))
      } else if (typeof ev.data === 'string') {
        try {
          const msg = JSON.parse(ev.data)
          if (msg.type === 'error') {
            term.writeln(`\x1b[31mError: ${msg.data}\x1b[0m`)
          }
        } catch {
          term.write(ev.data)
        }
      }
    }

    ws.onclose = () => {
      setStatus('disconnected')
      term.writeln('')
      term.writeln('\x1b[90m[disconnected — click reconnect]\x1b[0m')
    }

    ws.onerror = () => {
      setStatus('error')
    }
  }, [sandboxId])

  useEffect(() => {
    if (!ref.current) return

    const term = new Terminal({
      theme: {
        background: '#1a1a1a',
        foreground: '#e5e5e5',
        cursor: '#e5e5e5',
        cursorAccent: '#1a1a1a',
        selectionBackground: '#333',
        selectionForeground: '#fff',
      },
      fontSize: 13,
      fontFamily: "'JetBrains Mono', monospace",
      cursorBlink: true,
      allowProposedApi: true,
      scrollback: 10000,
      convertEol: true,
    })

    const fit = new FitAddon()
    const webLinks = new WebLinksAddon()
    term.loadAddon(fit)
    term.loadAddon(webLinks)
    term.open(ref.current)
    fit.fit()

    termRef.current = term

    connect(term, fit)

    const onDataDisposable = term.onData((data) => {
      if (wsRef.current && wsRef.current.readyState === WebSocket.OPEN) {
        wsRef.current.send(data)
      }
    })

    const onResizeDisposable = term.onResize(({ cols, rows }) => {
      if (wsRef.current && wsRef.current.readyState === WebSocket.OPEN) {
        wsRef.current.send(JSON.stringify({ type: 'resize', cols, rows }))
      }
    })

    const handleWindowResize = () => fit.fit()
    window.addEventListener('resize', handleWindowResize)

    const resizeObserver = new ResizeObserver(() => fit.fit())
    resizeObserver.observe(ref.current)

    return () => {
      onDataDisposable.dispose()
      onResizeDisposable.dispose()
      resizeObserver.disconnect()
      window.removeEventListener('resize', handleWindowResize)
      if (wsRef.current) {
        wsRef.current.close()
        wsRef.current = null
      }
      term.dispose()
      termRef.current = null
    }
  }, [sandboxId, reconnectKey, connect])

  const handleReconnect = () => setReconnectKey(k => k + 1)

  return (
    <div style={{ height: '100%', display: 'flex', flexDirection: 'column' }}>
      <div style={{
        display: 'flex', alignItems: 'center', justifyContent: 'space-between',
        padding: '4px 12px', background: 'var(--surface-soft)', borderBottom: '1px solid var(--hairline)',
        fontSize: 11, fontFamily: 'monospace',
      }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
          <span style={{
            width: 6, height: 6, borderRadius: '50%',
            background: status === 'connected' ? 'var(--accent)' : status === 'connecting' ? '#f59e0b' : 'var(--danger)',
          }} />
          <span style={{ color: 'var(--mute)' }}>
            terminal — {status === 'connected' ? 'connected' : status === 'connecting' ? 'connecting...' : status === 'error' ? 'error' : 'disconnected'}
          </span>
        </div>
        {status !== 'connected' && (
          <button onClick={handleReconnect} style={{
            fontSize: 11, color: 'var(--accent)', background: 'none', border: 'none',
            cursor: 'pointer', fontFamily: 'inherit',
          }}>[r] reconnect</button>
        )}
      </div>
      <div ref={ref} style={{ flex: 1, background: '#1a1a1a' }} />
    </div>
  )
}
