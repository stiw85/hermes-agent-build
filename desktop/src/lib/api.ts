import { useCallback, useEffect, useRef, useState } from 'react'
import type { ApiResult, BackendState, TraderBridge } from '../../shared/ipc.ts'

type Bridge = TraderBridge & {
  windowControl(a: 'minimize' | 'maximize' | 'close'): void
  onMaximized(cb: (m: boolean) => void): () => void
}

declare global {
  interface Window {
    trader: Bridge
  }
}

export const trader = (): Bridge => window.trader

// ---- API shapes (mirror hermes_trader/server.py) -------------------------------------------

export interface PositionRow {
  qty: number
  avg: number
  px: number
  upnl: number
}

export interface RiskState {
  day: string
  start_of_day_equity: number
  peak_equity: number
  trades_today: number
  halted: boolean
  halt_reason: string
}

export interface BotState {
  running: boolean
  /** asked to stop, still finishing the cycle in progress */
  stopping: boolean
  next_cycle: string | null
  last_tick: string | null
  last_error: string | null
  started_at: string | null
}

export interface Status {
  mode: 'paper' | 'live'
  broker: string
  /** null only while the very first snapshot is blocked by a running cycle (busy) */
  equity: number | null
  cash: number | null
  currency: string
  positions: Record<string, PositionRow>
  risk: RiskState
  strategies: Record<string, string>
  last_cycle: string | null
  version: string
  symbols: string[]
  timeframe: string
  llm_enabled: boolean
  jev_mode: 'off' | 'shadow' | 'gate' | 'error'
  allow_short: boolean
  day_pnl: number | null
  day_pnl_pct: number | null
  drawdown_pct: number | null
  realized_pnl: number | null
  closed_trades: number | null
  bot: BotState
  /** a cycle was running: these numbers are the last snapshot */
  busy?: boolean
}

export interface EquityRow {
  ts: string
  equity: number
  cash: number
  gross_exposure: number
}

export interface Fill {
  id: number
  ts: string
  order_id: string
  symbol: string
  side: 'buy' | 'sell'
  qty: number
  price: number
  fee: number
  status: string
  strategy: string
  reason: string
  realized_pnl: number | null
}

export interface Decision {
  id: number
  ts: string
  symbol: string
  strategy: string
  params: string | null
  target: number
  price: number
  signal_reason: string
  risk_notes: string
  llm_verdict: string
  llm_note: string
  action: string
  jev_p: number | null
  jev_note: string | null
}

export interface JevBucket {
  bucket: string
  trades: number
  win_rate: number | null
  avg_p: number | null
  pnl: number
}

export interface JevReport {
  enabled: boolean
  /** set when JEV is enabled but could not start (e.g. missing key); the bot trades without it */
  error?: string | null
  mode?: 'shadow' | 'gate'
  veto_below?: number
  reduce_below?: number
  scored?: number
  taken?: number
  resolved?: number
  open?: number
  errors?: number
  cost_usd?: number
  brier?: number | null
  brier_base_rate?: number | null
  buckets?: JevBucket[]
  what_if_gate_pnl?: number
  by_regime?: Record<string, { trades: number; wins: number; pnl: number }>
  recommendation?: string
  recent?: { ts: string; symbol: string; side: string; strategy: string; p: number | null; regime: string | null; verdict: string | null; applied: number; taken: number; outcome_pnl: number | null; closed_ts: string | null; error: string | null }[]
}

export interface EventRow {
  id: number
  ts: string
  kind: string
  message: string
  data: string | null
}

export interface Metrics {
  strategy: string
  params: Record<string, unknown>
  bars: number
  total_return: number
  cagr: number
  sharpe: number
  sortino: number
  max_drawdown: number
  volatility: number
  trades: number
  win_rate: number
  profit_factor: number | null
  exposure: number
  fees_paid_pct: number
}

