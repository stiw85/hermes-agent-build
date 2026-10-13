import { IconChartCandle, IconRefresh } from '@tabler/icons-react'
import { useEffect, useMemo, useState } from 'react'
import { baseOption, chartTokens, EChart, valueAxis } from '../components/Chart.tsx'
import { Chips, EmptyGlass, GlassButton, GlassCard, KeyValue, PageHeader, Pill, Section, Select } from '../components/glass.tsx'
import { usePoll, type Candles, type Decision, type KeyLevel } from '../lib/api.ts'
import { cn } from '../lib/cn.ts'
import { fmtNum, fmtPct, fmtPrice, fmtTime } from '../lib/format.ts'
import { useStatus } from '../lib/status.ts'

function sma(xs: number[], n: number): (number | null)[] {
  const out: (number | null)[] = []
  let sum = 0
  xs.forEach((x, i) => {
    sum += x
    if (i >= n) sum -= xs[i - n]
    out.push(i >= n - 1 ? sum / n : null)
  })
  return out
}

/** Nearest few key levels on each side of price (the chart gets cluttered beyond that). */
function nearbyLevels(c: Candles, each = 3): KeyLevel[] {
  const ctx = c.snapshot?.context
  const px = ctx?.price ?? c.snapshot?.last
  if (!ctx?.levels || !px) return []
  const above = ctx.levels.filter(z => z.price > px).sort((a, b) => a.price - b.price).slice(0, each)
  const below = ctx.levels.filter(z => z.price <= px).sort((a, b) => b.price - a.price).slice(0, each)
  return [...below, ...above]
}

