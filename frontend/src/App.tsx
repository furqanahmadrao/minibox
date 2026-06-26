import { useEffect, useState } from 'react'
import { useAuthStore } from './stores/authStore'
import { useSandboxStore } from './stores/sandboxStore'
import { LoginScreen } from './components/Auth/LoginScreen'
import { SetupScreen } from './components/Auth/SetupScreen'
import { Dashboard } from './components/Dashboard/Dashboard'
import { SandboxPanel } from './components/SandboxPanel/SandboxPanel'
import { ToastContainer } from './components/ToastContainer'

export default function App() {
  const { token, initializing, init, authStatus } = useAuthStore()
  const { view } = useSandboxStore()
  const [showSetup, setShowSetup] = useState(false)

  useEffect(() => { init() }, [init])

  if (initializing) {
    return (
      <div style={{ minHeight: '100vh', display: 'flex', alignItems: 'center', justifyContent: 'center', background: 'var(--canvas)' }}>
        <div style={{ textAlign: 'center' }}>
          <div className="spinner" style={{ width: 24, height: 24, marginBottom: 12 }} />
          <div style={{ fontSize: 13, color: 'var(--mute)' }}>loading...</div>
        </div>
      </div>
    )
  }

  // Auth disabled by backend — go straight to dashboard
  if (token === 'no-auth') {
    return (
      <>
        {view === 'dashboard' ? <Dashboard /> : <SandboxPanel />}
        <ToastContainer />
      </>
    )
  }

  // First-time setup — no users, no env creds, no API key
  if (showSetup || (authStatus?.needs_setup && !token)) {
    return (
      <>
        <SetupScreen onDone={() => setShowSetup(false)} />
        <ToastContainer />
      </>
    )
  }

  // Not logged in — show login
  if (!token) {
    return (
      <>
        <LoginScreen
          onSetup={() => setShowSetup(true)}
          needsSetup={!!authStatus?.needs_setup}
        />
        <ToastContainer />
      </>
    )
  }

  // Logged in
  return (
    <>
      {view === 'dashboard' ? <Dashboard /> : <SandboxPanel />}
      <ToastContainer />
    </>
  )
}
