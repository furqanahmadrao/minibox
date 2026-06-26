const API_BASE = window.location.origin

class ApiClient {
  private token: string | null = null
  private tokenExpiry: number = 0

  setToken(t: string | null) {
    this.token = t
    this.tokenExpiry = t ? Date.now() + 3600_000 : 0
    t ? localStorage.setItem('minibox_token', t) : localStorage.removeItem('minibox_token')
  }

  getToken(): string | null {
    if (!this.token) this.token = localStorage.getItem('minibox_token')
    return this.token
  }

  isTokenExpired(): boolean {
    return this.tokenExpiry > 0 && Date.now() >= this.tokenExpiry
  }

  private async req<T>(path: string, opts: { method?: string; body?: unknown; params?: Record<string, string> } = {}): Promise<T> {
    const { method = 'GET', body, params } = opts
    let url = `${API_BASE}${path}`
    if (params) url += `?${new URLSearchParams(params)}`

    const headers: Record<string, string> = { 'Content-Type': 'application/json' }
    const token = this.getToken()
    if (token) headers['Authorization'] = `Bearer ${token}`

    const res = await fetch(url, { method, headers, body: body != null ? JSON.stringify(body) : undefined })
    if (!res.ok) {
      if (res.status === 401) {
        this.setToken(null)
        window.location.reload()
        throw new Error('Session expired')
      }
      const err = await res.json().catch(() => ({ detail: res.statusText }))
      throw new Error(err.detail || `HTTP ${res.status}`)
    }
    return res.json()
  }

  async login(u: string, p: string) {
    const d = await this.req<{ token: string; expires_in: number }>('/api/auth/login', { method: 'POST', body: { username: u, password: p } })
    this.setToken(d.token)
    if (d.expires_in) this.tokenExpiry = Date.now() + d.expires_in * 1000
    return d
  }

  async setup(u: string, p: string) {
    return this.req<{ user: any }>('/api/auth/setup', { method: 'POST', body: { username: u, password: p, role: 'admin' } })
  }

  async createSandbox(o: { template?: string; label?: string; ttl?: number; cpu_cores?: number; memory_mb?: number; network?: string; env?: Record<string, string>; agent_config?: any }) {
    return this.req<{ sandbox_id: string; status: string }>('/api/sandbox/create', { method: 'POST', body: o })
  }

  async listSandboxes() {
    return this.req<Array<{ sandbox_id: string; status: string; template: string; label: string; ttl: number; cpu_cores: number; memory_mb: number; network_mode: string; egress_allowlist: string[]; env: Record<string, string>; exec_count: number; ttl_remaining: number; agent_config: any; created_at: number; port_forwards: any[] }>>('/api/sandbox/list')
  }

  async getSandbox(id: string) {
    return this.req<any>(`/api/sandbox/${id}`)
  }

  async destroySandbox(id: string) {
    return this.req<any>(`/api/sandbox/${id}`, { method: 'DELETE' })
  }

  async pauseSandbox(id: string) {
    return this.req<any>(`/api/sandbox/${id}/pause`, { method: 'POST' })
  }

  async resumeSandbox(id: string) {
    return this.req<any>(`/api/sandbox/${id}/resume`, { method: 'POST' })
  }

  async updateSandbox(id: string, patch: any) {
    return this.req<any>(`/api/sandbox/${id}`, { method: 'PATCH', body: patch })
  }

  async getSandboxStats(id: string) {
    return this.req<{ cpu_percent: number; memory_mb: number; memory_limit_mb: number; disk_mb: number; uptime_seconds: number; exec_count: number; ttl_remaining: number; status: string }>(`/api/sandbox/${id}/stats`)
  }

  async exec(sandboxId: string, cmd: string, workdir?: string) {
    return this.req<{ stdout: string; stderr: string; exit_code: number }>(`/api/sandbox/${sandboxId}/exec`, { method: 'POST', body: { cmd, workdir: workdir || '/', timeout: 60 } })
  }

