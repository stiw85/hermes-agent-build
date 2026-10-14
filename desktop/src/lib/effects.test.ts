import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

describe('visual effects level', () => {
  const store = new Map<string, string>()
  beforeEach(() => {
    store.clear()
    vi.stubGlobal('localStorage', {
      getItem: (k: string) => store.get(k) ?? null,
      setItem: (k: string, v: string) => void store.set(k, v)
    })
    vi.stubGlobal('document', { documentElement: { dataset: {} as Record<string, string> } })
    vi.stubGlobal('window', new EventTarget())
  })
  afterEach(() => vi.unstubAllGlobals())

  it('defaults to balanced, persists and applies a choice, ignores junk', async () => {
    const fx = await import('./effects.ts')
    expect(fx.getEffects()).toBe('balanced')
    let fired = 0
    window.addEventListener('ht-effects', () => fired++)
    fx.setEffects('low')
    expect(fx.getEffects()).toBe('low')
    expect(document.documentElement.dataset.effects).toBe('low')
    expect(fired).toBe(1)
    store.set('ht.effects', 'sparkles')
    expect(fx.getEffects()).toBe('balanced')
  })

  it('still works when storage throws (private window, blocked site data)', async () => {
    vi.stubGlobal('localStorage', { getItem: () => { throw new Error('denied') }, setItem: () => { throw new Error('denied') } })
    const fx = await import('./effects.ts')
    expect(fx.getEffects()).toBe('balanced')
    fx.setEffects('full')
    expect(document.documentElement.dataset.effects).toBe('full')
  })
})
