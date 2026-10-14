import {
  IconBook2,
  IconBrain,
  IconChartCandle,
  IconFlask,
  IconLayoutDashboard,
  IconMinus,
  IconSettings,
  IconSquare,
  IconSquaresDiagonal,
  IconX
} from '@tabler/icons-react'
import { useEffect, useState, type ReactNode } from 'react'
import type { BackendState } from '../../shared/ipc.ts'
import type { Status } from '../lib/api.ts'
import { trader } from '../lib/api.ts'
import { cn } from '../lib/cn.ts'
import { fmtAgo } from '../lib/format.ts'
import { Pill, StatusDot } from './glass.tsx'

export type PageId = 'overview' | 'markets' | 'strategies' | 'journal' | 'brain' | 'settings'

export const PAGES: { id: PageId; label: string; icon: ReactNode }[] = [
  { id: 'overview', label: 'Overview', icon: <IconLayoutDashboard /> },
  { id: 'markets', label: 'Markets', icon: <IconChartCandle /> },
  { id: 'strategies', label: 'Strategies', icon: <IconFlask /> },
  { id: 'journal', label: 'Journal', icon: <IconBook2 /> },
  { id: 'brain', label: 'Brain', icon: <IconBrain /> },
  { id: 'settings', label: 'Settings', icon: <IconSettings /> }
]

export function HermesMark({ size = 22 }: { size?: number }) {
  // Original mark: a rising line in a glass tile (not the Herald or Nous logos).
  return (
    <svg width={size} height={size} viewBox="0 0 24 24" fill="none" aria-hidden="true">
      <rect x="1.5" y="1.5" width="21" height="21" rx="6" fill="url(#hm)" stroke="rgba(170,205,255,.6)" />
      <path d="M5.5 16.5l4-4.5 3 2.5 6-7" stroke="#eaf2ff" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" />
      <circle cx="18.5" cy="7.5" r="1.6" fill="#36e6a6" />
      <defs>
        <linearGradient id="hm" x1="0" y1="0" x2="0" y2="24">
          <stop stopColor="#3c78ff" />
          <stop offset="1" stopColor="#1e46be" />
        </linearGradient>
      </defs>
    </svg>
  )
}

export function TitleBar({ status }: { status: Status | null }) {
  const [max, setMax] = useState(false)
  useEffect(() => trader().onMaximized(setMax), [])
  const live = status?.mode === 'live'
  return (
    <div className="drag-region relative z-30 flex h-10 shrink-0 items-center justify-between px-3" onDoubleClick={() => trader().windowControl('maximize')}>
      <div className="flex items-center gap-2.5 pl-1">
        <HermesMark size={20} />
        <span className="text-[13px] font-semibold tracking-tight text-fg">Hermes Trader</span>
        {status && (
          <Pill tone={live ? 'danger' : 'info'} dot className="ml-1 h-5 text-[10.5px] tracking-wider uppercase">
            {live ? 'Live — real money' : 'Paper'}
          </Pill>
        )}
      </div>
      <div className="no-drag flex items-center gap-1">
        {[
          { a: 'minimize' as const, icon: <IconMinus size={15} />, label: 'Minimise' },
          { a: 'maximize' as const, icon: max ? <IconSquaresDiagonal size={14} /> : <IconSquare size={13} />, label: max ? 'Restore' : 'Maximise' },
          { a: 'close' as const, icon: <IconX size={15} />, label: 'Close' }
        ].map(b => (
          <button
            key={b.a}
            type="button"
            aria-label={b.label}
            onClick={() => trader().windowControl(b.a)}
            className={cn('flex size-8 items-center justify-center rounded-lg text-fg-3 hover:bg-white/10 hover:text-fg', b.a === 'close' && 'hover:bg-danger/80 hover:text-white')}
          >
            {b.icon}
          </button>
        ))}
      </div>
    </div>
  )
}

export function Sidebar({ page, onPage, status, backend }: { page: PageId; onPage: (p: PageId) => void; status: Status | null; backend: BackendState | null }) {
  const bot = status?.bot
  const halted = status?.risk.halted
  const connected = backend?.phase === 'ready'
  return (
    <nav aria-label="Main" className="glass flex w-[212px] shrink-0 flex-col rounded-2xl p-2.5">
      <div className="stagger flex flex-col gap-0.5">
        {PAGES.map(p => {
          const active = p.id === page
          return (
            <button
              key={p.id}
              type="button"
              aria-current={active ? 'page' : undefined}
              onClick={() => onPage(p.id)}
              className={cn(
                'flex h-9 items-center gap-2.5 rounded-lg px-2.5 text-[13px] transition-colors duration-150 [&_svg]:size-[18px]',
                active ? 'bg-accent text-accent-fg shadow-[0_4px_16px_rgba(47,125,255,.4)]' : 'text-fg-2 hover:bg-white/7 hover:text-fg'
              )}
            >
              {p.icon}
              {p.label}
            </button>
          )
        })}
      </div>

      <div className="mt-auto flex flex-col gap-2 rounded-xl border border-line bg-black/15 p-3 text-[12px]">
        <div className="flex items-center gap-2">
          <StatusDot tone={!connected ? (backend?.phase === 'starting' ? 'warn' : 'danger') : halted ? 'danger' : bot?.running ? 'ok' : 'muted'} pulse={bot?.running && !halted} />
          <span className="font-medium text-fg">
            {!connected ? (backend?.phase === 'starting' ? 'Connecting…' : 'Backend offline') : halted ? 'Halted' : bot?.stopping ? 'Stopping…' : bot?.running ? 'Bot running' : 'Bot stopped'}
          </span>
        </div>
        {connected && status && (
          <div className="tabular flex flex-col gap-0.5 text-fg-3">
            <span>
              {status.broker} · {status.timeframe} · {status.symbols.length} symbols
            </span>
            {bot?.running && bot.next_cycle && <span>Next cycle {fmtAgo(bot.next_cycle)}</span>}
            {!bot?.running && <span>Last cycle {fmtAgo(status.last_cycle)}</span>}
          </div>
        )}
      </div>
    </nav>
  )
}
