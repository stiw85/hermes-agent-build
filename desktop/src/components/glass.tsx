import { IconAlertTriangle, IconInfoCircle } from '@tabler/icons-react'
import type React from 'react'
import { cn } from '../lib/cn.ts'

/*
 * Glass page vocabulary, adapted from Herald OS's src/components/ui/glass.tsx (MIT).
 * One primitive per concern; tokens only, never literal colours.
 */

export function Tile({ icon, size = 44, tone = 'accent' }: { icon: React.ReactNode; size?: number; tone?: 'accent' | 'danger' | 'ok' }) {
  const vars = {
    accent: {},
    danger: { '--tile-from': 'rgba(255,109,109,.55)', '--tile-to': 'rgba(170,40,60,.55)', '--tile-border': 'rgba(255,170,170,.4)' },
    ok: { '--tile-from': 'rgba(54,230,166,.45)', '--tile-to': 'rgba(20,120,110,.55)', '--tile-border': 'rgba(150,255,210,.4)' }
  }[tone] as React.CSSProperties
  return (
    <span className="icon-tile shrink-0" style={{ width: size, height: size, ...vars }}>
      <span className="flex [&_svg]:size-[55%]" style={{ width: size, height: size, alignItems: 'center', justifyContent: 'center' }}>
        {icon}
      </span>
    </span>
  )
}

export function PageHeader({ icon, title, subtitle, actions }: { icon: React.ReactNode; title: string; subtitle?: React.ReactNode; actions?: React.ReactNode }) {
  return (
    <div className="flex items-center justify-between gap-4 px-6 pt-5 pb-4">
      <div className="flex min-w-0 items-center gap-3.5">
        <Tile icon={icon} />
        <div className="min-w-0">
          <h1 className="text-[20px] leading-tight font-semibold tracking-tight text-fg">{title}</h1>
          {subtitle && <div className="truncate text-[12.5px] text-fg-3">{subtitle}</div>}
        </div>
      </div>
      {actions && <div className="flex shrink-0 items-center gap-2">{actions}</div>}
    </div>
  )
}

export function GlassCard({ children, className, selected, interactive, onClick }: { children: React.ReactNode; className?: string; selected?: boolean; interactive?: boolean; onClick?: () => void }) {
  return (
    <div
      onClick={onClick}
      className={cn('glass-card rounded-xl text-left', interactive && 'glass-card-hover cursor-pointer', selected && 'glass-card-selected', className)}
    >
      {children}
    </div>
  )
}

export type Tone = 'accent' | 'progress' | 'ok' | 'warn' | 'danger' | 'muted' | 'info'

const PILL: Record<Tone, string> = {
  accent: 'bg-accent-soft text-accent-strong border-accent/40',
  progress: 'bg-progress/15 text-progress border-progress/40',
  ok: 'bg-ok/15 text-ok border-ok/40',
  warn: 'bg-warn/15 text-warn border-warn/40',
  danger: 'bg-danger/15 text-danger border-danger/40',
  muted: 'bg-white/6 text-fg-2 border-line',
  info: 'bg-info/15 text-info border-info/40'
}

export function Pill({ children, tone = 'muted', dot, className, title }: { children: React.ReactNode; tone?: Tone; dot?: boolean; className?: string; title?: string }) {
  return (
    <span title={title} className={cn('inline-flex h-6 items-center gap-1.5 rounded-full border px-2.5 text-[11.5px] font-medium whitespace-nowrap', PILL[tone], className)}>
      {dot && <span className="size-1.5 rounded-full bg-current" />}
      {children}
    </span>
  )
}

export function StatusDot({ tone = 'ok', pulse, className }: { tone?: Tone; pulse?: boolean; className?: string }) {
  const color = { accent: 'bg-accent-strong', progress: 'bg-progress', ok: 'bg-ok', warn: 'bg-warn', danger: 'bg-danger', muted: 'bg-fg-4', info: 'bg-info' }[tone]
  return <span className={cn('inline-block size-2 shrink-0 rounded-full shadow-[0_0_8px_currentColor]', color, pulse && 'animate-pulse-soft', className)} />
}

export interface TabDef<T extends string> {
  id: T
  label: string
  count?: number
}