  async readFile(sandboxId: string, path: string) {
    return this.req<{ path: string; content: string; size: number }>(`/api/sandbox/${sandboxId}/fs/read`, { params: { path } })
  }

  async writeFile(sandboxId: string, path: string, content: string) {
    return this.req<{ path: string; size: number }>(`/api/sandbox/${sandboxId}/fs/write`, { method: 'POST', body: { path, content } })
  }

  async deleteFile(sandboxId: string, path: string) {
    return this.req<any>(`/api/sandbox/${sandboxId}/fs/delete`, { method: 'DELETE', params: { path } })
  }

  async listFiles(sandboxId: string, path?: string) {
    return this.req<{ name: string; type: string; size?: number; children?: any[] }>(`/api/sandbox/${sandboxId}/fs/tree`, { params: { path: path || '/' } })
  }

  async listSnapshots(sandboxId: string) {
    return this.req<Array<{ snapshot_id: string; label: string; size: number; created_at: number }>>(`/api/sandbox/${sandboxId}/snapshots`)
  }

  async createSnapshot(sandboxId: string, label: string) {
    return this.req<any>(`/api/sandbox/${sandboxId}/snapshot`, { method: 'POST', body: { label } })
  }

  async restoreSnapshot(sandboxId: string, snapshotId: string) {
    return this.req<any>(`/api/sandbox/${sandboxId}/restore/${snapshotId}`, { method: 'POST' })
  }

  async forkSnapshot(sandboxId: string, snapshotId: string) {
    return this.req<{ sandbox_id: string }>(`/api/sandbox/${sandboxId}/fork`, { method: 'POST', body: { snapshot_id: snapshotId } })
  }

  async listTemplates() {
    return this.req<Array<{ id: string; name: string; description: string; packages?: string[]; is_custom?: boolean }>>('/api/templates')
  }

  async registerTemplate(template: { id: string; name: string; description: string; packages: string[]; env: Record<string, string> }) {
    return this.req<any>('/api/templates', { method: 'POST', body: template })
  }

  async getConfig() {
    return this.req<any>('/api/admin/config')
  }

  async updateConfig(updates: any) {
    return this.req<any>('/api/admin/config', { method: 'PATCH', body: updates })
  }

  async updateTemplate(id: string, template: { name: string; description: string; packages: string[]; env: Record<string, string> }) {
    return this.req<any>(`/api/templates/${id}`, { method: 'PUT', body: { id, ...template } })
  }

  async deleteTemplate(id: string) {
    return this.req<any>(`/api/templates/${id}`, { method: 'DELETE' })
  }

  async listProviders() {
    return this.req<Array<{ id: string; name: string; base_url: string; models: any[]; requires_api_key: boolean }>>('/api/agent/providers')
  }

  async listAgents() {
    return this.req<Array<{ id: string; name: string; description: string; install_cmd: string; providers: string[] }>>('/api/agent/list')
  }

  async fetchModels(providerId: string, baseUrl: string, apiKey: string) {
    return this.req<Array<{ id: string; name: string; context: number }>>('/api/agent/fetch-models', { method: 'POST', body: { provider_id: providerId, base_url: baseUrl, api_key: apiKey } })
  }

  async startAcpSession(sandboxId: string, agentType: string, cwd?: string, apiKey?: string, baseUrl?: string, model?: string) {
    return this.req<{ session_id: string; status: string; capabilities: any }>(`/api/sandbox/${sandboxId}/acp/start`, { method: 'POST', body: { agent_type: agentType, cwd: cwd || '/', api_key: apiKey || '', base_url: baseUrl || '', model: model || '' } })
  }

  async stopAcpSession(sandboxId: string, sessionId: string) {
    return this.req<any>(`/api/sandbox/${sandboxId}/acp/stop`, { method: 'POST', params: { session_id: sessionId } })
  }

