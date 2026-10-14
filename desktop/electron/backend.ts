import { type ChildProcess, spawn } from 'node:child_process'
import { createHmac, randomBytes, timingSafeEqual } from 'node:crypto'
import { EventEmitter } from 'node:events'
import fs from 'node:fs'
import path from 'node:path'
import readline from 'node:readline'
import { API_GET, API_POST, type ApiResult, type BackendState, type Settings } from '../shared/ipc.ts'

const READY_TIMEOUT_MS = 60_000
/** How long a backend may take to finish an in-flight trading cycle before it is force-killed. */
const SHUTDOWN_GRACE_MS = 120_000
const SLOW_PATHS = new Set(['/api/chat', '/api/optimize', '/api/backtest', '/api/cycle'])

/** Resolve the hermes-trader executable: explicit setting, then the project's venv, then PATH. */
export function resolveCommand(s: Settings): string {
  if (s.command.trim()) {
    return s.command.trim()
  }
  const venv = path.join(s.projectDir, '.venv', 'bin', 'hermes-trader')

  return fs.existsSync(venv) ? venv : 'hermes-trader'
}

export function allowed(method: 'GET' | 'POST', apiPath: string): boolean {
  const bare = apiPath.split('?')[0]
  const list: readonly string[] = method === 'GET' ? API_GET : API_POST

  return list.includes(bare) && !apiPath.includes('..')
}

/**
 * Owns the connection to the Python backend: either a child process it spawned
 * (`hermes-trader serve --port 0`, random token via env) or an existing server it attaches to.
 * The API token never reaches the renderer.
 */
export class Backend extends EventEmitter {
  state: BackendState = { phase: 'stopped', mode: 'spawn', url: null, error: null, command: null, pid: null }
  logs: string[] = []
  private child: ChildProcess | null = null
  private token: string | null = null

  private set(patch: Partial<BackendState>): void {
    this.state = { ...this.state, ...patch }
    this.emit('state', this.state)
  }

  private log(line: string): void {
    this.logs.push(line)
    if (this.logs.length > 500) {
      this.logs.splice(0, this.logs.length - 500)
    }
  }

  async start(s: Settings): Promise<BackendState> {
    await this.stop()
    this.set({ phase: 'starting', mode: s.mode, error: null, url: null, pid: null, command: null })

    try {
      if (s.mode === 'attach') {
        await this.attach(s)
      } else {
        await this.spawnServer(s)
      }
      this.set({ phase: 'ready' })
    } catch (err) {
      this.set({ phase: 'error', error: err instanceof Error ? err.message : String(err) })
      await this.killChild()
    }

    return this.state
  }

  private async attach(s: Settings): Promise<void> {
    const tokenFile = s.attachTokenFile.trim() || path.join(s.projectDir, 'data', 'api_token')

    if (!fs.existsSync(tokenFile)) {
      throw new Error(`Token file not found: ${tokenFile}. Start the backend with \`hermes-trader serve\` first.`)
    }
    this.token = fs.readFileSync(tokenFile, 'utf8').trim()
    const url = s.attachUrl.trim().replace(/\/$/, '')

    if (!/^http:\/\/(127\.0\.0\.1|localhost):\d+$/.test(url)) {
      throw new Error('Attach URL must be http://127.0.0.1:<port> (the API only listens locally).')
    }
    this.set({ url })
    await this.waitHealthy(url, 5_000)
    await this.verifyIdentity(url)
    const probe = await this.raw(url, 'GET', '/api/config')

    if (!probe.ok) {
      throw new Error(`Backend refused the token (${probe.status}): ${probe.error ?? ''}`)
    }
  }

  private async spawnServer(s: Settings): Promise<void> {
    if (!fs.existsSync(path.join(s.projectDir, 'config.yaml'))) {
      throw new Error(`No config.yaml in ${s.projectDir}. Run \`hermes-trader init\` there, or pick the right folder in Settings.`)
    }
    const command = resolveCommand(s)
    this.token = randomBytes(32).toString('base64url')
    this.log(`$ ${command} serve --port 0   (cwd ${s.projectDir})`)
    const child = spawn(command, ['serve', '--port', '0'], {
      cwd: s.projectDir,
      // stdin stays open and unused: when this app exits for any reason the backend sees EOF and stops trading
      env: { ...process.env, HERMES_TRADER_API_TOKEN: this.token, HERMES_TRADER_EXIT_ON_STDIN_EOF: '1', PYTHONUNBUFFERED: '1' },
      stdio: ['pipe', 'pipe', 'pipe']
    })
    this.child = child
    this.set({ command, pid: child.pid ?? null })

    const url = await new Promise<string>((resolve, reject) => {
      const timer = setTimeout(() => reject(new Error('Backend did not start within 60s. See Settings → Logs.')), READY_TIMEOUT_MS)
      const done = (fn: () => void) => {
        clearTimeout(timer)
        fn()
      }
      readline.createInterface({ input: child.stdout! }).on('line', line => {
        this.log(line)
        try {
          const j = JSON.parse(line) as { hermes_trader_api?: string }
          if (j.hermes_trader_api) {
            done(() => resolve(j.hermes_trader_api!))
          }
        } catch {
          /* ordinary log line */
        }
      })
      readline.createInterface({ input: child.stderr! }).on('line', line => this.log(line))
      child.once('error', err => {
        const hint = (err as NodeJS.ErrnoException).code === 'ENOENT' ? ` (is hermes-trader installed? looked for "${command}")` : ''
        done(() => reject(new Error(`Could not start backend: ${err.message}${hint}`)))
      })
      child.once('exit', code => done(() => reject(new Error(`Backend exited with code ${code}. Last log: ${this.logs.slice(-3).join(' | ')}`))))
    })

    child.on('exit', code => {
      this.child = null
      if (this.state.phase === 'ready' || this.state.phase === 'starting') {
        this.set({ phase: 'error', error: `Backend stopped (exit ${code}). Last log: ${this.logs.slice(-2).join(' | ')}`, pid: null })
      }
    })
    this.set({ url })
    await this.waitHealthy(url, 10_000)
    await this.verifyIdentity(url)
  }

