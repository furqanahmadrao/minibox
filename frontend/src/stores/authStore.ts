import { create } from 'zustand'

export interface AuthStatus {
  auth_enabled: boolean
  has_users: boolean
  has_env_credentials: boolean
  has_api_key: boolean
  needs_setup: boolean
}

interface AuthState {
  token: string | null
  initializing: boolean
  authStatus: AuthStatus | null
  login: (u: string, p: string) => Promise<void>
  logout: () => void
  init: () => Promise<void>
  setup: (u: string, p: string) => Promise<void>
}

export const useAuthStore = create<AuthState>((set, get) => ({
  token: null,
  initializing: true,
  authStatus: null,

  login: async (u, p) => {
    const { api } = await import('../api/client')
    await api.login(u, p)
    set({ token: api.getToken() })
  },

  logout: () => {
    localStorage.removeItem('minibox_token')
    import('../api/client').then(({ api }) => api.setToken(null))
    set({ token: null })
  },

  init: async () => {
    const { api } = await import('../api/client')

    // 1) Fetch backend auth status
    let status: AuthStatus | null = null
    try {
      const res = await fetch(`${window.location.origin}/api/auth/status`)
      if (res.ok) status = await res.json()
    } catch {
      // Status endpoint unreachable — assume auth disabled
    }
    set({ authStatus: status })

    // 2) If backend says auth is disabled, skip login entirely
    if (status && !status.auth_enabled) {
      api.setToken('no-auth')
      set({ token: 'no-auth', initializing: false })
      return
    }

    // 3) If backend says needs setup, show setup screen (no token yet)
    if (status?.needs_setup) {
      set({ initializing: false })
      return
    }

    // 4) Otherwise, try to restore existing token from localStorage
    const t = localStorage.getItem('minibox_token')
    if (t) {
      api.setToken(t)
      set({ token: t, initializing: false })
    } else {
      set({ initializing: false })
    }
  },

  setup: async (u, p) => {
    const { api } = await import('../api/client')
    await api.setup(u, p)
    // Auto-login after setup
    await get().login(u, p)
  },
}))
