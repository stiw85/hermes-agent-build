import { IconFolder, IconFolderOpen, IconPlugConnected, IconRefresh, IconSettings } from '@tabler/icons-react'
import { useEffect, useState } from 'react'
import type { Settings } from '../../shared/ipc.ts'
import { Banner, Chips, Field, GlassButton, GlassCard, KeyValue, PageHeader, Pill, Section, StatusDot, TextInput } from '../components/glass.tsx'
import { useConfirm, useToast } from '../components/overlays.tsx'
import { trader, useBackendState, usePoll, type ConfigView } from '../lib/api.ts'
import { setEffects, useEffectsLevel, type Effects } from '../lib/effects.ts'
import { fmtMoney, fmtPct } from '../lib/format.ts'
import { useStatus } from '../lib/status.ts'

function ConfigCard() {
  const backend = useBackendState()
  const cfg = usePoll<ConfigView>(backend?.phase === 'ready' ? '/api/config' : null, 0)
  const c = cfg.data
  if (!c) return null
  const r = c.risk
  return (
    <GlassCard className="p-4">
      <Section
        title="Trading configuration"
        action={
          c.config_path && (
            <GlassButton size="sm" onClick={() => trader().openPath(c.config_path!.replace(/\/[^/]+$/, ''))}>
              <IconFolderOpen /> Open folder
            </GlassButton>
          )
        }
      >
        <p className="text-[12px] text-fg-3">
          Read-only by design: edit <span className="font-mono text-fg-2">{c.config_path ?? 'config.yaml'}</span> and restart the backend. Nothing in this app can loosen a risk limit.
        </p>
        <div className="grid grid-cols-2 gap-6">
          <KeyValue
            labelWidth={150}
            rows={[
              { label: 'Mode', value: <Pill tone={c.mode === 'live' ? 'danger' : 'info'}>{c.mode}</Pill> },
              { label: 'Broker', value: `${String(c.broker.name)}${c.broker.name === 'paper' ? ` · data: ${String(c.broker.data_source)}` : ''}${c.broker.name === 'ccxt' ? ` · ${String(c.broker.exchange)}${c.broker.sandbox ? ' (testnet)' : ''}` : ''}` },
              { label: 'Symbols', value: c.symbols.join(', ') },
              { label: 'Timeframe', value: `${c.timeframe} · ${c.history_bars} bars` },
              { label: 'Short selling', value: c.allow_short ? 'Allowed' : 'Off' },
              { label: 'Default strategy', value: c.default_strategy.name },
              { label: 'LLM', value: c.llm.enabled ? `${String(c.llm.model)} @ ${String(c.llm.base_url)}` : 'Off' },
              {
                label: 'Entry filters',
                value: !c.filters?.enabled
                  ? 'Off'
                  : `${c.filters.mode} · ${(['levels', 'stretch', 'flow', 'vol', 'events'] as const)
                      .filter(n => (c.filters?.[n] as { enabled?: boolean } | undefined)?.enabled !== false)
                      .map(n => {
                        const m = (c.filters?.[n] as { mode?: string } | undefined)?.mode
                        return m && m !== c.filters?.mode ? `${n} (${m})` : n
                      })
                      .join(', ')}`
              },
              { label: 'Data folder', value: <span className="font-mono text-[11.5px]">{c.home}</span> }
            ]}
          />
          <KeyValue
            labelWidth={170}
            rows={[
              { label: 'Max per position', value: fmtPct(r.max_position_pct, 0) },
              { label: 'Max gross exposure', value: fmtPct(r.max_gross_exposure_pct, 0) },
              { label: 'Max order size', value: fmtMoney(r.max_order_notional) },
              { label: 'Risk per trade (ATR)', value: fmtPct(r.risk_per_trade_pct, 1) },
              { label: 'ATR stop', value: `${r.atr_stop_mult}× ATR` },
              { label: 'Daily loss → reduce-only', value: fmtPct(r.max_daily_loss_pct, 1) },
              { label: 'Drawdown → kill switch', value: fmtPct(r.max_drawdown_pct, 0) },
              { label: 'Max trades per day', value: String(r.max_trades_per_day) }
            ]}
          />
        </div>
      </Section>
    </GlassCard>
  )
}