  /** Make the server prove it knows the token (HMAC of a nonce) before we ever send the token to it. */
  private async verifyIdentity(url: string): Promise<void> {
    const nonce = randomBytes(16).toString('hex')
    const r = await fetch(`${url}/api/health`, { headers: { 'X-Challenge': nonce }, signal: AbortSignal.timeout(5_000) })
    const j = (await r.json().catch(() => ({}))) as { proof?: string }
    const want = createHmac('sha256', this.token ?? '').update(nonce).digest()
    const got = Buffer.from(String(j.proof ?? ''), 'hex')
    if (got.length !== want.length || !timingSafeEqual(got, want)) {
      this.token = null
      throw new Error(`The server at ${url} is not your Hermes Trader backend (it could not prove the token). Refusing to connect.`)
    }
  }

  private async waitHealthy(url: string, ms: number): Promise<void> {
    const until = Date.now() + ms
    let last = ''

    while (Date.now() < until) {
      try {
        const r = await fetch(`${url}/api/health`, { signal: AbortSignal.timeout(2_000) })
        if (r.ok) {
          return
        }
        last = `HTTP ${r.status}`
      } catch (err) {
        last = err instanceof Error ? err.message : String(err)
      }
      await new Promise(r => setTimeout(r, 300))
    }
    throw new Error(`Backend not reachable at ${url}: ${last}`)
  }

  async request<T>(method: 'GET' | 'POST', apiPath: string, body?: Record<string, unknown>): Promise<ApiResult<T>> {
    if (!allowed(method, apiPath)) {
      return { ok: false, status: 400, error: `path not allowed: ${method} ${apiPath}` }
    }
    if (this.state.phase !== 'ready' || !this.state.url) {
      return { ok: false, status: 503, error: this.state.error ?? 'backend not connected' }
    }
    return this.raw<T>(this.state.url, method, apiPath, body)
  }

  private async raw<T>(url: string, method: 'GET' | 'POST', apiPath: string, body?: Record<string, unknown>): Promise<ApiResult<T>> {
    const bare = apiPath.split('?')[0]

    try {
      const r = await fetch(`${url}${apiPath}`, {
        method,
        headers: { Authorization: `Bearer ${this.token}`, ...(method === 'POST' ? { 'Content-Type': 'application/json' } : {}) },
        body: method === 'POST' ? JSON.stringify(body ?? {}) : undefined,
        signal: AbortSignal.timeout(SLOW_PATHS.has(bare) ? 300_000 : 30_000)
      })
      const j = (await r.json().catch(() => ({}))) as { ok?: boolean; data?: T; error?: string }

      return { ok: r.ok && j.ok !== false, status: r.status, data: j.data, error: j.error }
    } catch (err) {
      return { ok: false, status: 0, error: err instanceof Error ? err.message : String(err) }
    }
  }

  /** SIGTERM lets the backend finish an in-flight cycle (so no order goes unjournaled); SIGKILL only as a last resort. */
  private async killChild(): Promise<void> {
    const child = this.child
    if (!child || child.exitCode !== null) {
      this.child = null
      return
    }
    await new Promise<void>(resolve => {
      const t = setTimeout(() => {
        this.log('backend did not stop in time: force-killing')
        child.kill('SIGKILL')
        resolve()
      }, SHUTDOWN_GRACE_MS)
      child.once('exit', () => {
        clearTimeout(t)
        resolve()
      })
      child.kill('SIGTERM')
    })
    this.child = null
  }

  async stop(): Promise<void> {
    const wasSpawned = !!this.child
    if (wasSpawned && this.state.phase === 'ready') {
      await this.request('POST', '/api/bot/stop').catch(() => undefined)
    }
    this.set({ phase: 'stopped', url: null, pid: null })
    await this.killChild()
    if (wasSpawned) {
      this.log('backend stopped')
    }
  }

  get spawned(): boolean {
    return !!this.child
  }
}
