import {
  IconActivity,
  IconHandStop,
  IconLayoutDashboard,
  IconPlayerPlay,
  IconPlayerStop,
  IconPlayerTrackNext,
  IconPlayerPause,
  IconShieldX
} from '@tabler/icons-react'
import { useMemo, useState } from 'react'
import { baseOption, chartTokens, EChart, timeAxis, valueAxis } from '../components/Chart.tsx'
import { Banner, EmptyGlass, GlassButton, GlassCard, KeyValue, PageHeader, Pill, ProgressBar, Section, Stat } from '../components/glass.tsx'
import { useConfirm, useToast } from '../components/overlays.tsx'
import type { PageId } from '../components/Shell.tsx'
import { post, usePoll, type ConfigView, type EquityRow, type EventRow, type Fill } from '../lib/api.ts'
import { cn } from '../lib/cn.ts'
import { fmtAgo, fmtMoney, fmtPct, fmtPrice, fmtQty, fmtSigned, fmtTime, tone } from '../lib/format.ts'
import { useStatus } from '../lib/status.ts'

function EquityChart({ rows, ccy }: { rows: EquityRow[]; ccy: string }) {
  const option = useMemo(() => {
    const t = chartTokens()
    return {
      ...baseOption(),
      tooltip: {
        ...(baseOption().tooltip as object),
        valueFormatter: (v: number) => fmtMoney(v, ccy)
      },
      xAxis: timeAxis(),
      yAxis: valueAxis(v => (Math.abs(v) >= 1000 ? `${(v / 1000).toFixed(1)}K` : v.toFixed(0)), 'left'),
      series: [
        {
          name: 'Equity',
          type: 'line',
          showSymbol: false,
          smooth: false,
          lineStyle: { width: 2, color: t.s1, cap: 'round', join: 'round' },
          itemStyle: { color: t.s1 },
          areaStyle: { color: t.s1, opacity: 0.1 },
          data: rows.map(r => [r.ts, r.equity]),
          endLabel: { show: rows.length > 1, color: t.fg, formatter: (p: { value: [string, number] }) => fmtMoney(p.value[1]) }
        }
      ],
      grid: { left: 8, right: 84, top: 16, bottom: 8, containLabel: true }
    }
  }, [rows, ccy])
  if (rows.length < 2) {
    return <EmptyGlass className="h-[260px]" icon={<IconActivity />} title="No equity history yet" description="Each trading cycle records a point. Start the bot or run a cycle." />
  }
  return <EChart option={option} height={260} ariaLabel={`Equity curve, ${rows.length} points, latest ${fmtMoney(rows[rows.length - 1].equity, ccy)}`} />
}

type Activity = { ts: string; kind: 'fill' | 'event'; title: string; detail: string; tone: 'ok' | 'danger' | 'warn' | 'info' | 'muted' }

function activity(fills: Fill[], events: EventRow[]): Activity[] {
  const a: Activity[] = fills.map(f => ({
    ts: f.ts,
    kind: 'fill',
    title: `${f.side === 'buy' ? 'Bought' : 'Sold'} ${fmtQty(f.qty)} ${f.symbol} @ ${fmtPrice(f.price)}`,
    detail: f.realized_pnl != null ? `realised ${fmtSigned(f.realized_pnl)} · ${f.strategy}` : f.strategy,
    tone: f.side === 'buy' ? 'ok' : 'danger'
  }))
  for (const e of events) {
    const t = ['halt', 'error', 'reject', 'stop'].includes(e.kind) ? 'danger' : ['promote', 'resume', 'bot'].includes(e.kind) ? 'info' : 'muted'
    a.push({ ts: e.ts, kind: 'event', title: e.kind, detail: e.message, tone: t })
  }
  return a.sort((x, y) => (x.ts < y.ts ? 1 : -1)).slice(0, 14)
}

