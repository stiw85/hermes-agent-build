import { describe, expect, it } from 'vitest'
import { allowed, resolveCommand } from './backend.ts'

describe('IPC allowlist', () => {
  it('allows known routes, with query strings', () => {
    expect(allowed('GET', '/api/status')).toBe(true)
    expect(allowed('GET', '/api/candles?symbol=BTC/USDT&bars=300')).toBe(true)
    expect(allowed('POST', '/api/flatten')).toBe(true)
  })
  it('rejects unknown routes, wrong methods and traversal', () => {
    expect(allowed('GET', '/api/flatten')).toBe(false)
    expect(allowed('POST', '/api/status')).toBe(false)
    expect(allowed('GET', '/api/status/../bot/start')).toBe(false)
    expect(allowed('GET', '/api/status?x=../../bot/start')).toBe(false)
    expect(allowed('GET', 'http://evil.example/api/status')).toBe(false)
    expect(allowed('GET', '//evil.example/api/status')).toBe(false)
    expect(allowed('POST', '/api/order')).toBe(false)
  })
})

describe('resolveCommand', () => {
  const base = { mode: 'spawn' as const, attachUrl: '', attachTokenFile: '' }
  it('prefers an explicit command', () => {
    expect(resolveCommand({ ...base, projectDir: '/nope', command: ' /x/hermes-trader ' })).toBe('/x/hermes-trader')
  })
  it('falls back to PATH when there is no venv', () => {
    expect(resolveCommand({ ...base, projectDir: '/definitely/not/here', command: '' })).toBe('hermes-trader')
  })
})
