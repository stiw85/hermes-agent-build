import { IconArrowUp, IconBrain, IconBulb, IconFilter, IconGauge, IconMessageCircle, IconNotebook, IconPlayerPlay, IconTool, IconTrash } from '@tabler/icons-react'
import { useEffect, useRef, useState } from 'react'
import Markdown from 'react-markdown'
import remarkGfm from 'remark-gfm'
import { Banner, EmptyGlass, GlassButton, GlassCard, PageHeader, Pill, Section, Select, Stat, Tabs } from '../components/glass.tsx'
import { HermesMark } from '../components/Shell.tsx'
import { get, post, usePoll, type FilterName, type FilterReplay, type FilterReport, type JevReport, type StrategyDef } from '../lib/api.ts'
import { cn } from '../lib/cn.ts'
import { fmtNum, fmtPct, fmtSigned, fmtTime } from '../lib/format.ts'
import { useStatus } from '../lib/status.ts'

interface Msg {
  role: 'user' | 'assistant' | 'error'
  text: string
  tools?: { name: string; args: unknown }[]
}

const SUGGESTIONS = ['How are we doing this week?', 'Is the current strategy still right for each symbol?', 'What have you learned so far?']

function Chat({ enabled }: { enabled: boolean }) {
  const [msgs, setMsgs] = useState<Msg[]>([])
  const [text, setText] = useState('')
  const [busy, setBusy] = useState(false)
  const end = useRef<HTMLDivElement>(null)
  useEffect(() => end.current?.scrollIntoView({ behavior: 'smooth' }), [msgs, busy])

  if (!enabled) {
    return (
      <EmptyGlass
        className="h-full"
        icon={<IconMessageCircle />}
        title="The LLM brain is off"
        description={
          <>
            The bot trades fine without it. To chat, review trades and self-reflect, set <code className="font-mono">llm.enabled: true</code> in config.yaml (Ollama works free and locally),
            put the key in .env if your provider needs one, then restart the backend from Settings.
          </>
        }
      />
    )
  }

  const send = async (m: string) => {
    const msg = m.trim()
    if (!msg || busy) return
    setText('')
    setMsgs(xs => [...xs, { role: 'user', text: msg }])
    setBusy(true)
    try {
      const r = await post<{ reply: string; tools: { name: string; args: unknown }[] }>('/api/chat', { message: msg, reset: msgs.length === 0 })
      setMsgs(xs => [...xs, { role: 'assistant', text: r.reply || '(no reply)', tools: r.tools }])
    } catch (err) {
      setMsgs(xs => [...xs, { role: 'error', text: err instanceof Error ? err.message : String(err) }])
    } finally {
      setBusy(false)
    }
  }

  return (
    <div className="flex h-full min-h-0 flex-col">
      <div className="min-h-0 flex-1 overflow-y-auto pr-1">
        {msgs.length === 0 ? (
          <div className="flex h-full flex-col items-center justify-center gap-4 text-center">
            <HermesMark size={44} />
            <div className="text-[13px] text-fg-2">Ask about performance, strategies or the market. The agent reads the journal and backtests before answering.</div>
            <div className="flex flex-wrap justify-center gap-2">
              {SUGGESTIONS.map(s => (
                <button key={s} type="button" className="rounded-full border border-line bg-white/5 px-3 py-1.5 text-[12px] text-fg-2 hover:bg-white/10 hover:text-fg" onClick={() => void send(s)}>
                  {s}
                </button>
              ))}
            </div>
            <p className="max-w-md text-[11.5px] text-fg-4">It can request a strategy promotion (still gated) and edit its lessons. It cannot place orders or change risk limits from here.</p>
          </div>
        ) : (
          <div className="flex flex-col gap-3">
            {msgs.map((m, i) => (
              <div key={i} className={cn('flex', m.role === 'user' ? 'justify-end' : 'justify-start')}>
                <div
                  className={cn(
                    'max-w-[88%] rounded-xl px-3.5 py-2.5 text-[13px]',
                    m.role === 'user' ? 'bg-accent text-accent-fg' : m.role === 'error' ? 'border border-danger/40 bg-danger/10 text-danger' : 'glass-card text-fg'
                  )}
                >
                  {m.tools && m.tools.length > 0 && (
                    <div className="mb-2 flex flex-wrap gap-1">
                      {m.tools.map((t, j) => (
                        <Pill key={j} className="h-5 text-[10.5px]" title={JSON.stringify(t.args)}>
                          <IconTool size={11} /> {t.name}
                        </Pill>
                      ))}
                    </div>
                  )}
                  {m.role === 'assistant' ? (
                    <div className="prose-hermes">
                      <Markdown remarkPlugins={[remarkGfm]}>{m.text}</Markdown>
                    </div>
                  ) : (
                    <span className="selectable whitespace-pre-wrap">{m.text}</span>
                  )}
                </div>
              </div>
            ))}
            {busy && <div className="shimmer h-10 w-48 rounded-xl" aria-label="Thinking" />}
            <div ref={end} />
          </div>
        )}
      </div>
      <form
        className="glass-input mt-3 flex items-end gap-2 rounded-xl p-2"
        onSubmit={e => {
          e.preventDefault()
          void send(text)
        }}
      >
        <textarea
          rows={1}
          value={text}
          onChange={e => setText(e.target.value)}
          onKeyDown={e => {
            if (e.key === 'Enter' && !e.shiftKey) {
              e.preventDefault()
              void send(text)
            }
          }}
          placeholder="Ask Hermes…"
          aria-label="Message"
          className="max-h-32 min-h-9 flex-1 resize-none bg-transparent px-2 py-1.5 text-[13px] outline-none placeholder:text-fg-4"
        />
        {msgs.length > 0 && (
          <GlassButton size="icon" variant="ghost" aria-label="New conversation" onClick={() => setMsgs([])} disabled={busy}>
            <IconTrash />
          </GlassButton>
        )}
        <GlassButton size="icon" variant="primary" type="submit" aria-label="Send" disabled={busy || !text.trim()}>
          <IconArrowUp />
        </GlassButton>
      </form>
    </div>
  )
}

