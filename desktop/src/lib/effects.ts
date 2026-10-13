import { useSyncExternalStore } from 'react'

/**
 * How much eye-candy the window draws. CPU cost on a typical Linux desktop (measured idle):
 * - low:      flat panels, still wallpaper, no looping animation — cheapest
 * - balanced: frosted-glass blur over a still wallpaper (default)
 * - full:     blur + the moving "silk" wallpaper + pulsing status light — costs a whole CPU core
 *             without GPU acceleration
 */
export type Effects = 'low' | 'balanced' | 'full'

const KEY = 'ht.effects'
const EVENT = 'ht-effects'
export const DEFAULT_EFFECTS: Effects = 'balanced'

function valid(v: unknown): v is Effects {
  return v === 'low' || v === 'balanced' || v === 'full'
}

export function getEffects(): Effects {
  try {
    const v = localStorage.getItem(KEY)
    if (valid(v)) return v
  } catch {
    /* storage unavailable: fall through */
  }
  return DEFAULT_EFFECTS
}

export function applyEffects(e: Effects = getEffects()): void {
  document.documentElement.dataset.effects = e
}

export function setEffects(e: Effects): void {
  try {
    localStorage.setItem(KEY, e)
  } catch {
    /* still applies for this session */
  }
  applyEffects(e)
  window.dispatchEvent(new Event(EVENT))
}

function subscribe(cb: () => void): () => void {
  window.addEventListener(EVENT, cb)
  return () => window.removeEventListener(EVENT, cb)
}

export function useEffectsLevel(): Effects {
  return useSyncExternalStore(subscribe, getEffects, () => DEFAULT_EFFECTS)
}