export function OverviewPage({ onPage }: { onPage: (p: PageId) => void }) {
  const { status, refresh } = useStatus()
  const equity = usePoll<EquityRow[]>('/api/equity?limit=1200', 10_000)
  const fills = usePoll<Fill[]>('/api/fills?n=20', 5_000)
  const events = usePoll<EventRow[]>('/api/events?n=20', 5_000)
  const config = usePoll<ConfigView>('/api/config', 0)
  const toast = useToast()
  const confirm = useConfirm()
  const [busy, setBusy] = useState<string | null>(null)

  const act = async (key: string, fn: () => Promise<unknown>, ok: string) => {
    setBusy(key)
    try {
      await fn()
      toast('ok', ok)
    } catch (err) {
      toast('danger', err instanceof Error ? err.message : String(err))
    } finally {
      setBusy(null)
      refresh()
      equity.refresh()
      fills.refresh()
      events.refresh()
    }
  }

  if (!status) {
    return <div className="shimmer m-6 h-40 rounded-xl" />
  }
  const live = status.mode === 'live'
  const risk = config.data?.risk
  const gross = Object.values(status.positions).reduce((s, p) => s + Math.abs(p.qty * p.px), 0)
  const ddLimit = risk?.max_drawdown_pct ?? 0.15
  const ddUse = ((status.drawdown_pct ?? 0) / ddLimit) * 100
  const dayLossLimit = risk?.max_daily_loss_pct ?? 0.03
  const dayUse = (status.day_pnl_pct ?? 0) < 0 ? (-(status.day_pnl_pct ?? 0) / dayLossLimit) * 100 : 0
  const running = status.bot.running

  const toggleBot = async () => {
    if (!running) {
      const c = await confirm({
        title: live ? 'Start LIVE trading?' : 'Start the bot?',
        danger: live,
        typed: live ? 'LIVE' : undefined,
        confirmLabel: 'Start bot',
        body: live ? (
          <>
            The bot will place <b>real orders with real money</b> on {status.broker} every {status.timeframe} bar, within your risk limits.
          </>
        ) : (
          <>The bot will trade on paper every {status.timeframe} bar close. It keeps running while this app is open.</>
        )
      })
      if (!c.ok) return
      return act('bot', () => post('/api/bot/start'), 'Bot started')
    }
    return act('bot', () => post('/api/bot/stop'), 'Bot stopped')
  }

  return (
    <div className="flex h-full flex-col">
      <PageHeader
        icon={<IconLayoutDashboard />}
        title="Overview"
        subtitle={`${live ? 'Live' : 'Paper'} trading · ${status.broker} · ${status.timeframe} bars · ${status.symbols.join(', ')}`}
        actions={
          <>
            <GlassButton
              disabled={!!busy}
              title="Run one trading cycle now"
              onClick={async () => {
                const c = await confirm({
                  title: live ? 'Run a LIVE trading cycle now?' : 'Run one trading cycle now?',
                  danger: live,
                  typed: live ? 'LIVE' : undefined,
                  confirmLabel: 'Run cycle',
                  body: live ? (
                    <>
                      The strategy, stops and risk limits run once for every symbol and may place <b>real orders</b>.
                    </>
                  ) : (
                    <>The strategy, stops and risk limits run once for every symbol and may place paper orders.</>
                  )
                })
                if (c.ok) await act('cycle', () => post('/api/cycle'), 'Cycle complete')
              }}
            >
              <IconPlayerTrackNext /> {busy === 'cycle' ? 'Running…' : 'Run cycle now'}
            </GlassButton>
            <GlassButton variant={running ? 'secondary' : 'primary'} disabled={!!busy || status.bot.stopping} onClick={toggleBot}>
              {running ? <IconPlayerStop /> : <IconPlayerPlay />}
              {status.bot.stopping ? 'Stopping…' : running ? 'Stop bot' : 'Start bot'}
            </GlassButton>
          </>
        }
      />
      <div className="min-h-0 flex-1 overflow-y-auto px-6 pb-6">
        <div className="flex flex-col gap-4">
          {status.risk.halted && (
            <Banner
              tone="danger"
              title="Trading is halted"
              action={
                <GlassButton size="sm" onClick={async () => {
                  const c = await confirm({ title: 'Resume trading?', confirmLabel: 'Resume', body: 'This clears the halt and resets the drawdown baseline to current equity.' })
                  if (c.ok) await act('resume', () => post('/api/resume'), 'Trading resumed')
                }}>
                  <IconPlayerPlay /> Resume
                </GlassButton>
              }
            >
              {status.risk.halt_reason || 'No reason recorded.'} No new positions will be opened until you resume.
            </Banner>
          )}
          {status.busy && (
            <Banner tone="info" title="A trading cycle is running">
              Figures update when it finishes.
            </Banner>
          )}
          {status.bot.last_error && (
            <Banner tone="warn" title="The last cycle failed">
              {status.bot.last_error}
            </Banner>
          )}

          <div className="stagger grid grid-cols-5 gap-3">
            <Stat label="Equity" value={fmtMoney(status.equity)} sub={`Cash ${fmtMoney(status.cash)} ${status.currency}`} />
            <Stat label="Today" value={fmtSigned(status.day_pnl)} valueTone={tone(status.day_pnl)} sub={`${fmtPct(status.day_pnl_pct, 2, true)} · ${status.risk.trades_today} trades`}>
              <ProgressBar className="mt-1.5" label="Daily loss limit used" value={dayUse} tone={dayUse > 70 ? 'danger' : dayUse > 40 ? 'warn' : 'accent'} />
            </Stat>
            <Stat label="Drawdown" value={fmtPct(status.drawdown_pct)} sub={`Kill switch at ${fmtPct(ddLimit, 0)}`}>
              <ProgressBar className="mt-1.5" label="Drawdown limit used" value={ddUse} tone={ddUse > 70 ? 'danger' : ddUse > 40 ? 'warn' : 'accent'} />
            </Stat>
            <Stat label="Realised P&L" value={fmtSigned(status.realized_pnl)} valueTone={tone(status.realized_pnl)} sub={`${status.closed_trades ?? '—'} closed trades`} />
            <Stat label="Exposure" value={status.equity == null ? '—' : fmtPct(status.equity ? gross / status.equity : 0, 1)} sub={`Limit ${fmtPct(risk?.max_gross_exposure_pct ?? 0.8, 0)} · ${Object.keys(status.positions).length} open`} />
          </div>

          <div className="grid grid-cols-[minmax(0,2fr)_minmax(0,1fr)] gap-4">
            <GlassCard className="p-4">
              <Section title="Equity">
                {equity.data ? <EquityChart rows={equity.data} ccy={status.currency} /> : <div className="shimmer h-[260px] rounded-lg" />}
              </Section>
            </GlassCard>
            <GlassCard className="flex flex-col p-4">
              <Section title="Positions" action={<Pill>{Object.keys(status.positions).length} open</Pill>}>
                {Object.keys(status.positions).length === 0 ? (
                  <EmptyGlass className="min-h-[200px]" title="Flat" description="No open positions." />
                ) : (
                  <table className="tabular w-full text-[12.5px]">
                    <thead>
                      <tr className="text-left text-fg-3">
                        <th className="pb-2 font-medium">Symbol</th>
                        <th className="pb-2 text-right font-medium">Qty</th>
                        <th className="pb-2 text-right font-medium">Avg / Last</th>
                        <th className="pb-2 text-right font-medium">Unrealised</th>
                      </tr>
                    </thead>
                    <tbody>
                      {Object.entries(status.positions).map(([sym, p]) => (
                        <tr key={sym} className="border-t border-line">
                          <td className="py-2">
                            <button type="button" className="text-fg hover:underline" onClick={() => onPage('markets')}>
                              {sym}
                            </button>
                            <div className="text-[11px] text-fg-3">{status.strategies[sym]}</div>
                          </td>
                          <td className="py-2 text-right">{fmtQty(p.qty)}</td>
                          <td className="py-2 text-right">
                            {fmtPrice(p.avg)}
                            <div className="text-[11px] text-fg-3">{fmtPrice(p.px)}</div>
                          </td>
                          <td className={cn('py-2 text-right', p.upnl > 0 ? 'text-ok' : p.upnl < 0 ? 'text-danger' : 'text-fg-2')}>{fmtSigned(p.upnl)}</td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                )}
              </Section>
            </GlassCard>
          </div>

          <div className="grid grid-cols-[minmax(0,2fr)_minmax(0,1fr)] gap-4">
            <GlassCard className="p-4">
              <Section title="Recent activity" action={<button type="button" className="text-[12px] text-accent-strong hover:underline" onClick={() => onPage('journal')}>Open journal →</button>}>
                {fills.data && events.data && activity(fills.data, events.data).length === 0 ? (
                  <EmptyGlass title="Nothing yet" description="Trades, halts, promotions and errors appear here." />
                ) : (
                  <ul className="flex flex-col">
                    {activity(fills.data ?? [], events.data ?? []).map((a, i) => (
                      <li key={i} className="flex items-start gap-3 border-t border-line py-2 first:border-t-0">
                        <span className={cn('mt-1.5 size-2 shrink-0 rounded-full', { ok: 'bg-ok', danger: 'bg-danger', warn: 'bg-warn', info: 'bg-info', muted: 'bg-fg-4' }[a.tone])} />
                        <div className="min-w-0 flex-1">
                          <div className="truncate text-[12.5px] text-fg">{a.kind === 'event' ? <span className="capitalize">{a.title}</span> : a.title}</div>
                          <div className="selectable truncate text-[11.5px] text-fg-3" title={a.detail}>
                            {a.detail}
                          </div>
                        </div>
                        <span className="tabular shrink-0 text-[11.5px] text-fg-4">{fmtTime(a.ts)}</span>
                      </li>
                    ))}
                  </ul>
                )}
              </Section>
            </GlassCard>
            <GlassCard className="flex flex-col gap-4 p-4">
              <Section title="Risk controls">
                <KeyValue
                  labelWidth={130}
                  rows={[
                    { label: 'Trades today', value: `${status.risk.trades_today} / ${risk?.max_trades_per_day ?? '—'}` },
                    { label: 'Max per position', value: fmtPct(risk?.max_position_pct, 0) },
                    { label: 'Max order', value: fmtMoney(risk?.max_order_notional) },
                    { label: 'Daily loss limit', value: fmtPct(dayLossLimit, 0) },
                    { label: 'LLM review', value: status.llm_enabled ? 'On (shrink/veto only)' : 'Off' },
                    { label: 'Last cycle', value: fmtAgo(status.last_cycle) }
                  ]}
                />
                <p className="text-[11.5px] text-fg-4">Limits are read-only here. Change them in config.yaml and restart the backend.</p>
              </Section>
              <div className="mt-auto grid grid-cols-2 gap-2">
                <GlassButton
                  variant="secondary"
                  disabled={!!busy || status.risk.halted}
                  onClick={async () => {
                    const c = await confirm({ title: 'Halt trading?', confirmLabel: 'Halt', withReason: true, body: 'Stops opening new positions. Existing positions stay open, and exits and stops still work.' })
                    if (c.ok) await act('halt', () => post('/api/halt', { reason: c.reason || 'halt from desktop app' }), 'Trading halted')
                  }}
                >
                  <IconPlayerPause /> Halt
                </GlassButton>
                <GlassButton
                  variant="danger"
                  disabled={!!busy || Object.keys(status.positions).length === 0}
                  onClick={async () => {
                    const c = await confirm({
                      title: 'Close every position now?',
                      danger: true,
                      typed: 'FLATTEN',
                      confirmLabel: 'Flatten all',
                      body: (
                        <>
                          Sends market orders to close all {Object.keys(status.positions).length} positions{live ? ' with real money' : ''}. The bot keeps running; halt it too if you want it to stay flat.
                        </>
                      )
                    })
                    if (c.ok) await act('flatten', () => post('/api/flatten', { confirm: 'FLATTEN' }), 'All positions closed')
                  }}
                >
                  <IconShieldX /> Flatten all
                </GlassButton>
              </div>
              {!running && !status.risk.halted && (
                <div className="flex items-center gap-2 text-[11.5px] text-fg-3">
                  <IconHandStop size={14} /> Bot is stopped: no orders are placed until you start it.
                </div>
              )}
            </GlassCard>
          </div>
        </div>
      </div>
    </div>
  )
}