function CheckTable({ title, rows, horizon, note }: { title: string; rows: { bucket: string; n: number; avg_fwd_pct: number | null; up_share: number | null }[]; horizon: number; note: string }) {
  return (
    <div>
      <div className="mb-1.5 text-[12px] text-fg-3">{title}</div>
      <table className="tabular w-full text-[12px]">
        <thead>
          <tr className="text-left text-fg-3">
            <th className="pb-1.5 font-medium">JEV said</th>
            <th className="pb-1.5 text-right font-medium">Bars</th>
            <th className="pb-1.5 text-right font-medium">Next {horizon} bars</th>
            <th className="pb-1.5 text-right font-medium">Went right</th>
          </tr>
        </thead>
        <tbody>
          {rows.map(b => (
            <tr key={b.bucket} className="border-t border-line">
              <td className="py-1.5 text-fg-2">{b.bucket}</td>
              <td className="py-1.5 text-right">{b.n}</td>
              <td className={cn('py-1.5 text-right', b.avg_fwd_pct == null ? 'text-fg-4' : b.avg_fwd_pct > 0 ? 'text-ok' : b.avg_fwd_pct < 0 ? 'text-danger' : 'text-fg-3')}>
                {b.avg_fwd_pct == null ? '—' : `${b.avg_fwd_pct > 0 ? '+' : ''}${b.avg_fwd_pct.toFixed(3)}%`}
              </td>
              <td className="py-1.5 text-right">{b.up_share == null ? '—' : fmtPct(b.up_share, 0)}</td>
            </tr>
          ))}
        </tbody>
      </table>
      <p className="mt-1 text-[11px] text-fg-4">{note}</p>
    </div>
  )
}

