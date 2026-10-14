import { IconArrowBackUp, IconFlask, IconPlayerPlay, IconSparkles } from '@tabler/icons-react'
import { useEffect, useMemo, useState } from 'react'
import { baseOption, chartTokens, EChart, timeAxis, valueAxis } from '../components/Chart.tsx'
import { Banner, EmptyGlass, Field, GlassButton, GlassCard, KeyValue, PageHeader, Pill, Section, Select, Stat, TextInput } from '../components/glass.tsx'
import { useConfirm, useToast } from '../components/overlays.tsx'
import { post, usePoll, type BacktestResponse, type BookEntry, type Candidate, type OptimizeReport, type StrategyDef } from '../lib/api.ts'
import { cn } from '../lib/cn.ts'
import { fmtNum, fmtPct, fmtTime, tone } from '../lib/format.ts'
import { useStatus } from '../lib/status.ts'

const params = (p: Record<string, unknown>) =>
  Object.entries(p)
    .map(([k, v]) => `${k}=${v}`)
    .join(' ')

function BookTable({ book, onOptimize, onChanged }: { book: Record<string, BookEntry>; onOptimize: (s: string) => void; onChanged: () => void }) {
  const confirm = useConfirm()
  const toast = useToast()
  return (
    <table className="tabular w-full text-[12.5px]">
      <thead>
        <tr className="text-left text-fg-3">
          <th className="pb-2 font-medium">Symbol</th>
          <th className="pb-2 font-medium">Strategy</th>
          <th className="pb-2 font-medium">Version</th>
          <th className="pb-2 text-right font-medium">Holdout Sharpe</th>
          <th className="pb-2 text-right font-medium">Return</th>
          <th className="pb-2 text-right font-medium">Max DD</th>
          <th className="pb-2 text-right font-medium">Trades</th>
          <th className="pb-2 pl-4 font-medium">Promoted</th>
          <th className="pb-2" />
        </tr>
      </thead>
      <tbody>
        {Object.entries(book).map(([sym, e]) => {
          const h = e.metrics?.holdout
          return (
            <tr key={sym} className="border-t border-line align-middle">
              <td className="py-2.5 font-medium text-fg">{sym}</td>
              <td className="py-2.5">
                <div className="text-fg">{e.strategy}</div>
                <div className="font-mono text-[11px] text-fg-3">{params(e.params)}</div>
              </td>
              <td className="py-2.5">
                <Pill tone={e.source === 'default' ? 'muted' : e.source === 'agent' ? 'info' : 'accent'}>
                  v{e.version} · {e.source}
                </Pill>
              </td>
              <td className="py-2.5 text-right">{h ? fmtNum(h.sharpe) : '—'}</td>
              <td className={cn('py-2.5 text-right', h && (h.total_return >= 0 ? 'text-ok' : 'text-danger'))}>{h ? fmtPct(h.total_return, 1, true) : '—'}</td>
              <td className="py-2.5 text-right">{h ? fmtPct(h.max_drawdown, 1) : '—'}</td>
              <td className="py-2.5 text-right">{h?.trades ?? '—'}</td>
              <td className="py-2.5 pl-4 text-fg-3">{e.promoted_at ? fmtTime(e.promoted_at) : 'never'}</td>
              <td className="py-2.5">
                <div className="flex justify-end gap-1.5">
                  <GlassButton size="sm" onClick={() => onOptimize(sym)}>
                    <IconSparkles /> Optimise
                  </GlassButton>
                  <GlassButton
                    size="sm"
                    variant="ghost"
                    disabled={!e.history?.length}
                    title={e.history?.length ? `Back to ${e.history[e.history.length - 1].strategy}` : 'No earlier version'}
                    onClick={async () => {
                      const prev = e.history![e.history!.length - 1]
                      const c = await confirm({ title: `Roll back ${sym}?`, confirmLabel: 'Roll back', body: `Switch from ${e.strategy} (v${e.version}) back to ${prev.strategy} ${params(prev.params)}.` })
                      if (!c.ok) return
                      try {
                        await post('/api/rollback', { symbol: sym })
                        toast('ok', `${sym} rolled back to ${prev.strategy}`)
                        onChanged()
                      } catch (err) {
                        toast('danger', String(err))
                      }
                    }}
                  >
                    <IconArrowBackUp /> Roll back
                  </GlassButton>
                </div>
              </td>
            </tr>
          )
        })}
      </tbody>
    </table>
  )
}

