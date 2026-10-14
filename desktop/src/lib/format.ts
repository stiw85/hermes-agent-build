const money = new Intl.NumberFormat('en-AU', { minimumFractionDigits: 2, maximumFractionDigits: 2 })

export function fmtMoney(v: number | null | undefined, ccy = ''): string {
  if (v == null || !Number.isFinite(v)) return '—'
  return `${v < 0 ? '−' : ''}${ccy ? ccy + ' ' : ''}${money.format(Math.abs(v))}`
}

export function fmtSigned(v: number | null | undefined): string {
  if (v == null || !Number.isFinite(v)) return '—'
  return `${v >= 0 ? '+' : '−'}${money.format(Math.abs(v))}`
}

export function fmtPct(v: number | null | undefined, digits = 2, signed = false): string {
  if (v == null || !Number.isFinite(v)) return '—'
  const s = `${(Math.abs(v) * 100).toFixed(digits)}%`
  return signed ? `${v >= 0 ? '+' : '−'}${s}` : v < 0 ? `−${s}` : s
}

/** Prices span 0.0001 to 100,000: keep ~6 significant digits. */
export function fmtPrice(v: number | null | undefined): string {
  if (v == null || !Number.isFinite(v)) return '—'
  const a = Math.abs(v)
  const d = a >= 1000 ? 2 : a >= 1 ? 4 : 6
  return v.toLocaleString('en-AU', { minimumFractionDigits: Math.min(2, d), maximumFractionDigits: d })
}

export function fmtQty(v: number | null | undefined): string {
  if (v == null || !Number.isFinite(v)) return '—'
  return Number(v.toPrecision(6)).toString()
}

export function fmtNum(v: number | null | undefined, digits = 2): string {
  if (v == null || !Number.isFinite(v)) return '—'
  return v.toFixed(digits)
}

export function fmtTime(iso: string | null | undefined): string {
  if (!iso) return '—'
  const d = new Date(iso)
  return d.toLocaleString('en-AU', { day: '2-digit', month: 'short', hour: '2-digit', minute: '2-digit', hour12: false })
}

export function fmtAgo(iso: string | null | undefined): string {
  if (!iso) return 'never'
  const s = (Date.now() - new Date(iso).getTime()) / 1000
  if (s < 0) {
    const f = -s
    return f < 60 ? `in ${Math.round(f)}s` : f < 3600 ? `in ${Math.round(f / 60)}m` : `in ${(f / 3600).toFixed(1)}h`
  }
  return s < 60 ? `${Math.round(s)}s ago` : s < 3600 ? `${Math.round(s / 60)}m ago` : s < 86400 ? `${(s / 3600).toFixed(1)}h ago` : `${Math.round(s / 86400)}d ago`
}

export function tone(v: number | null | undefined): 'ok' | 'danger' | 'muted' {
  if (v == null || !Number.isFinite(v) || v === 0) return 'muted'
  return v > 0 ? 'ok' : 'danger'
}