function ChecksPanel({ c }: { c: NonNullable<JevReport['checks']> }) {
  const act = c.mode === 'act'
  return (
    <div className="flex flex-col gap-3 border-t border-line pt-3">
      <div className="flex items-center gap-2">
        <span className="text-[13px] font-semibold text-fg">Every-bar checks</span>
        <Pill tone={act ? 'warn' : 'info'} dot className="h-5 text-[10.5px]">
          {act ? 'Act: may stand aside or close' : 'Shadow: watching only'}
        </Pill>
        <span className="ml-auto text-[11.5px] text-fg-3 tabular">
          {c.checks} answers · ${c.cost_usd.toFixed(4)}
          {c.errors ? ` · ${c.errors} errors` : ''}
        </span>
      </div>
      <Banner tone="info" title="Regime / strategy fit">
        {c.regime.recommendation}
      </Banner>
      <CheckTable
        title="Strategy fit: how the strategy's wanted direction then performed"
        rows={c.regime.buckets}
        horizon={c.horizon_bars}
        note="If JEV is useful, low-fit rows should show weaker (or negative) returns than high-fit rows."
      />
      <Banner tone="info" title="Exit check">
        {c.exit.recommendation}
      </Banner>
      <CheckTable
        title="Exit: what holding the position then returned"
        rows={c.exit.buckets}
        horizon={c.horizon_bars}
        note="If JEV is useful, high exit-probability rows should show holding lost money. 'Went right' here means the price kept moving in the position's favour."
      />
      {Object.keys(c.regime.seen).length > 0 && (
        <div className="flex flex-wrap gap-1.5">
          {Object.entries(c.regime.seen).map(([k, v]) => (
            <Pill key={k} className="h-5 text-[10.5px]">
              {k.replace('_', ' ')} · {v}
            </Pill>
          ))}
        </div>
      )}
    </div>
  )
}