export function Tabs<T extends string>({ tabs, value, onChange }: { tabs: readonly TabDef<T>[]; value: T; onChange: (id: T) => void }) {
  return (
    <div className="inline-flex items-center gap-1 rounded-lg bg-black/15 p-1 hairline" role="tablist">
      {tabs.map(tab => {
        const active = tab.id === value
        return (
          <button
            key={tab.id}
            type="button"
            role="tab"
            aria-selected={active}
            onClick={() => onChange(tab.id)}
            className={cn('flex h-7 items-center gap-1.5 rounded-md px-3 text-[12.5px] transition-colors duration-150', active ? 'bg-accent text-accent-fg shadow-[0_2px_10px_rgba(47,125,255,.45)]' : 'text-fg-2 hover:bg-white/6 hover:text-fg')}
          >
            {tab.label}
            {tab.count != null && <span className={cn('rounded-full px-1.5 text-[10.5px] tabular-nums', active ? 'bg-white/25' : 'bg-white/10 text-fg-3')}>{tab.count}</span>}
          </button>
        )
      })}
    </div>
  )
}

export function Chips<T extends string>({ items, value, onChange }: { items: readonly { id: T; label: string }[]; value: T; onChange: (id: T) => void }) {
  return (
    <div className="flex flex-wrap items-center gap-1.5">
      {items.map(item => {
        const active = item.id === value
        return (
          <button
            key={item.id}
            type="button"
            aria-pressed={active}
            onClick={() => onChange(item.id)}
            className={cn('h-7 rounded-full border px-3 text-[12px] transition-colors duration-150', active ? 'border-accent bg-accent text-accent-fg' : 'border-line bg-white/4 text-fg-2 hover:bg-white/8 hover:text-fg')}
          >
            {item.label}
          </button>
        )
      })}
    </div>
  )
}

export function Section({ title, action, children, className }: { title: React.ReactNode; action?: React.ReactNode; children: React.ReactNode; className?: string }) {
  return (
    <section className={cn('flex min-h-0 flex-col gap-2.5', className)}>
      <div className="flex items-center justify-between gap-3">
        <h2 className="text-[14px] font-semibold text-fg">{title}</h2>
        {action}
      </div>
      {children}
    </section>
  )
}

export function KeyValue({ rows, className, labelWidth = 120 }: { rows: { label: string; value: React.ReactNode }[]; className?: string; labelWidth?: number }) {
  return (
    <dl className={cn('grid gap-x-4 gap-y-2.5 text-[12.5px]', className)} style={{ gridTemplateColumns: `${labelWidth}px 1fr` }}>
      {rows.map(row => (
        <div key={row.label} className="contents">
          <dt className="text-fg-3">{row.label}</dt>
          <dd className="selectable tabular text-fg">{row.value}</dd>
        </div>
      ))}
    </dl>
  )
}

export function GlassButton({ children, variant = 'secondary', size = 'md', className, ...rest }: React.ComponentProps<'button'> & { variant?: 'primary' | 'secondary' | 'ghost' | 'danger'; size?: 'sm' | 'md' | 'icon' }) {
  const variants = {
    primary: 'bg-accent text-accent-fg border-accent-strong/60 hover:bg-accent-strong shadow-[0_4px_16px_rgba(47,125,255,.45)] font-medium',
    secondary: 'bg-white/6 text-fg border-line hover:bg-white/10 hover:border-line-strong',
    ghost: 'bg-transparent text-fg-2 border-transparent hover:bg-white/8 hover:text-fg',
    danger: 'bg-danger/10 text-danger border-danger/40 hover:bg-danger/20'
  }
  const sizes = { sm: 'h-8 px-3 text-[12.5px] gap-1.5 rounded-lg', md: 'h-9 px-3.5 text-[13px] gap-2 rounded-lg', icon: 'size-9 rounded-lg' }
  return (
    <button type="button" className={cn('inline-flex items-center justify-center whitespace-nowrap border transition-colors duration-150 disabled:cursor-not-allowed disabled:opacity-40 [&_svg]:size-4 [&_svg]:shrink-0', variants[variant], sizes[size], className)} {...rest}>
      {children}
    </button>
  )
}

