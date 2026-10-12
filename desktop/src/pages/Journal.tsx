import { IconBook2 } from '@tabler/icons-react'
import { useState } from 'react'
import { EmptyGlass, GlassCard, PageHeader, Pill, Section, Tabs } from '../components/glass.tsx'
import { usePoll, type Decision, type EventRow, type Fill, type Stats } from '../lib/api.ts'
import { cn } from '../lib/cn.ts'
import { fmtMoney, fmtPct, fmtPrice, fmtQty, fmtSigned, fmtTime } from '../lib/format.ts'

type Tab = 'trades' | 'decisions' | 'events'

const th = 'sticky top-0 bg-[#0a1c55] pb-2 pt-1 font-medium'

function Trades({ rows }: { rows: Fill[] }) {
  if (!rows.length) return <EmptyGlass title="No trades yet" />
  return (
    <table className="tabular w-full text-[12.5px]">
      <thead>
        <tr className="text-left text-fg-3">
          <th className={th}>Time</th>
          <th className={th}>Symbol</th>
          <th className={th}>Side</th>
          <th className={cn(th, 'text-right')}>Qty</th>
          <th className={cn(th, 'text-right')}>Price</th>
          <th className={cn(th, 'text-right')}>Fee</th>
          <th className={cn(th, 'text-right')}>Realised</th>
          <th className={cn(th, 'pl-4')}>Strategy · reason</th>
        </tr>
      </thead>
      <tbody>
        {rows.map(f => (
          <tr key={f.id} className="border-t border-line">
            <td className="py-2 text-fg-3">{fmtTime(f.ts)}</td>
            <td className="py-2 text-fg">{f.symbol}</td>
            <td className="py-2">
              <Pill tone={f.side === 'buy' ? 'ok' : 'danger'}>{f.side}</Pill>
            </td>
            <td className="py-2 text-right">{fmtQty(f.qty)}</td>
            <td className="py-2 text-right">{fmtPrice(f.price)}</td>
            <td className="py-2 text-right text-fg-3">{fmtMoney(f.fee)}</td>
            <td className={cn('py-2 text-right', f.realized_pnl == null ? 'text-fg-4' : f.realized_pnl >= 0 ? 'text-ok' : 'text-danger')}>{f.realized_pnl == null ? '—' : fmtSigned(f.realized_pnl)}</td>
            <td className="selectable max-w-[360px] truncate py-2 pl-4 text-fg-3" title={f.reason}>
              {f.strategy} · {f.reason}
            </td>
          </tr>
        ))}
      </tbody>
    </table>
  )
}

function Decisions({ rows }: { rows: Decision[] }) {
  if (!rows.length) return <EmptyGlass title="No decisions yet" description="Every symbol gets one decision per cycle, including holds." />
  return (
    <table className="tabular w-full text-[12.5px]">
      <thead>
        <tr className="text-left text-fg-3">
          <th className={th}>Time</th>
          <th className={th}>Symbol</th>
          <th className={cn(th, 'text-right')}>Target</th>
          <th className={cn(th, 'pl-4')}>Action</th>
          <th className={th}>JEV</th>
          <th className={th}>LLM</th>
          <th className={th}>Why</th>
        </tr>
      </thead>
      <tbody>
        {rows.map(d => (
          <tr key={d.id} className="border-t border-line align-top">
            <td className="py-2 text-fg-3">{fmtTime(d.ts)}</td>
            <td className="py-2 text-fg">{d.symbol}</td>
            <td className="py-2 text-right">{d.target >= 0 ? '+' : ''}{d.target.toFixed(2)}</td>
            <td className={cn('py-2 pl-4', d.action.startsWith('buy') ? 'text-ok' : d.action.startsWith('sell') ? 'text-danger' : 'text-fg-2')}>{d.action}</td>
            <td className="py-2">
              {d.jev_p != null ? (
                <span className={cn('tabular', d.jev_p < 0.4 ? 'text-danger' : d.jev_p < 0.55 ? 'text-warn' : 'text-ok')} title={d.jev_note ?? ''}>
                  {Math.round(d.jev_p * 100)}%
                </span>
              ) : (
                <span className="text-fg-4" title={d.jev_note ?? ''}>{d.jev_note ? '!' : '—'}</span>
              )}
            </td>
            <td className="py-2">{d.llm_verdict ? <Pill tone={d.llm_verdict === 'veto' ? 'danger' : d.llm_verdict === 'reduce' ? 'warn' : d.llm_verdict === 'error' ? 'warn' : 'ok'} title={d.llm_note}>{d.llm_verdict}</Pill> : <span className="text-fg-4">—</span>}</td>
            <td className="selectable max-w-[460px] py-2 text-[11.5px] text-fg-3">
              <div className="truncate" title={d.signal_reason}>{d.signal_reason}</div>
              {d.risk_notes && <div className="truncate text-fg-4" title={d.risk_notes}>risk: {d.risk_notes}</div>}
              {d.llm_note && <div className="truncate text-fg-4" title={d.llm_note}>LLM: {d.llm_note}</div>}
            </td>
          </tr>
        ))}
      </tbody>
    </table>
  )
}