function JevPanel() {
  const r = usePoll<JevReport>('/api/jev?n=40', 20_000).data
  if (!r) return <div className="shimmer h-40 rounded-lg" />
  if (!r.enabled) {
    return (
      <EmptyGlass
        icon={<IconGauge />}
        title="JEV is off"
        description={
          <>
            TypeSafe's Jev scores every new entry with a calibrated probability that it's worth taking. Set <code className="font-mono">jev.enabled: true</code> (mode{' '}
            <code className="font-mono">shadow</code>) in config.yaml, put <code className="font-mono">TYPESAFE_API_KEY</code> in .env, check it with{' '}
            <code className="font-mono">hermes-trader jev --test</code>, then restart the backend.
          </>
        }
      />
    )
  }
  const gate = r.mode === 'gate'
  return (
    <div className="flex flex-col gap-3">
      {r.error && (
        <Banner tone="warn" title="JEV is enabled but not running: the bot is trading without it">
          {r.error}
        </Banner>
      )}
      <div className="flex items-center gap-2">
        <Pill tone={gate ? 'warn' : 'info'} dot>
          {gate ? 'Gate: can shrink or veto entries' : 'Shadow: watching only'}
        </Pill>
        <span className="text-[11.5px] text-fg-3">
          entry gate: veto &lt; {r.veto_below} · half size &lt; {r.reduce_below}
        </span>
      </div>
      <div className="grid grid-cols-3 gap-2">
        <Stat label="Scored entries" value={String(r.scored ?? 0)} sub={r.errors ? `${r.taken ?? 0} taken · ${r.errors} errors` : `${r.taken ?? 0} taken`} />
        <Stat label="Closed trades" value={String(r.resolved ?? 0)} sub={`${r.open ?? 0} still open`} />
        <Stat label="If gating" value={fmtSigned(r.what_if_gate_pnl)} valueTone={(r.what_if_gate_pnl ?? 0) > 0 ? 'ok' : (r.what_if_gate_pnl ?? 0) < 0 ? 'danger' : 'muted'} sub={`JEV cost $${(r.cost_usd ?? 0).toFixed(4)}`} />
      </div>
      {r.recommendation && <Banner tone="info" title="Verdict so far">{r.recommendation}</Banner>}
      <div>
        <div className="mb-1.5 flex items-baseline justify-between text-[12px] text-fg-3">
          <span>Calibration on closed trades</span>
          <span className="tabular">
            Brier {fmtNum(r.brier, 3)} vs base rate {fmtNum(r.brier_base_rate, 3)} (lower is better)
          </span>
        </div>
        <table className="tabular w-full text-[12px]">
          <thead>
            <tr className="text-left text-fg-3">
              <th className="pb-1.5 font-medium">JEV probability</th>
              <th className="pb-1.5 text-right font-medium">Trades</th>
              <th className="pb-1.5 text-right font-medium">Avg P</th>
              <th className="pb-1.5 text-right font-medium">Won</th>
              <th className="pb-1.5 text-right font-medium">P&L</th>
            </tr>
          </thead>
          <tbody>
            {(r.buckets ?? []).map(b => (
              <tr key={b.bucket} className="border-t border-line">
                <td className="py-1.5 text-fg-2">{b.bucket}</td>
                <td className="py-1.5 text-right">{b.trades}</td>
                <td className="py-1.5 text-right">{b.avg_p == null ? '—' : fmtPct(b.avg_p, 0)}</td>
                <td className="py-1.5 text-right">{b.win_rate == null ? '—' : fmtPct(b.win_rate, 0)}</td>
                <td className={cn('py-1.5 text-right', b.pnl > 0 ? 'text-ok' : b.pnl < 0 ? 'text-danger' : 'text-fg-3')}>{fmtSigned(b.pnl)}</td>
              </tr>
            ))}
          </tbody>
        </table>
        <p className="mt-1.5 text-[11px] text-fg-4">Well calibrated means the "Won" column tracks "Avg P". Trust it only after dozens of closed trades.</p>
      </div>
      {r.checks && <ChecksPanel c={r.checks} />}
      <div>
        <div className="mb-1.5 text-[12px] text-fg-3">Latest entry scores</div>
        <ul className="flex flex-col">
          {(r.recent ?? []).slice(0, 12).map((x, i) => (
            <li key={i} className="flex items-center gap-2 border-t border-line py-1.5 text-[12px] first:border-t-0">
              <span className="tabular w-[96px] shrink-0 text-fg-4">{fmtTime(x.ts)}</span>
              <span className="w-[86px] shrink-0 truncate text-fg">{x.symbol}</span>
              {x.error ? (
                <Pill tone="warn" className="h-5 text-[10.5px]" title={x.error}>error</Pill>
              ) : (
                <Pill tone={x.verdict === 'veto' ? 'danger' : x.verdict === 'reduce' ? 'warn' : 'ok'} className="h-5 text-[10.5px]">
                  P {fmtPct(x.p, 0)} · {x.verdict}
                </Pill>
              )}
              <span className="truncate text-fg-3">{x.regime?.replace('_', ' ')}</span>
              <span className={cn('tabular ml-auto shrink-0', x.outcome_pnl == null ? 'text-fg-4' : x.outcome_pnl > 0 ? 'text-ok' : 'text-danger')}>
                {!x.taken ? (x.applied ? 'blocked' : 'not filled') : x.closed_ts ? fmtSigned(x.outcome_pnl) : 'open'}
              </span>
            </li>
          ))}
        </ul>
      </div>
    </div>
  )
}

const FILTER_LABEL: Record<FilterName, { name: string; what: string }> = {
  levels: { name: 'Key-level room', what: 'Enough distance to the next support/resistance vs the stop?' },
  stretch: { name: 'Stretch (σ)', what: "Don't chase a move already beyond ±2σ." },
  flow: { name: 'Order flow', what: 'No long into a bearish CVD divergence (shorts: bullish).' },
  vol: { name: 'Volatility regime', what: 'Volatility exploding, or options pricing a big move: trade smaller.' },
  events: { name: 'Event blackout', what: 'No new entries around FOMC / CPI.' }
}
const FILTER_ORDER: FilterName[] = ['levels', 'stretch', 'flow', 'vol', 'events']

const signedPct = (v: number | null | undefined, d = 2) => (v == null ? '—' : `${v > 0 ? '+' : ''}${v.toFixed(d)}%`)
const toneOf = (v: number | null | undefined) => (v == null ? 'text-fg-4' : v > 0 ? 'text-ok' : v < 0 ? 'text-danger' : 'text-fg-3')