function CandidateRow({ c, best }: { c: Candidate; best?: boolean }) {
  return (
    <tr className="border-t border-line">
      <td className="py-2">
        <span className={cn(best && 'font-medium text-fg')}>{c.strategy}</span>
        <div className="font-mono text-[11px] text-fg-3">{params(c.params)}</div>
      </td>
      <td className="py-2 text-right">{fmtNum(c.train.sharpe)}</td>
      <td className="py-2 text-right">{fmtPct(c.train.total_return, 1, true)}</td>
      <td className="py-2 text-right">{fmtPct(c.train.max_drawdown, 1)}</td>
      <td className="py-2 text-right">{c.train.trades}</td>
    </tr>
  )
}

function OptimizePanel({ symbol, onDone, onClose }: { symbol: string; onDone: () => void; onClose: () => void }) {
  const [rep, setRep] = useState<OptimizeReport | null>(null)
  const [err, setErr] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)
  const confirm = useConfirm()
  const toast = useToast()

  const run = async (promote: boolean) => {
    setBusy(true)
    setErr(null)
    try {
      const r = await post<OptimizeReport>('/api/optimize', { symbol, promote })
      setRep(r)
      if (promote) {
        toast(r.promoted ? 'ok' : 'info', r.promoted ? `${symbol} now trades ${r.best?.strategy}` : `Not promoted: ${r.reason}`)
        onDone()
      }
    } catch (e) {
      setErr(e instanceof Error ? e.message : String(e))
    } finally {
      setBusy(false)
    }
  }
  useEffect(() => {
    setRep(null)
    void run(false)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [symbol])

  const h = rep?.best?.holdout
  const passes = !!rep && rep.passes && !rep.promoted

  return (
    <GlassCard className="animate-rise p-4">
      <Section
        title={`Walk-forward search · ${symbol}`}
        action={
          <div className="flex gap-2">
            <GlassButton
              size="sm"
              variant="primary"
              disabled={busy || !passes}
              title={passes ? 'Switch to the challenger' : 'Only a challenger that passes the holdout gate can be promoted'}
              onClick={async () => {
                const c = await confirm({
                  title: `Promote for ${symbol}?`,
                  confirmLabel: 'Promote',
                  body: `The search re-runs and ${rep?.best?.strategy} is promoted only if it still passes the holdout gate. The previous version stays available for roll-back.`
                })
                if (c.ok) await run(true)
              }}
            >
              <IconSparkles /> Promote
            </GlassButton>
            <GlassButton size="sm" variant="ghost" onClick={onClose}>
              Close
            </GlassButton>
          </div>
        }
      >
        {busy && !rep && <div className="shimmer h-32 rounded-lg" aria-label="Searching" />}
        {err && <Banner tone="danger" title="Search failed">{err}</Banner>}
        {rep && (
          <div className="grid grid-cols-[minmax(0,1fr)_minmax(0,1.2fr)] gap-5">
            <div className="flex flex-col gap-3">
              <Banner tone={rep.promoted ? 'info' : passes ? 'info' : 'warn'} title={rep.promoted ? 'Promoted' : passes ? 'Challenger passes the gate' : 'No change recommended'}>
                {rep.reason}
              </Banner>
              {rep.best && (
                <KeyValue
                  labelWidth={130}
                  rows={[
                    { label: 'Incumbent', value: `${rep.incumbent.strategy} ${params(rep.incumbent.params)}` },
                    { label: 'Incumbent holdout', value: rep.incumbent_score == null ? '—' : fmtNum(rep.incumbent_score) },
                    { label: 'Challenger', value: `${rep.best.strategy} ${params(rep.best.params)}` },
                    { label: 'Challenger holdout', value: rep.best.holdout_score == null ? '—' : fmtNum(rep.best.holdout_score) },
                    { label: 'Holdout return', value: h ? fmtPct(h.total_return, 1, true) : 'not tested' },
                    { label: 'Holdout max DD', value: h ? fmtPct(h.max_drawdown, 1) : '—' },
                    { label: 'Holdout trades', value: h ? String(h.trades) : '—' }
                  ]}
                />
              )}
              <p className="text-[11.5px] text-fg-4">The challenger is chosen on training data only, then tested once on the last 30% of history it never saw.</p>
            </div>
            <div>
              <div className="mb-1.5 text-[12px] text-fg-3">Top candidates by training score</div>
              <table className="tabular w-full text-[12px]">
                <thead>
                  <tr className="text-left text-fg-3">
                    <th className="pb-1.5 font-medium">Candidate</th>
                    <th className="pb-1.5 text-right font-medium">Sharpe</th>
                    <th className="pb-1.5 text-right font-medium">Return</th>
                    <th className="pb-1.5 text-right font-medium">Max DD</th>
                    <th className="pb-1.5 text-right font-medium">Trades</th>
                  </tr>
                </thead>
                <tbody>
                  {rep.leaderboard.map((c, i) => (
                    <CandidateRow key={i} c={c} best={i === 0} />
                  ))}
                </tbody>
              </table>
            </div>
          </div>
        )}
      </Section>
    </GlassCard>
  )
}