function CandleChart({ c }: { c: Candles }) {
  const option = useMemo(() => {
    const t = chartTokens()
    const ts = c.candles.map(r => r[0])
    const closes = c.candles.map(r => r[4])
    const ctx = c.snapshot?.context
    const em = ctx?.expected_move
    const step = ts.length > 1 ? ts[ts.length - 1] - ts[ts.length - 2] : 3_600_000
    const ahead = em ? Math.round(em.bars) : 0
    const future = Array.from({ length: ahead }, (_, i) => ts[ts.length - 1] + step * (i + 1))
    const labels = [...ts, ...future].map(x => fmtTime(new Date(x).toISOString()))
    const pad = (xs: (number | null)[]) => [...xs, ...Array(ahead).fill(null)]
    // a fill happens after its bar closes: attach it to the last bar that opened at or before it
    const idxFor = (iso: string) => {
      const ms = new Date(iso).getTime()
      let lo = 0
      let hi = ts.length - 1
      if (ms < ts[0]) return -1
      while (lo < hi) {
        const mid = (lo + hi + 1) >> 1
        if (ts[mid] <= ms) lo = mid
        else hi = mid - 1
      }
      return lo
    }
    const buys: [number, number, string][] = []
    const sells: [number, number, string][] = []
    for (const f of c.fills) {
      const i = idxFor(f.ts)
      if (i < 0) continue
      ;(f.side === 'buy' ? buys : sells).push([i, f.price, `${f.side === 'buy' ? 'Buy' : 'Sell'} ${f.qty} @ ${fmtPrice(f.price)} (${f.strategy})`])
    }
    // expected-move cone: ±1σ / ±2σ from the last close, widening with √bars (log-normal, no drift)
    const last = closes[closes.length - 1]
    const sBar = em ? em.sigma_pct / 100 / Math.sqrt(Math.max(em.bars, 1)) : 0
    const cone = (k: number) =>
      em ? [...Array(ts.length - 1).fill(null), last, ...future.map((_, i) => last * Math.exp(k * sBar * Math.sqrt(i + 1)))] : []
    const px = ctx?.price ?? last
    const levelLines = nearbyLevels(c).map(z => {
      const res = z.price > px
      const round = z.kinds.length === 1 && z.kinds[0] === 'round number'
      return {
        yAxis: z.price,
        lineStyle: { color: res ? t.danger : t.ok, type: 'dashed', width: 1, opacity: round ? 0.35 : 0.7 },
        label: { formatter: `${fmtPrice(z.price)}  ${z.kinds[0]}${z.kinds.length > 1 ? ` +${z.kinds.length - 1}` : ''}`, color: t.fg3, fontSize: 10, position: 'insideEndTop' }
      }
    })
    const hasCvd = Boolean(c.cvd && c.cvd.length === ts.length)
    const total = ts.length + ahead
    const start = Math.max(0, 100 - (180 / Math.max(1, total)) * 100)
    const xAxisBase = { type: 'category', data: labels, boundaryGap: true, axisLine: { lineStyle: { color: t.line } }, axisTick: { show: false } }
    return {
      ...baseOption(),
      legend: {
        top: 0, left: 0, itemWidth: 14, itemHeight: 3, icon: 'rect', textStyle: { color: t.fg2 },
        data: ['SMA 50', 'SMA 200', 'Buy', 'Sell', ...(em ? ['±1σ', '±2σ'] : []), ...(hasCvd ? ['CVD'] : [])]
      },
      grid: hasCvd
        ? [{ left: 8, right: 16, top: 30, bottom: '27%', containLabel: true }, { left: 8, right: 16, top: '77%', bottom: 8, containLabel: true }]
        : { left: 8, right: 16, top: 30, bottom: 8, containLabel: true },
      tooltip: {
        ...(baseOption().tooltip as object),
        valueFormatter: (v: number) => (typeof v === 'number' ? fmtPrice(v) : String(v))
      },
      xAxis: hasCvd
        ? [{ ...xAxisBase, axisLabel: { show: false } }, { ...xAxisBase, gridIndex: 1, axisLabel: { color: t.fg3, hideOverlap: true } }]
        : { ...xAxisBase, axisLabel: { color: t.fg3, hideOverlap: true } },
      yAxis: hasCvd
        ? [valueAxis(v => fmtPrice(v)), { ...valueAxis(v => fmtNum(v, 0)), gridIndex: 1, splitNumber: 2 }]
        : valueAxis(v => fmtPrice(v)),
      dataZoom: [{ type: 'inside', start, end: 100, minValueSpan: 20, xAxisIndex: hasCvd ? [0, 1] : [0] }],
      series: [
        {
          name: c.symbol,
          type: 'candlestick',
          data: [...c.candles.map(r => [r[1], r[4], r[3], r[2]]), ...Array(ahead).fill('-')],
          itemStyle: { color: t.ok, color0: t.danger, borderColor: t.ok, borderColor0: t.danger, borderWidth: 1 },
          barMaxWidth: 10,
          markLine: levelLines.length ? { symbol: 'none', silent: true, data: levelLines, animation: false } : undefined
        },
        { name: 'SMA 50', type: 'line', data: pad(sma(closes, 50)), showSymbol: false, lineStyle: { width: 2, color: t.s1 }, itemStyle: { color: t.s1 } },
        { name: 'SMA 200', type: 'line', data: pad(sma(closes, 200)), showSymbol: false, lineStyle: { width: 2, color: t.s2 }, itemStyle: { color: t.s2 } },
        ...(em
          ? [
              { name: '±1σ', type: 'line', data: cone(1), showSymbol: false, connectNulls: false, lineStyle: { width: 1.5, type: 'dashed', color: t.fg2 }, itemStyle: { color: t.fg2 } },
              { name: '±1σ', type: 'line', data: cone(-1), showSymbol: false, lineStyle: { width: 1.5, type: 'dashed', color: t.fg2 }, itemStyle: { color: t.fg2 } },
              { name: '±2σ', type: 'line', data: cone(2), showSymbol: false, lineStyle: { width: 1, type: 'dotted', color: t.fg3 }, itemStyle: { color: t.fg3 } },
              { name: '±2σ', type: 'line', data: cone(-2), showSymbol: false, lineStyle: { width: 1, type: 'dotted', color: t.fg3 }, itemStyle: { color: t.fg3 } }
            ]
          : []),
        {
          name: 'Buy',
          type: 'scatter',
          symbol: 'triangle',
          symbolSize: 15,
          itemStyle: { color: t.ok, borderColor: t.surface, borderWidth: 2 },
          data: buys.map(b => ({ value: [b[0], b[1]], tip: b[2] })),
          tooltip: { trigger: 'item', formatter: (p: { data: { tip: string } }) => p.data.tip }
        },
        {
          name: 'Sell',
          type: 'scatter',
          symbol: 'triangle',
          symbolRotate: 180,
          symbolSize: 15,
          itemStyle: { color: t.danger, borderColor: t.surface, borderWidth: 2 },
          data: sells.map(b => ({ value: [b[0], b[1]], tip: b[2] })),
          tooltip: { trigger: 'item', formatter: (p: { data: { tip: string } }) => p.data.tip }
        },
        ...(hasCvd
          ? [{ name: 'CVD', type: 'line', xAxisIndex: 1, yAxisIndex: 1, data: pad(c.cvd as number[]), showSymbol: false, lineStyle: { width: 1.5, color: t.s2 }, itemStyle: { color: t.s2 }, areaStyle: { color: t.s2, opacity: 0.08 } }]
          : [])
      ]
    }
  }, [c])
  return (
    <EChart
      option={option}
      height="100%"
      className="min-h-[360px]"
      ariaLabel={`${c.symbol} ${c.timeframe} candlestick chart with SMA 50 and SMA 200, nearby key levels, the expected-move cone for the next bars${c.cvd ? ', cumulative volume delta' : ''} and the bot's fills`}
    />
  )
}