function Replay() {
  const { status } = useStatus()
  const symbols = status?.symbols ?? []
  const strategies = usePoll<StrategyDef[]>('/api/strategies', 0).data ?? []
  const [sym, setSym] = useState('')
  const [strat, setStrat] = useState('')
  const [busy, setBusy] = useState(false)
  const [out, setOut] = useState<FilterReplay | null>(null)
  const [err, setErr] = useState<string | null>(null)
  const symbol = sym || symbols[0] || ''
  const run = async () => {
    setBusy(true)
    setErr(null)
    try {
      setOut(await post<FilterReplay>('/api/filters/replay', { symbol, ...(strat ? { strategy: strat } : {}), bars: 3000 }))
    } catch (e) {
      setErr(e instanceof Error ? e.message : String(e))
    } finally {
      setBusy(false)
    }
  }
  return (
    <div className="flex flex-col gap-2.5 border-t border-line pt-3">
      <div className="text-[13px] font-semibold text-fg">Replay history</div>
      <p className="text-[12px] text-fg-3">Run a strategy's past entries through the filters now, instead of waiting weeks for shadow results.</p>
      <div className="flex flex-wrap items-center gap-2">
        <Select label="Symbol" value={symbol} onChange={setSym} options={symbols.map(x => ({ value: x, label: x }))} />
        <Select label="Strategy" value={strat} onChange={setStrat} options={[{ value: '', label: 'Current strategy' }, ...strategies.map(x => ({ value: x.name, label: x.name }))]} />
        <GlassButton variant="primary" disabled={busy || !symbol} onClick={run}>
          <IconPlayerPlay /> {busy ? 'Replaying…' : 'Replay 3000 bars'}
        </GlassButton>
      </div>
      {err && <Banner tone="danger" title="Replay failed">{err}</Banner>}
      {out && (
        <div>
          <div className="mb-1.5 text-[12px] text-fg-3">
            {out.strategy} · {out.entries} entries over {out.bars} bars
          </div>
          <table className="tabular w-full text-[12px]">
            <thead>
              <tr className="text-left text-fg-3">
                <th className="pb-1.5 font-medium">Filter</th>
                <th className="pb-1.5 text-right font-medium">Would block</th>
                <th className="pb-1.5 text-right font-medium">Blocked trades avg</th>
                <th className="pb-1.5 text-right font-medium">Kept trades avg</th>
                <th className="pb-1.5 text-right font-medium">Total: acting / not</th>
              </tr>
            </thead>
            <tbody>
              {FILTER_ORDER.filter(n => out.filters[n]).map(n => {
                const f = out.filters[n]
                return (
                  <tr key={n} className="border-t border-line" title={f.verdict}>
                    <td className="py-1.5 text-fg-2">{FILTER_LABEL[n].name}</td>
                    <td className="py-1.5 text-right">{f.blocked.n}</td>
                    <td className={cn('py-1.5 text-right', toneOf(f.blocked.avg_trade_pct))}>{signedPct(f.blocked.avg_trade_pct)}</td>
                    <td className={cn('py-1.5 text-right', toneOf(f.passed.avg_trade_pct))}>{signedPct(f.passed.avg_trade_pct)}</td>
                    <td className="py-1.5 text-right">
                      <span className={f.pnl_if_acting_pct > f.pnl_without_pct ? 'text-ok' : 'text-fg-3'}>{signedPct(f.pnl_if_acting_pct, 1)}</span>
                      <span className="text-fg-4"> / {signedPct(f.pnl_without_pct, 1)}</span>
                    </td>
                  </tr>
                )
              })}
            </tbody>
          </table>
          <p className="mt-1.5 text-[11px] text-fg-4">A filter helps when the trades it would block averaged worse than the ones it keeps, and the total is higher when acting. Hover a row for the verdict.</p>
        </div>
      )}
    </div>
  )
}