export function EmptyGlass({ icon, title, description, action, className }: { icon?: React.ReactNode; title: string; description?: React.ReactNode; action?: React.ReactNode; className?: string }) {
  return (
    <div className={cn('flex min-h-40 flex-col items-center justify-center gap-2 rounded-xl border border-dashed border-line px-6 py-8 text-center', className)}>
      {icon && <div className="text-fg-3 [&_svg]:size-7">{icon}</div>}
      <div className="text-[13px] text-fg-2">{title}</div>
      {description && <div className="max-w-md text-[12px] text-fg-3">{description}</div>}
      {action && <div className="mt-2">{action}</div>}
    </div>
  )
}

export function ProgressBar({ value, tone = 'accent', className, label }: { value: number; tone?: 'accent' | 'ok' | 'warn' | 'danger'; className?: string; label: string }) {
  const color = { accent: 'bg-accent-strong', ok: 'bg-ok', warn: 'bg-warn', danger: 'bg-danger' }[tone]
  return (
    <div role="meter" aria-label={label} aria-valuenow={Math.round(value)} aria-valuemin={0} aria-valuemax={100} className={cn('h-1.5 w-full overflow-hidden rounded-full bg-black/25', className)}>
      <div className={cn('h-full rounded-full transition-[width] duration-500', color)} style={{ width: `${Math.max(0, Math.min(100, value))}%` }} />
    </div>
  )
}

/** Hero number tile: label, value, a secondary line. */
export function Stat({ label, value, sub, valueTone, children }: { label: string; value: React.ReactNode; sub?: React.ReactNode; valueTone?: 'ok' | 'danger' | 'muted'; children?: React.ReactNode }) {
  return (
    <GlassCard className="flex min-w-0 flex-col gap-1 px-4 py-3.5">
      <div className="text-[11.5px] font-medium tracking-wide text-fg-3 uppercase">{label}</div>
      <div className={cn('truncate text-[22px] leading-tight font-semibold', valueTone === 'ok' ? 'text-ok' : valueTone === 'danger' ? 'text-danger' : 'text-fg')}>{value}</div>
      {sub && <div className="tabular truncate text-[12px] text-fg-3">{sub}</div>}
      {children}
    </GlassCard>
  )
}

export function Banner({ tone, title, children, action }: { tone: 'danger' | 'warn' | 'info'; title: string; children?: React.ReactNode; action?: React.ReactNode }) {
  const cls = { danger: 'border-danger/45 bg-danger/12', warn: 'border-warn/45 bg-warn/10', info: 'border-info/40 bg-info/10' }[tone]
  const Icon = tone === 'info' ? IconInfoCircle : IconAlertTriangle
  return (
    <div role={tone === 'danger' ? 'alert' : 'status'} className={cn('flex items-start gap-3 rounded-xl border px-4 py-3', cls)}>
      <Icon size={18} className={cn('mt-0.5 shrink-0', tone === 'danger' ? 'text-danger' : tone === 'warn' ? 'text-warn' : 'text-info')} />
      <div className="min-w-0 flex-1">
        <div className="text-[13px] font-semibold text-fg">{title}</div>
        {children && <div className="selectable mt-0.5 text-[12.5px] text-fg-2">{children}</div>}
      </div>
      {action}
    </div>
  )
}

export function Field({ label, children, hint }: { label: string; children: React.ReactNode; hint?: React.ReactNode }) {
  return (
    <label className="flex flex-col gap-1.5">
      <span className="text-[12px] text-fg-3">{label}</span>
      {children}
      {hint && <span className="text-[11.5px] text-fg-4">{hint}</span>}
    </label>
  )
}

export function TextInput(props: React.ComponentProps<'input'>) {
  return <input {...props} className={cn('glass-input h-9 rounded-lg px-3 text-[13px] outline-none placeholder:text-fg-4', props.className)} />
}

export function Select({ value, onChange, options, label }: { value: string; onChange: (v: string) => void; options: { value: string; label: string }[]; label: string }) {
  return (
    <select aria-label={label} value={value} onChange={e => onChange(e.target.value)} className="glass-input h-9 rounded-lg px-2.5 text-[13px] text-fg outline-none">
      {options.map(o => (
        <option key={o.value} value={o.value} className="bg-bg">
          {o.label}
        </option>
      ))}
    </select>
  )
}