function ContextCard({ c }: { c: Candles }) {
  const ctx = c.snapshot?.context
  if (!ctx || ctx.error) return null
  const em = ctx.expected_move
  const z = ctx.stretch_z_24
  const pct = (v: number | null | undefined) => (v == null ? '' : ` (${v > 0 ? '+' : ''}${v.toFixed(2)}%)`)
  const touch = (k: string) => {
    const v = Object.entries(ctx).find(([key]) => key.startsWith(`p_touch_${k}`))?.[1]
    return typeof v === 'number' ? ` · ${Math.round(v * 100)}% touch` : ''
  }
  const flow = ctx.order_flow
  return (
    <GlassCard className="p-4">
      <Section title="Levels & volatility">
        <KeyValue
          labelWidth={92}
          rows={[
            ...(ctx.at_level ? [{ label: 'At level', value: <span className="text-[12px] text-warn">{ctx.at_level}</span> }] : []),
            { label: 'Resistance', value: <span className="text-[12px]" title={`${ctx.nearest_resistance ?? ''}${touch('resistance')}`}>{(ctx.nearest_resistance ?? '—') + pct(ctx.resistance_dist_pct)}</span> },
            { label: 'Support', value: <span className="text-[12px]" title={`${ctx.nearest_support ?? ''}${touch('support')}`}>{(ctx.nearest_support ?? '—') + pct(ctx.support_dist_pct)}</span> },
            ...(em ? [{ label: `Next ${em.bars} bars`, value: `±${em.sigma_pct.toFixed(2)}% typical (1σ)` }] : []),
            ...(z != null ? [{ label: 'Last 24 bars', value: <span className={cn(Math.abs(z) > 2 ? 'text-warn' : '')}>{`${z > 0 ? '+' : ''}${z.toFixed(1)}σ move${Math.abs(z) > 2 ? ' (stretched)' : ''}`}</span> }] : [])
          ]}
        />
      </Section>
      {flow && (
        <Section title="Order flow" className="mt-3">
          <KeyValue
            labelWidth={92}
            rows={[
              { label: 'Net aggression', value: <span className={cn(flow.net_aggression_24b > 0 ? 'text-ok' : flow.net_aggression_24b < 0 ? 'text-danger' : '')}>{`${flow.net_aggression_24b > 0 ? '+' : ''}${Math.round(flow.net_aggression_24b * 100)}% (24 bars)`}</span> },
              { label: 'CVD divergence', value: <span className="text-[12px]">{flow.cvd_divergence}</span> },
              { label: 'Last bar', value: <span className="text-[12px]">{flow.last_bar}</span> }
            ]}
          />
        </Section>
      )}
    </GlassCard>
  )
}