function FiltersPanel() {
  const r = usePoll<FilterReport>('/api/filters?n=40', 20_000).data
  if (!r) return <div className="shimmer h-40 rounded-lg" />
  if (!r.enabled) {
    return <EmptyGlass icon={<IconFilter />} title="Entry filters are off" description={<>Set <code className="font-mono">filters.enabled: true</code> in config.yaml and restart the backend.</>} />
  }
  return (
    <div className="flex flex-col gap-3">
      <p className="text-[12px] text-fg-3">
        Rule-based checks on every new entry, from price action, volatility maths and order flow. In <b className="text-fg-2">shadow</b> they only record what they would do; switch one to{' '}
        <code className="font-mono">mode: act</code> in config.yaml once its numbers show an edge. They never touch exits.
      </p>
      <table className="tabular w-full text-[12px]">
        <thead>
          <tr className="text-left text-fg-3">
            <th className="pb-1.5 font-medium">Filter</th>
            <th className="pb-1.5 text-right font-medium">Checks</th>
            <th className="pb-1.5 text-right font-medium">Would block</th>
            <th className="pb-1.5 text-right font-medium">Next {r.horizon_bars} bars: blocked / kept</th>
          </tr>
        </thead>
        <tbody>
          {FILTER_ORDER.filter(n => r.filters[n]).map(n => {
            const f = r.filters[n]
            return (
              <tr key={n} className="border-t border-line align-top">
                <td className="py-1.5">
                  <div className="flex items-center gap-1.5">
                    <span className={f.enabled ? 'text-fg' : 'text-fg-4'}>{FILTER_LABEL[n].name}</span>
                    <Pill tone={!f.enabled ? 'muted' : f.mode === 'act' ? 'warn' : 'info'} className="h-[18px] text-[10px]">
                      {f.enabled ? f.mode : 'off'}
                    </Pill>
                  </div>
                  <div className="mt-0.5 text-[11px] text-fg-4">{f.recommendation}</div>
                </td>
                <td className="py-1.5 text-right">{f.checks}</td>
                <td className="py-1.5 text-right">{f.would_block}</td>
                <td className="py-1.5 text-right">
                  <span className={toneOf(f.avg_fwd_pct_blocked)}>{signedPct(f.avg_fwd_pct_blocked, 3)}</span>
                  <span className="text-fg-4"> / </span>
                  <span className={toneOf(f.avg_fwd_pct_passed)}>{signedPct(f.avg_fwd_pct_passed, 3)}</span>
                </td>
              </tr>
            )
          })}
        </tbody>
      </table>
      <Replay />
      {r.recent.length > 0 && (
        <div className="border-t border-line pt-3">
          <div className="mb-1.5 text-[12px] text-fg-3">Latest checks</div>
          <ul className="flex flex-col">
            {r.recent.slice(0, 15).map((x, i) => (
              <li key={i} className="flex items-center gap-2 border-t border-line py-1.5 text-[12px] first:border-t-0" title={x.error ?? x.note ?? ''}>
                <span className="tabular w-[96px] shrink-0 text-fg-4">{fmtTime(x.ts)}</span>
                <span className="w-[80px] shrink-0 truncate text-fg">{x.symbol}</span>
                <span className="w-[112px] shrink-0 truncate text-fg-2">{FILTER_LABEL[x.name as FilterName]?.name ?? x.name}</span>
                <Pill tone={x.error ? 'warn' : x.passed ? 'ok' : x.applied ? 'danger' : 'info'} className="h-5 shrink-0 text-[10.5px]">
                  {x.error ? 'error' : x.passed ? 'pass' : x.applied ? 'acted' : 'would act'}
                </Pill>
                <span className="truncate text-fg-3">{x.note}</span>
              </li>
            ))}
          </ul>
        </div>
      )}
    </div>
  )
}

