import React from 'react'
import { AlertTriangle, Copy, RefreshCw } from 'lucide-react'

interface Props { children: React.ReactNode }

interface State { error: Error | null; errorInfo: React.ErrorInfo | null }

export class ErrorBoundary extends React.Component<Props, State> {
  constructor(props: Props) {
    super(props)
    this.state = { error: null, errorInfo: null }
  }

  static getDerivedStateFromError(error: Error) { return { error } }

  componentDidCatch(_error: Error, errorInfo: React.ErrorInfo) { this.setState({ errorInfo }) }

  copyError = () => {
    const { error, errorInfo } = this.state
    const text = `${error?.message}\n\n${errorInfo?.componentStack || ''}`
    navigator.clipboard.writeText(text)
  }

  render() {
    if (this.state.error) {
      return (
        <div style={{ padding: 32, background: 'var(--canvas)', minHeight: '100vh', display: 'flex', alignItems: 'center', justifyContent: 'center' }}>
          <div style={{ maxWidth: 500, width: '100%', background: 'var(--surface-soft)', border: '1px solid var(--hairline)', borderRadius: 4, padding: 32 }} role="alert">
            <div style={{ display: 'flex', alignItems: 'center', gap: 10, marginBottom: 16, color: 'var(--danger)' }}>
              <AlertTriangle size={20} />
              <span style={{ fontWeight: 700, fontSize: 16 }}>Something went wrong</span>
            </div>
            <p style={{ fontSize: 14, marginBottom: 8 }}>{this.state.error.message}</p>
            <pre style={{ fontSize: 11, lineHeight: 1.6, background: 'var(--surface-card)', border: '1px solid var(--hairline)', borderRadius: 4, padding: 12, overflow: 'auto', fontFamily: 'var(--mono)', marginBottom: 16, maxHeight: 200 }}>
              {this.state.errorInfo?.componentStack}
            </pre>
            <div style={{ display: 'flex', gap: 8 }}>
              <button onClick={this.copyError} className="btn-secondary" style={{ gap: 4 }}><Copy size={12} /> copy error</button>
              <button onClick={() => window.location.reload()} className="btn-primary" style={{ gap: 4 }}><RefreshCw size={12} /> reload page</button>
            </div>
          </div>
        </div>
      )
    }
    return this.props.children
  }
}