function BacktestChart({ r }: { r: BacktestResponse }) {
  const option = useMemo(() => {
    const t = chartTokens()
    const end = (name: string) => ({ show: true, color: t.fg2, formatter: () => name })
    return {
      ...baseOption(),
      legend: { top: 0, left: 0, itemWidth: 14, itemHeight: 3, icon: 'rect', textStyle: { color: t.fg2 } },
      grid: { left: 8, right: 90, top: 30, bottom: 8, containLabel: true },
      tooltip: { ...(baseOption().tooltip as object), valueFormatter: (v: number) => `${((v - 1) * 100).toFixed(1)}%` },
      xAxis: timeAxis(),
      yAxis: valueAxis(v => `${((v - 1) * 100).toFixed(0)}%`, 'left'),
      series: [
        { name: 'Strategy', type: 'line', showSymbol: false, data: r.curve.map(p => [p[0], p[1]]), lineStyle: { width: 2, color: t.s1 }, itemStyle: { color: t.s1 }, endLabel: end('Strategy') },
        { name: 'Buy & hold', type: 'line', showSymbol: false, data: r.curve.map(p => [p[0], p[2]]), lineStyle: { width: 2, color: t.s2 }, itemStyle: { color: t.s2 }, endLabel: end('Buy & hold') }
      ]
    }
  }, [r])
  return <EChart option={option} height={280} ariaLabel={`Backtest growth: strategy ${fmtPct(r.result.total_return, 1, true)} vs buy and hold ${fmtPct(r.buy_and_hold.total_return, 1, true)}`} />
}

