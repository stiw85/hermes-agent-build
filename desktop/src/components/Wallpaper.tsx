import { useEffect, useRef } from 'react'

/*
 * A calmer cousin of Herald OS's "flowing silk" wallpaper (MIT): a few slow ribbons on the
 * deep-blue field, drawn at half resolution and ~20fps, paused when hidden or motion is reduced.
 */
const RIBBONS = Array.from({ length: 7 }, (_, i) => ({
  y: 0.18 + (i / 7) * 0.7,
  amp: 0.06 + (i % 3) * 0.035,
  freq: 0.8 + (i % 4) * 0.25,
  speed: 0.06 + (i % 5) * 0.02,
  width: 30 + (i % 3) * 34,
  light: 50 + (i % 3) * 8,
  alpha: 0.16 + (i % 2) * 0.08,
  phase: i * 1.9
}))

function draw(ctx: CanvasRenderingContext2D, w: number, h: number, t: number, scale: number) {
  const g = ctx.createRadialGradient(w * 0.55, h * 0.45, h * 0.05, w * 0.5, h * 0.5, Math.max(w, h) * 0.85)
  g.addColorStop(0, '#0f37ad')
  g.addColorStop(0.5, '#08217a')
  g.addColorStop(1, '#030c31')
  ctx.globalCompositeOperation = 'source-over'
  ctx.fillStyle = g
  ctx.fillRect(0, 0, w, h)
  ctx.globalCompositeOperation = 'lighter'
  ctx.lineCap = 'round'
  for (const r of RIBBONS) {
    ctx.beginPath()
    for (let s = 0; s <= 48; s++) {
      const x = (s / 48) * w
      const nx = (s / 48) * r.freq * Math.PI * 2
      const y = h * r.y + Math.sin(nx + t * r.speed + r.phase) * h * r.amp + Math.sin(nx * 0.5 - t * r.speed * 0.7 + r.phase * 2) * h * r.amp * 0.5
      if (s === 0) ctx.moveTo(x, y)
      else ctx.lineTo(x, y)
    }
    ctx.strokeStyle = `hsla(216, 95%, ${r.light}%, ${r.alpha})`
    ctx.lineWidth = r.width * scale
    ctx.filter = `blur(${18 * scale}px)`
    ctx.stroke()
  }
  ctx.filter = 'none'
}

export function Wallpaper() {
  const ref = useRef<HTMLCanvasElement>(null)
  useEffect(() => {
    const c = ref.current
    const ctx = c?.getContext('2d')
    if (!c || !ctx) return
    const scale = 0.5
    let raf = 0
    let last = 0
    let t = Math.random() * 100
    const reduce = window.matchMedia('(prefers-reduced-motion: reduce)')
    const size = () => {
      c.width = Math.max(1, Math.floor(window.innerWidth * scale))
      c.height = Math.max(1, Math.floor(window.innerHeight * scale))
      draw(ctx, c.width, c.height, t, scale)
    }
    const frame = (now: number) => {
      raf = requestAnimationFrame(frame)
      if (now - last < 50 || document.hidden || reduce.matches) return
      t += (now - last) / 1000
      last = now
      draw(ctx, c.width, c.height, t, scale)
    }
    size()
    window.addEventListener('resize', size)
    raf = requestAnimationFrame(frame)
    return () => {
      cancelAnimationFrame(raf)
      window.removeEventListener('resize', size)
    }
  }, [])
  return <canvas ref={ref} aria-hidden="true" className="pointer-events-none fixed inset-0 h-full w-full" />
}