export interface BookEntry {
  strategy: string
  params: Record<string, number>
  version: number
  source: string
  promoted_at?: string
  metrics?: { holdout?: Metrics; score?: number; bars?: number; why?: string }
  history?: Omit<BookEntry, 'history'>[]
}

export interface StrategyDef {
  name: string
  description: string
  defaults: Record<string, number>
  grid: Record<string, number[]>
}

export interface Snapshot {
  last: number
  bar_time: string
  bars: number
  chg_24: number | null
  chg_100: number | null
  vol_annual: number | null
  rsi14: number | null
  atr_pct: number | null
  trend_sma50_200: string
  range_100: [number, number]
}

export interface Candles {
  symbol: string
  timeframe: string
  candles: [number, number, number, number, number, number][]
  snapshot: Snapshot
  strategy: BookEntry
  fills: { ts: string; side: 'buy' | 'sell'; qty: number; price: number; strategy: string; realized_pnl: number | null }[]
}

export interface Stats {
  fills: number
  closed_trades: number
  realized_pnl: number
  by_strategy_symbol: { strategy: string; symbol: string; closes: number; pnl: number; wins: number; fees: number; win_rate: number }[]
  max_drawdown: number
}

export interface Candidate {
  strategy: string
  params: Record<string, number>
  train_score: number
  train: { sharpe: number; total_return: number; max_drawdown: number; trades: number }
  holdout?: Metrics
  holdout_score?: number | null
}

export interface OptimizeReport {
  symbol: string
  incumbent: BookEntry
  incumbent_score: number | null
  best: Candidate | null
  promoted: boolean
  passes: boolean
  reason: string
  leaderboard: Candidate[]
}

export interface BacktestResponse {
  result: Metrics
  buy_and_hold: { total_return: number; sharpe: number; max_drawdown: number }
  curve: [number, number, number][]
}

export interface ConfigView {
  mode: string
  symbols: string[]
  timeframe: string
  history_bars: number
  allow_short: boolean
  default_strategy: { name: string; params: Record<string, number> }
  risk: Record<string, number>
  improve: Record<string, unknown>
  schedule: Record<string, unknown>
  broker: Record<string, unknown>
  llm: Record<string, unknown>
  home: string
  config_path: string | null
}

// ---- calls ---------------------------------------------------------------------------------

export async function get<T>(path: string): Promise<T> {
  const r: ApiResult<T> = await trader().get<T>(path)
  if (!r.ok) throw new Error(r.error || `HTTP ${r.status}`)
  return r.data as T
}

export async function post<T>(path: string, body?: Record<string, unknown>): Promise<T> {
  const r: ApiResult<T> = await trader().post<T>(path, body)
  if (!r.ok) throw new Error(r.error || `HTTP ${r.status}`)
  return r.data as T
}

/** Poll a GET endpoint while mounted (and the window is visible). `refresh()` forces a reload. */
export function usePoll<T>(path: string | null, intervalMs = 5000): { data: T | null; error: string | null; loading: boolean; refresh: () => void } {
  const [data, setData] = useState<T | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [loading, setLoading] = useState(false)
  const seq = useRef(0)

  const load = useCallback(async () => {
    if (!path) return
    const n = ++seq.current
    setLoading(true)
    try {
      const d = await get<T>(path)
      if (n === seq.current) {
        setData(d)
        setError(null)
      }
    } catch (err) {
      if (n === seq.current) setError(err instanceof Error ? err.message : String(err))
    } finally {
      if (n === seq.current) setLoading(false)
    }
  }, [path])

  useEffect(() => {
    setData(null)
    void load()
    if (!intervalMs) return
    const t = setInterval(() => {
      if (document.visibilityState === 'visible') void load()
    }, intervalMs)
    return () => clearInterval(t)
  }, [load, intervalMs])

  return { data, error, loading, refresh: () => void load() }
}

export function useBackendState(): BackendState | null {
  const [s, setS] = useState<BackendState | null>(null)
  useEffect(() => {
    void trader().backendState().then(setS)
    return trader().onBackendState(setS)
  }, [])
  return s
}