export function SettingsPage() {
  const backend = useBackendState()
  const [s, setS] = useState<Settings | null>(null)
  const [logs, setLogs] = useState<string[]>([])
  const [busy, setBusy] = useState(false)
  const toast = useToast()
  const confirm = useConfirm()
  const { status } = useStatus()
  const botRunning = !!status?.bot.running && backend?.mode === 'spawn'
  /** Restarting a spawned backend stops the bot: say so first. */
  const okToRestart = async () =>
    !botRunning ||
    (
      await confirm({
        title: 'Restart the backend?',
        danger: status?.mode === 'live',
        confirmLabel: 'Stop bot and restart',
        body: 'The bot finishes its current cycle and stops. Start it again from Overview after the restart.'
      })
    ).ok

  useEffect(() => {
    void trader().getSettings().then(setS)
  }, [])
  useEffect(() => {
    const load = () => void trader().backendLogs().then(setLogs)
    load()
    const t = setInterval(load, 3000)
    return () => clearInterval(t)
  }, [])

  if (!s) return null
  const patch = (p: Partial<Settings>) => setS({ ...s, ...p })
  const save = async () => {
    if (!(await okToRestart())) return
    setBusy(true)
    const next = await trader().setSettings(s)
    setS(next)
    const st = await trader().backendRestart()
    setBusy(false)
    toast(st.phase === 'ready' ? 'ok' : 'danger', st.phase === 'ready' ? 'Connected to the backend' : st.error ?? 'Could not connect')
  }
  const tone = backend?.phase === 'ready' ? 'ok' : backend?.phase === 'starting' ? 'warn' : 'danger'

  return (
    <div className="flex h-full flex-col">
      <PageHeader icon={<IconSettings />} title="Settings" subtitle="How this app reaches the trading bot, and the configuration it runs with" />
      <div className="min-h-0 flex-1 overflow-y-auto px-6 pb-6">
        <div className="flex flex-col gap-4">
          <GlassCard className="p-4">
            <Section
              title="Backend connection"
              action={
                <div className="flex items-center gap-2 text-[12.5px]">
                  <StatusDot tone={tone} />
                  <span className="text-fg-2">{backend?.phase ?? '…'}</span>
                  {backend?.url && <span className="font-mono text-[11.5px] text-fg-3">{backend.url}</span>}
                </div>
              }
            >
              {backend?.phase === 'error' && <Banner tone="danger" title="Not connected">{backend.error}</Banner>}
              <Chips
                items={[
                  { id: 'spawn', label: 'Start it for me' },
                  { id: 'attach', label: 'Attach to a running one' }
                ]}
                value={s.mode}
                onChange={mode => patch({ mode })}
              />
              <p className="text-[12px] text-fg-3">
                {s.mode === 'spawn'
                  ? 'The app runs `hermes-trader serve` in your project folder and stops it when you quit. The bot only trades while the app is open.'
                  : 'For 24/7 trading: run `hermes-trader serve --run` in tmux or systemd yourself; the app connects to it and closing the app does not stop trading.'}
              </p>
              <div className="grid grid-cols-2 gap-4">
                <Field label="Project folder (contains config.yaml)">
                  <div className="flex gap-2">
                    <TextInput className="flex-1 font-mono text-[12px]" value={s.projectDir} onChange={e => patch({ projectDir: e.target.value })} aria-label="Project folder" />
                    <GlassButton
                      size="icon"
                      aria-label="Choose folder"
                      onClick={async () => {
                        const p = await trader().pickFolder()
                        if (p) patch({ projectDir: p })
                      }}
                    >
                      <IconFolder />
                    </GlassButton>
                  </div>
                </Field>
                {s.mode === 'spawn' ? (
                  <Field label="Command (optional)" hint="Blank = <project>/.venv/bin/hermes-trader, else hermes-trader on PATH">
                    <TextInput className="font-mono text-[12px]" placeholder="auto" value={s.command} onChange={e => patch({ command: e.target.value })} aria-label="Command" />
                  </Field>
                ) : (
                  <div className="grid grid-cols-2 gap-3">
                    <Field label="Backend URL">
                      <TextInput className="font-mono text-[12px]" value={s.attachUrl} onChange={e => patch({ attachUrl: e.target.value })} aria-label="Backend URL" />
                    </Field>
                    <Field label="Token file" hint="Blank = <project>/data/api_token">
                      <TextInput className="font-mono text-[12px]" placeholder="auto" value={s.attachTokenFile} onChange={e => patch({ attachTokenFile: e.target.value })} aria-label="Token file" />
                    </Field>
                  </div>
                )}
              </div>
              <div className="flex gap-2">
                <GlassButton variant="primary" disabled={busy} onClick={save}>
                  <IconPlugConnected /> {busy ? 'Connecting…' : 'Save and connect'}
                </GlassButton>
                <GlassButton disabled={busy} onClick={async () => {
                  if (!(await okToRestart())) return
                  setBusy(true)
                  await trader().backendRestart()
                  setBusy(false)
                }}>
                  <IconRefresh /> Restart backend
                </GlassButton>
              </div>
            </Section>
          </GlassCard>

          <AppearanceCard />

          <ConfigCard />

          <GlassCard className="p-4">
            <Section title="Backend log">
              <pre className="selectable max-h-64 overflow-auto rounded-lg border border-line bg-black/25 p-3 font-mono text-[11.5px] leading-relaxed text-fg-3">{logs.length ? logs.join('\n') : 'No output yet.'}</pre>
            </Section>
          </GlassCard>
        </div>
      </div>
    </div>
  )
}

const EFFECT_NOTES: Record<Effects, string> = {
  low: 'Flat panels and a still background. The lightest option: use it on older machines or when the app runs all day.',
  balanced: 'Frosted-glass panels over a still background. Little CPU once the window is drawn.',
  full: 'Adds the moving silk background and a pulsing status light. Without GPU acceleration this can use a whole CPU core.'
}

function AppearanceCard() {
  const effects = useEffectsLevel()
  return (
    <GlassCard className="p-4">
      <Section title="Appearance">
        <Chips
          items={[
            { id: 'low', label: 'Light (lowest CPU)' },
            { id: 'balanced', label: 'Balanced' },
            { id: 'full', label: 'Full effects' }
          ]}
          value={effects}
          onChange={setEffects}
        />
        <p className="text-[12px] text-fg-3">{EFFECT_NOTES[effects]} Applies immediately; the trading bot is not affected.</p>
      </Section>
    </GlassCard>
  )
}