export function MarketsPage() {
  const { status } = useStatus()
  const symbols = status?.symbols ?? []
  const [sym, setSym] = useState(symbols[0] ?? '')
  const [bars, setBars] = useState('300')
  useEffect(() => {
    if (!sym && symbols[0]) setSym(symbols[0])
  }, [sym, symbols])
  const candles = usePoll<Candles>(sym ? `/api/candles?symbol=${encodeURIComponent(sym)}&bars=${bars}` : null, 30_000)
  const decisions = usePoll<Decision[]>(sym ? `/api/decisions?symbol=${encodeURIComponent(sym)}&n=12` : null, 15_000)
  const c = candles.data
  const s = c?.snapshot
  const pos = status?.positions[sym]

  return (
    <div className="flex h-full flex-col">
      <PageHeader
        icon={<IconChartCandle />}
        title="Markets"
        subtitle={`Closed ${status?.timeframe ?? ''} bars from ${status?.broker ?? 'the broker'}, with the bot's own fills`}
        actions={
          <>
            <Select label="History length" value={bars} onChange={setBars} options={['150', '300', '600', '1000'].map(v => ({ value: v, label: `${v} bars` }))} />
            <GlassButton size="icon" aria-label="Refresh" onClick={candles.refresh}>
              <IconRefresh />
            </GlassButton>
          </>
        }
      />
      <div className="px-6 pb-3">
        <Chips items={symbols.map(x => ({ id: x, label: x }))} value={sym} onChange={setSym} />
      </div>
      <div className="grid min-h-0 flex-1 grid-cols-[minmax(0,1fr)_300px] gap-4 px-6 pb-6">
        <GlassCard className="flex min-h-0 flex-col p-4">
          {candles.error && !c ? (
            <EmptyGlass title="Couldn't load market data" description={candles.error} />
          ) : c ? (
            <CandleChart c={c} />
          ) : (
            <div className="shimmer h-full rounded-lg" />
          )}
        </GlassCard>
        <div className="flex min-h-0 flex-col gap-4 overflow-y-auto">
          <GlassCard className="p-4">
            <Section title={sym || 'Market'} action={s && <Pill tone={s.trend_sma50_200 === 'up' ? 'ok' : s.trend_sma50_200 === 'down' ? 'danger' : 'muted'}>trend {s.trend_sma50_200}</Pill>}>
              {s ? (
                <KeyValue
                  labelWidth={110}
                  rows={[
                    { label: 'Last', value: fmtPrice(s.last) },
                    { label: '24 bars', value: <span className={cn((s.chg_24 ?? 0) >= 0 ? 'text-ok' : 'text-danger')}>{fmtPct(s.chg_24, 2, true)}</span> },
                    { label: '100 bars', value: <span className={cn((s.chg_100 ?? 0) >= 0 ? 'text-ok' : 'text-danger')}>{fmtPct(s.chg_100, 2, true)}</span> },
                    { label: 'Volatility (yr)', value: fmtPct(s.vol_annual, 1) },
                    { label: 'RSI 14', value: fmtNum(s.rsi14, 1) },
                    { label: 'ATR', value: fmtPct(s.atr_pct, 2) },
                    { label: '100-bar range', value: `${fmtPrice(s.range_100[0])} – ${fmtPrice(s.range_100[1])}` }
                  ]}
                />
              ) : (
                <div className="shimmer h-32 rounded-lg" />
              )}
            </Section>
          </GlassCard>
          {c && <ContextCard c={c} />}
          <GlassCard className="p-4">
            <Section title="Trading it with">
              {c ? (
                <KeyValue
                  labelWidth={90}
                  rows={[
                    { label: 'Strategy', value: c.strategy.strategy },
                    { label: 'Params', value: <span className="font-mono text-[11.5px]">{JSON.stringify(c.strategy.params)}</span> },
                    { label: 'Version', value: `v${c.strategy.version} · ${c.strategy.source}` },
                    { label: 'Position', value: pos ? `${pos.qty > 0 ? 'Long' : 'Short'} ${Number(pos.qty.toPrecision(6))}` : 'Flat' },
                    ...(c.jev
                      ? [
                          {
                            label: 'JEV now',
                            value: c.jev.error ? (
                              <span className="text-warn">check failed</span>
                            ) : (
                              <span title={`as of ${fmtTime(c.jev.ts)} · ${c.jev.mode}`}>
                                {(c.jev.regime ?? '?').replace('_', ' ')} · fit {c.jev.p == null ? '—' : `${Math.round(c.jev.p * 100)}%`}
                                {c.jev.applied ? ' · standing aside' : ''}
                              </span>
                            )
                          }
                        ]
                      : [])
                  ]}
                />
              ) : (
                <div className="shimmer h-20 rounded-lg" />
              )}
            </Section>
          </GlassCard>
          <GlassCard className="p-4">
            <Section title="Recent decisions">
              {(decisions.data ?? []).length === 0 ? (
                <div className="text-[12px] text-fg-3">No decisions yet for {sym}.</div>
              ) : (
                <ul className="flex flex-col">
                  {decisions.data!.map(d => (
                    <li key={d.id} className="border-t border-line py-1.5 first:border-t-0">
                      <div className="flex items-center justify-between gap-2 text-[12px]">
                        <span className={cn('truncate', d.action.startsWith('buy') ? 'text-ok' : d.action.startsWith('sell') ? 'text-danger' : 'text-fg-2')}>{d.action}</span>
                        <span className="tabular shrink-0 text-[11px] text-fg-4">{fmtTime(d.ts)}</span>
                      </div>
                      <div className="selectable truncate text-[11px] text-fg-3" title={`${d.signal_reason}\n${d.risk_notes}${d.llm_note ? `\nLLM: ${d.llm_note}` : ''}`}>
                        target {d.target >= 0 ? '+' : ''}
                        {d.target.toFixed(2)}
                        {d.jev_p != null && ` · JEV ${Math.round(d.jev_p * 100)}%`}
                        {d.llm_verdict && ` · LLM ${d.llm_verdict}`}
                        {d.risk_notes && ` · ${d.risk_notes}`}
                      </div>
                    </li>
                  ))}
                </ul>
              )}
            </Section>
          </GlassCard>
        </div>
      </div>
    </div>
  )
}
