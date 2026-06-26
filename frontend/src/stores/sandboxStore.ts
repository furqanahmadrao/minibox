import { create } from 'zustand'
import { api } from '../api/client'

export interface AgentConfig {
  provider: string
  base_url: string
  api_key: string
  model: string
  mode: string
  prompt: string
  extra: Record<string, string>
  mcp_servers: Record<string, any>
  instructions: string
  skills: string[]
}

export interface SandboxSecurityConfig {
  isolation_level: string
  symlink_policy: string
  read_only_rootfs: boolean
  max_processes: number
  max_open_files: number
  mask_paths: string[]
  readonly_paths: string[]
  seccomp_profile: string
  blocked_syscalls: string[]
}

export interface SandboxNetworkConfig {
  mode: string
  egress_allowlist: string[]
  dns_filtering: boolean
  dns_servers: string[]
  blocked_ports: number[]
  enforce_iptables: boolean
}

export interface Sandbox {
  sandbox_id: string
  status: string
  template: string
  label: string
  ttl: number
  cpu_cores: number
  memory_mb: number
  network_mode: string
  egress_allowlist: string[]
  env: Record<string, string>
  exec_count: number
  ttl_remaining: number
  agent_config: AgentConfig
  created_at: number
  port_forwards: any[]
  security?: SandboxSecurityConfig
  network_config?: SandboxNetworkConfig
  pid?: number
}

interface SandboxState {
  sandboxes: Sandbox[]
  activeId: string | null
  view: 'dashboard' | 'sandbox'
  error: string | null
  fetch: () => Promise<void>
  create: (opts: any) => Promise<string>
  setActive: (id: string) => void
  openDashboard: () => void
  destroy: (id: string) => Promise<void>
}

export const useSandboxStore = create<SandboxState>((set, get) => ({
  sandboxes: [],
  activeId: null,
  view: 'dashboard',
  error: null,

  fetch: async () => {
    set({ error: null })
    try {
      const sandboxes = await api.listSandboxes()
      set({ sandboxes })
    } catch (err: any) {
      set({ error: err.message || 'Failed to load sandboxes' })
    }
  },

  create: async (opts) => {
    const result = await api.createSandbox(opts)
    await get().fetch()
    set({ activeId: result.sandbox_id, view: 'sandbox' })
    return result.sandbox_id
  },

  setActive: (id) => set({ activeId: id, view: 'sandbox' }),
  openDashboard: () => set({ view: 'dashboard', activeId: null }),

  destroy: async (id) => {
    const prev = get().sandboxes
    const prevActive = get().activeId
    const prevView = get().view
    set({ sandboxes: prev.filter(s => s.sandbox_id !== id) })
    try {
      await api.destroySandbox(id)
      set({
        activeId: prevActive === id ? null : prevActive,
        view: prevActive === id ? 'dashboard' : prevView,
      })
    } catch (err: any) {
      set({ sandboxes: prev, error: err.message || 'Failed to destroy sandbox' })
    }
  },
}))
