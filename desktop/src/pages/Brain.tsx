import { IconArrowUp, IconBrain, IconBulb, IconMessageCircle, IconNotebook, IconTool, IconTrash } from '@tabler/icons-react'
import { useEffect, useRef, useState } from 'react'
import Markdown from 'react-markdown'
import remarkGfm from 'remark-gfm'
import { EmptyGlass, GlassButton, GlassCard, PageHeader, Pill, Section, Tabs } from '../components/glass.tsx'
import { HermesMark } from '../components/Shell.tsx'
import { get, post, usePoll } from '../lib/api.ts'
import { cn } from '../lib/cn.ts'
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

function Memory() {
  const [tab, setTab] = useState<'lessons' | 'playbooks'>('lessons')
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
          { id: 'playbooks', label: 'Playbooks', count: books.data?.length }
        ]}
        value={tab}
        onChange={t => {
          setTab(t)
          setOpen(null)
        }}
      />
      <div className="min-h-0 flex-1 overflow-y-auto pr-1">
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
      <PageHeader icon={<IconBrain />} title="Brain" subtitle="What the bot has learned, its playbooks, and a line to the agent" actions={<Pill tone={status?.llm_enabled ? 'ok' : 'muted'} dot>{status?.llm_enabled ? 'LLM on' : 'LLM off'}</Pill>} />
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