function Memory() {
  const [tab, setTab] = useState<'lessons' | 'playbooks' | 'jev' | 'filters'>('lessons')
  const lessons = usePoll<string[]>('/api/lessons', 20_000)
  const books = usePoll<{ name: string; description: string }[]>('/api/playbooks', 60_000)
  const [open, setOpen] = useState<string | null>(null)
  const [body, setBody] = useState<string>('')

  useEffect(() => {
    if (!open) return
    void get<{ text: string }>(`/api/playbook?name=${encodeURIComponent(open)}`).then(r => setBody(r.text.replace(/^---[\s\S]*?---\s*/, '')))
  }, [open])

  return (
    <div className="flex h-full min-h-0 flex-col gap-3">
      <Tabs
        tabs={[
          { id: 'lessons', label: 'Lessons', count: lessons.data?.length },
          { id: 'playbooks', label: 'Playbooks', count: books.data?.length },
          { id: 'filters', label: 'Filters' },
          { id: 'jev', label: 'JEV' }
        ]}
        value={tab}
        onChange={t => {
          setTab(t)
          setOpen(null)
        }}
      />
      <div className="min-h-0 flex-1 overflow-y-auto pr-1">
        {tab === 'jev' && <JevPanel />}
        {tab === 'filters' && <FiltersPanel />}
        {tab === 'lessons' &&
          (lessons.data?.length ? (
            <ul className="stagger flex flex-col gap-2">
              {lessons.data.map((l, i) => (
                <li key={i} className="glass-card selectable flex gap-2.5 rounded-lg px-3 py-2.5 text-[12.5px] text-fg-2">
                  <IconBulb size={16} className="mt-0.5 shrink-0 text-accent-strong" />
                  {l}
                </li>
              ))}
            </ul>
          ) : (
            <EmptyGlass icon={<IconBulb />} title="No lessons yet" description="After every few closed trades the agent reviews the journal and records short, specific lessons here." />
          ))}
        {tab === 'playbooks' &&
          (open ? (
            <div className="flex flex-col gap-2">
              <button type="button" className="self-start text-[12px] text-accent-strong hover:underline" onClick={() => setOpen(null)}>
                ← All playbooks
              </button>
              <div className="prose-hermes glass-card rounded-xl p-4 text-[13px]">
                <Markdown remarkPlugins={[remarkGfm]}>{body}</Markdown>
              </div>
            </div>
          ) : (
            <ul className="flex flex-col gap-2">
              {(books.data ?? []).map(b => (
                <li key={b.name}>
                  <GlassCard interactive onClick={() => setOpen(b.name)} className="flex gap-2.5 px-3 py-2.5">
                    <IconNotebook size={16} className="mt-0.5 shrink-0 text-accent-strong" />
                    <div className="min-w-0">
                      <div className="text-[13px] text-fg">{b.name}</div>
                      <div className="text-[12px] text-fg-3">{b.description}</div>
                    </div>
                  </GlassCard>
                </li>
              ))}
            </ul>
          ))}
      </div>
    </div>
  )
}

export function BrainPage() {
  const { status } = useStatus()
  return (
    <div className="flex h-full flex-col">
      <PageHeader
        icon={<IconBrain />}
        title="Brain"
        subtitle="What the bot has learned, its playbooks, the JEV decision model, and a line to the agent"
        actions={
          <>
            <Pill tone={status?.jev_mode === 'error' ? 'danger' : status?.jev_mode === 'gate' ? 'warn' : status?.jev_mode === 'shadow' ? 'info' : 'muted'} dot>
              JEV {status?.jev_mode ?? 'off'}
            </Pill>
            <Pill tone={status?.llm_enabled ? 'ok' : 'muted'} dot>
              {status?.llm_enabled ? 'LLM on' : 'LLM off'}
            </Pill>
          </>
        }
      />
      <div className="grid min-h-0 flex-1 grid-cols-[minmax(0,1fr)_minmax(0,1.35fr)] gap-4 px-6 pb-6">
        <GlassCard className="min-h-0 p-4">
          <Section title="Memory" className="h-full">
            <Memory />
          </Section>
        </GlassCard>
        <GlassCard className="min-h-0 p-4">
          <Section title="Ask Hermes" className="h-full">
            <Chat enabled={!!status?.llm_enabled} />
          </Section>
        </GlassCard>
      </div>
    </div>
  )
}