  async acpPrompt(sandboxId: string, sessionId: string, prompt: string) {
    return this.req<{ updates: any[] }>(`/api/sandbox/${sandboxId}/acp/prompt`, { method: 'POST', body: { session_id: sessionId, prompt } })
  }

  // Schedule methods
  async listSchedules(sandboxId: string) {
    return this.req<Array<{ id: string; name: string; command: string; schedule: string; enabled: boolean; last_run?: number; next_run?: number }>>(`/api/sandbox/${sandboxId}/schedules`)
  }

  async createSchedule(sandboxId: string, name: string, command: string, cron: string) {
    return this.req<{ schedule_id: string; next_run?: number }>(`/api/sandbox/${sandboxId}/schedules`, { method: 'POST', body: { name, command, cron } })
  }

  async toggleSchedule(sandboxId: string, scheduleId: string, enabled: boolean) {
    return this.req<any>(`/api/sandbox/${sandboxId}/schedules/${scheduleId}`, { method: 'PATCH', body: { enabled } })
  }

  async deleteSchedule(sandboxId: string, scheduleId: string) {
    return this.req<any>(`/api/sandbox/${sandboxId}/schedules/${scheduleId}`, { method: 'DELETE' })
  }

  async runSchedule(sandboxId: string, scheduleId: string) {
    return this.req<any>(`/api/sandbox/${sandboxId}/schedules/${scheduleId}/run`, { method: 'POST' })
  }

  // Breakpoint methods
  async listBreakpoints(sandboxId: string) {
    return this.req<Array<{ id: string; sandbox_id: string; pattern: string; action: string; created_at: number; hit_count: number }>>(`/api/sandbox/${sandboxId}/breakpoints`)
  }

  async createBreakpoint(sandboxId: string, pattern: string, action: string) {
    return this.req<{ id: string; sandbox_id: string; pattern: string; action: string; created_at: number; hit_count: number }>(`/api/sandbox/${sandboxId}/breakpoints`, { method: 'POST', body: { pattern, action } })
  }

  async deleteBreakpoint(sandboxId: string, bpId: string) {
    return this.req<any>(`/api/sandbox/${sandboxId}/breakpoints/${bpId}`, { method: 'DELETE' })
  }

  // Port forwarding
  async listPorts(sandboxId: string) {
    const res = await this.req<{ sandbox_id: string; forwards: Array<{ port: number; host_port: number }> }>(`/api/sandbox/${sandboxId}/ports`)
    return res.forwards || []
  }

  async exposePort(sandboxId: string, port: number) {
    return this.req<{ port: number; host_port: number }>(`/api/sandbox/${sandboxId}/port/expose`, { method: 'POST', body: { port } })
  }

  async removePort(sandboxId: string, port: number) {
    return this.req<any>(`/api/sandbox/${sandboxId}/port/${port}`, { method: 'DELETE' })
  }

  // Auth management
  async listUsers() {
    return this.req<Array<{ username: string; role: string; created_at: number }>>('/api/auth/users')
  }

  async listApiKeys() {
    return this.req<Array<{ key: string; name: string; scopes: string[]; created_at: number; last_used?: number }>>('/api/auth/api-keys')
  }

  async createApiKey(name: string, scopes: string[]) {
    return this.req<{ key: string; name: string; scopes: string[] }>('/api/auth/api-keys', { method: 'POST', body: { name, scopes } })
  }

  async deleteApiKey(key: string) {
    return this.req<any>(`/api/auth/api-keys/${key}`, { method: 'DELETE' })
  }

  async listScopes() {
    const res = await this.req<{ scopes: Array<{ id: string; name: string; description: string }>; groups: Record<string, string[]> }>('/api/auth/scopes')
    return res.scopes || []
  }

  async getAuditLog() {
    return this.req<Array<{ event: string; user: string; timestamp: number; details?: any }>>('/api/auth/audit')
  }
}

export const api = new ApiClient()
