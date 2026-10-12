/** Contract between the renderer, the preload bridge and the Electron main process. */

export type BackendMode = 'spawn' | 'attach'

export interface Settings {
  /** spawn: the app starts `hermes-trader serve` itself. attach: connect to one you started (tmux/systemd). */
  mode: BackendMode
  /** Folder that holds config.yaml (and usually the .venv). */
  projectDir: string
  /** Optional explicit command, e.g. /home/me/hermes-trader/.venv/bin/hermes-trader */
  command: string
  /** attach mode: http://127.0.0.1:8765 and the token file written by `serve` (data/api_token). */
  attachUrl: string
  attachTokenFile: string
}

export type BackendPhase = 'stopped' | 'starting' | 'ready' | 'error'

export interface BackendState {
  phase: BackendPhase
  mode: BackendMode
  url: string | null
  error: string | null
  command: string | null
  pid: number | null
}

export interface ApiResult<T = unknown> {
  ok: boolean
  status: number
  data?: T
  error?: string
}

export interface TraderBridge {
  get<T = unknown>(path: string): Promise<ApiResult<T>>
  post<T = unknown>(path: string, body?: Record<string, unknown>): Promise<ApiResult<T>>
  backendState(): Promise<BackendState>
  backendRestart(): Promise<BackendState>
  backendLogs(): Promise<string[]>
  onBackendState(cb: (s: BackendState) => void): () => void
  getSettings(): Promise<Settings>
  setSettings(patch: Partial<Settings>): Promise<Settings>
  pickFolder(): Promise<string | null>
  openPath(path: string): Promise<void>
}

/** Paths the renderer may call. Anything else is refused in main. */
export const API_GET = [
  '/api/health', '/api/status', '/api/equity', '/api/fills', '/api/decisions', '/api/events', '/api/stats',
  '/api/book', '/api/strategies', '/api/candles', '/api/lessons', '/api/playbooks', '/api/playbook', '/api/config'
] as const
export const API_POST = [
  '/api/bot/start', '/api/bot/stop', '/api/cycle', '/api/halt', '/api/resume', '/api/flatten', '/api/rollback',
  '/api/optimize', '/api/backtest', '/api/chat'
] as const
