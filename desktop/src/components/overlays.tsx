import { IconCheck, IconX } from '@tabler/icons-react'
import { createContext, useCallback, useContext, useEffect, useRef, useState, type ReactNode } from 'react'
import { cn } from '../lib/cn.ts'
import { GlassButton, TextInput } from './glass.tsx'

// ---- toasts ----------------------------------------------------------------------------------

interface Toast {
  id: number
  tone: 'ok' | 'danger' | 'info'
  text: string
}

const ToastCtx = createContext<(tone: Toast['tone'], text: string) => void>(() => undefined)

export function useToast() {
  return useContext(ToastCtx)
}

export function ToastHost({ children }: { children: ReactNode }) {
  const [items, setItems] = useState<Toast[]>([])
  const seq = useRef(0)
  const push = useCallback((tone: Toast['tone'], text: string) => {
    const id = ++seq.current
    setItems(xs => [...xs.slice(-3), { id, tone, text }])
    setTimeout(() => setItems(xs => xs.filter(x => x.id !== id)), tone === 'danger' ? 9000 : 4500)
  }, [])
  return (
    <ToastCtx.Provider value={push}>
      {children}
      <div className="pointer-events-none fixed right-5 bottom-5 z-[90] flex w-[380px] flex-col gap-2" aria-live="polite">
        {items.map(t => (
          <div key={t.id} className={cn('float animate-rise pointer-events-auto flex items-start gap-2.5 rounded-xl px-3.5 py-3 text-[12.5px]', t.tone === 'danger' && 'border-danger/50')}>
            <span className={cn('mt-0.5', t.tone === 'ok' ? 'text-ok' : t.tone === 'danger' ? 'text-danger' : 'text-info')}>{t.tone === 'danger' ? <IconX size={15} /> : <IconCheck size={15} />}</span>
            <span className="selectable min-w-0 flex-1 break-words text-fg">{t.text}</span>
          </div>
        ))}
      </div>
    </ToastCtx.Provider>
  )
}

// ---- confirm dialog --------------------------------------------------------------------------

export interface ConfirmSpec {
  title: string
  body: ReactNode
  confirmLabel: string
  danger?: boolean
  /** When set, the user must type this word to enable the confirm button. */
  typed?: string
  withReason?: boolean
}

const ConfirmCtx = createContext<(spec: ConfirmSpec) => Promise<{ ok: boolean; reason: string }>>(async () => ({ ok: false, reason: '' }))

export function useConfirm() {
  return useContext(ConfirmCtx)
}

export function ConfirmHost({ children }: { children: ReactNode }) {
  const [spec, setSpec] = useState<ConfirmSpec | null>(null)
  const [typed, setTyped] = useState('')
  const [reason, setReason] = useState('')
  const resolver = useRef<((v: { ok: boolean; reason: string }) => void) | null>(null)

  const ask = useCallback((s: ConfirmSpec) => {
    setSpec(s)
    setTyped('')
    setReason('')
    return new Promise<{ ok: boolean; reason: string }>(res => {
      resolver.current = res
    })
  }, [])

  const close = (ok: boolean) => {
    resolver.current?.({ ok, reason })
    resolver.current = null
    setSpec(null)
  }

  useEffect(() => {
    if (!spec) return
    const onKey = (e: KeyboardEvent) => e.key === 'Escape' && close(false)
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  })

  const canConfirm = !spec?.typed || typed.trim() === spec.typed

  return (
    <ConfirmCtx.Provider value={ask}>
      {children}
      {spec && (
        <div className="animate-fade-in fixed inset-0 z-[80] flex items-center justify-center bg-[#020a2b]/60 backdrop-blur-sm" onMouseDown={() => close(false)}>
          <div role="dialog" aria-modal="true" aria-labelledby="confirm-title" className="float animate-pop w-[460px] rounded-2xl p-5" onMouseDown={e => e.stopPropagation()}>
            <h2 id="confirm-title" className={cn('text-[16px] font-semibold', spec.danger ? 'text-danger' : 'text-fg')}>
              {spec.title}
            </h2>
            <div className="mt-2 text-[13px] text-fg-2">{spec.body}</div>
            {spec.withReason && (
              <TextInput autoFocus={!spec.typed} className="mt-4 w-full" placeholder="Reason (goes in the journal)" value={reason} onChange={e => setReason(e.target.value)} aria-label="Reason" />
            )}
            {spec.typed && (
              <div className="mt-4">
                <div className="mb-1.5 text-[12px] text-fg-3">
                  Type <span className="font-mono text-fg">{spec.typed}</span> to confirm
                </div>
                <TextInput autoFocus className="w-full font-mono" value={typed} onChange={e => setTyped(e.target.value)} aria-label={`Type ${spec.typed} to confirm`} onKeyDown={e => e.key === 'Enter' && canConfirm && close(true)} />
              </div>
            )}
            <div className="mt-5 flex justify-end gap-2">
              <GlassButton variant="ghost" onClick={() => close(false)}>
                Cancel
              </GlassButton>
              <GlassButton variant={spec.danger ? 'danger' : 'primary'} disabled={!canConfirm} onClick={() => close(true)} autoFocus={!spec.typed && !spec.withReason}>
                {spec.confirmLabel}
              </GlassButton>
            </div>
          </div>
        </div>
      )}
    </ConfirmCtx.Provider>
  )
}