function BacktestLab({ symbols, strategies, book }: { symbols: string[]; strategies: StrategyDef[]; book: Record<string, BookEntry> }) {
  const [sym, setSym] = useState(symbols[0] ?? '')
  const [strat, setStrat] = useState(book[symbols[0]]?.strategy ?? strategies[0]?.name ?? '')
  const def = strategies.find(s => s.name === strat)
  const [vals, setVals] = useState<Record<string, string>>({})
  const [bars, setBars] = useState('2000')
  const [res, setRes] = useState<BacktestResponse | null>(null)
  const [busy, setBusy] = useState(false)
  const [err, setErr] = useState<string | null>(null)

  useEffect(() => {
    const cur = book[sym]
    const base = cur && cur.strategy === strat ? cur.params : def?.defaults ?? {}
    setVals(Object.fromEntries(Object.entries(base).map(([k, v]) => [k, String(v)])))
  }, [strat, sym, def, book])

  const run = async () => {
    setBusy(true)
    setErr(null)
    try {
      const p = Object.fromEntries(Object.entries(vals).map(([k, v]) => [k, Number(v)]))
      if (Object.values(p).some(v => !Number.isFinite(v))) throw new Error('All parameters must be numbers')
      setRes(await post<BacktestResponse>('/api/backtest', { symbol: sym, strategy: strat, params: p, bars: Number(bars) }))
    } catch (e) {
      setErr(e instanceof Error ? e.message : String(e))
    } finally {
      setBusy(false)
    }
  }
  const m = res?.result

  return (
    <GlassCard className="p-4">
      <Section title="Backtest lab" action={<span className="text-[11.5px] text-fg-4">Fees and slippage included · read-only, changes nothing</span>}>
        <div className="flex flex-wrap items-end gap-3">
          <Field label="Symbol">
            <Select label="Symbol" value={sym} onChange={setSym} options={symbols.map(s => ({ value: s, label: s }))} />
          </Field>
          <Field label="Strategy">
            <Select label="Strategy" value={strat} onChange={setStrat} options={strategies.map(s => ({ value: s.name, label: s.name }))} />
          </Field>
          {Object.keys(vals).map(k => (
            <Field key={k} label={k}>
              <TextInput className="w-20 tabular" inputMode="decimal" value={vals[k]} onChange={e => setVals(v => ({ ...v, [k]: e.target.value }))} aria-label={`${k} parameter`} />
            </Field>
          ))}
          <Field label="History">
            <Select label="History length" value={bars} onChange={setBars} options={['500', '1000', '2000', '5000'].map(v => ({ value: v, label: `${v} bars` }))} />
          </Field>
          <GlassButton variant="primary" disabled={busy || !sym || !strat} onClick={run}>
            <IconPlayerPlay /> {busy ? 'Running…' : 'Run backtest'}
          </GlassButton>
        </div>
        {def && <p className="text-[12px] text-fg-3">{def.description}</p>}
        {err && <Banner tone="danger" title="Backtest failed">{err}</Banner>}
        {m && res && (
          <div className="animate-rise mt-1 flex flex-col gap-3">
            <div className="grid grid-cols-6 gap-3">
              <Stat label="Return" value={fmtPct(m.total_return, 1, true)} valueTone={tone(m.total_return)} sub={`Buy & hold ${fmtPct(res.buy_and_hold.total_return, 1, true)}`} />
              <Stat label="Sharpe" value={fmtNum(m.sharpe)} sub={`B&H ${fmtNum(res.buy_and_hold.sharpe)}`} />
              <Stat label="Max drawdown" value={fmtPct(m.max_drawdown, 1)} sub={`B&H ${fmtPct(res.buy_and_hold.max_drawdown, 1)}`} />
              <Stat label="Trades" value={String(m.trades)} sub={`Win rate ${fmtPct(m.win_rate, 0)}`} />
              <Stat label="Profit factor" value={m.profit_factor == null ? '∞' : fmtNum(m.profit_factor)} sub={`Exposure ${fmtPct(m.exposure, 0)}`} />
              <Stat label="Costs" value={fmtPct(m.fees_paid_pct, 2)} sub={`${m.bars} bars`} />
            </div>
            <BacktestChart r={res} />
          </div>
        )}
      </Section>
    </GlassCard>
  )
}

export function StrategiesPage() {
  const { status } = useStatus()
  const book = usePoll<Record<string, BookEntry>>('/api/book', 20_000)
  const strategies = usePoll<StrategyDef[]>('/api/strategies', 0)
  const [opt, setOpt] = useState<string | null>(null)

  return (
    <div className="flex h-full flex-col">
      <PageHeader icon={<IconFlask />} title="Strategies" subtitle="What each symbol trades, how it was chosen, and a lab to test alternatives" />
      <div className="min-h-0 flex-1 overflow-y-auto px-6 pb-6">
        <div className="flex flex-col gap-4">
          <GlassCard className="p-4">
            <Section title="Strategy book" action={<span className="text-[11.5px] text-fg-4">Re-optimised automatically every day; promotions need to pass the holdout gate</span>}>
              {book.data ? <BookTable book={book.data} onOptimize={setOpt} onChanged={book.refresh} /> : <div className="shimmer h-24 rounded-lg" />}
            </Section>
          </GlassCard>
          {opt && <OptimizePanel key={opt} symbol={opt} onDone={book.refresh} onClose={() => setOpt(null)} />}
          {book.data && strategies.data && status ? (
            <BacktestLab symbols={status.symbols} strategies={strategies.data} book={book.data} />
          ) : (
            <EmptyGlass title="Loading strategies…" />
          )}
        </div>
      </div>
    </div>
  )
}