function Events({ rows }: { rows: EventRow[] }) {
  if (!rows.length) return <EmptyGlass title="No events yet" description="Halts, promotions, reflections, stops and errors appear here." />
  const tone = (k: string) => (['halt', 'error', 'reject', 'stop'].includes(k) ? 'danger' : ['promote', 'reflect'].includes(k) ? 'accent' : k === 'resume' ? 'ok' : 'muted') as 'danger' | 'accent' | 'ok' | 'muted'
  return (
    <ul className="flex flex-col">
      {rows.map(e => (
        <li key={e.id} className="flex items-start gap-3 border-t border-line py-2.5 first:border-t-0">
          <span className="tabular w-[120px] shrink-0 pt-0.5 text-[12px] text-fg-3">{fmtTime(e.ts)}</span>
          <Pill tone={tone(e.kind)} className="w-[92px] justify-center">{e.kind}</Pill>
          <div className="selectable min-w-0 flex-1 text-[12.5px] whitespace-pre-wrap text-fg-2">{e.message}</div>
        </li>
      ))}
    </ul>
  )
}

export function JournalPage() {
  const [tab, setTab] = useState<Tab>('trades')
  const stats = usePoll<Stats>('/api/stats', 15_000)
  const fills = usePoll<Fill[]>(tab === 'trades' ? '/api/fills?n=300' : null, 10_000)
  const decisions = usePoll<Decision[]>(tab === 'decisions' ? '/api/decisions?n=300' : null, 10_000)
  const events = usePoll<EventRow[]>(tab === 'events' ? '/api/events?n=200' : null, 10_000)
  const s = stats.data

  return (
    <div className="flex h-full flex-col">
      <PageHeader icon={<IconBook2 />} title="Journal" subtitle="Everything the bot did and why: the record its self-review learns from" />
      <div className="flex min-h-0 flex-1 flex-col gap-4 px-6 pb-6">
        <GlassCard className="shrink-0 p-4">
          <Section title="Live results by strategy" action={s && <span className="tabular text-[12px] text-fg-3">{s.fills} fills · {s.closed_trades} closes · realised {fmtSigned(s.realized_pnl)} · max DD {fmtPct(s.max_drawdown, 1)}</span>}>
            {!s || s.by_strategy_symbol.length === 0 ? (
              <div className="text-[12.5px] text-fg-3">No closed trades yet. Results appear after the first exit.</div>
            ) : (
              <table className="tabular w-full text-[12.5px]">
                <thead>
                  <tr className="text-left text-fg-3">
                    <th className="pb-1.5 font-medium">Strategy</th>
                    <th className="pb-1.5 font-medium">Symbol</th>
                    <th className="pb-1.5 text-right font-medium">Closes</th>
                    <th className="pb-1.5 text-right font-medium">Win rate</th>
                    <th className="pb-1.5 text-right font-medium">Fees</th>
                    <th className="pb-1.5 text-right font-medium">P&L</th>
                  </tr>
                </thead>
                <tbody>
                  {s.by_strategy_symbol.map(r => (
                    <tr key={`${r.strategy}-${r.symbol}`} className="border-t border-line">
                      <td className="py-1.5 text-fg">{r.strategy}</td>
                      <td className="py-1.5">{r.symbol}</td>
                      <td className="py-1.5 text-right">{r.closes}</td>
                      <td className="py-1.5 text-right">{fmtPct(r.win_rate, 0)}</td>
                      <td className="py-1.5 text-right text-fg-3">{fmtMoney(r.fees)}</td>
                      <td className={cn('py-1.5 text-right', r.pnl >= 0 ? 'text-ok' : 'text-danger')}>{fmtSigned(r.pnl)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            )}
          </Section>
        </GlassCard>
        <GlassCard className="flex min-h-0 flex-1 flex-col p-4">
          <div className="mb-3">
            <Tabs
              tabs={[
                { id: 'trades', label: 'Trades' },
                { id: 'decisions', label: 'Decisions' },
                { id: 'events', label: 'Events' }
              ]}
              value={tab}
              onChange={setTab}
            />
          </div>
          <div className="min-h-0 flex-1 overflow-y-auto pr-1">
            {tab === 'trades' && (fills.data ? <Trades rows={fills.data} /> : <div className="shimmer h-40 rounded-lg" />)}
            {tab === 'decisions' && (decisions.data ? <Decisions rows={decisions.data} /> : <div className="shimmer h-40 rounded-lg" />)}
            {tab === 'events' && (events.data ? <Events rows={events.data} /> : <div className="shimmer h-40 rounded-lg" />)}
          </div>
        </GlassCard>
      </div>
    </div>
  )
}
