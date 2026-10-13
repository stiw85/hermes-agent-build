import { CandlestickChart, LineChart, ScatterChart } from 'echarts/charts'
import { DataZoomComponent, GridComponent, LegendComponent, MarkAreaComponent, MarkLineComponent, TooltipComponent } from 'echarts/components'
import * as echarts from 'echarts/core'
import { CanvasRenderer } from 'echarts/renderers'
import { useEffect, useRef } from 'react'

echarts.use([LineChart, CandlestickChart, ScatterChart, GridComponent, TooltipComponent, LegendComponent, DataZoomComponent, MarkLineComponent, MarkAreaComponent, CanvasRenderer])

export type ChartOption = echarts.EChartsCoreOption

/** Design tokens resolved for the canvas (it can't read CSS variables). */
export function chartTokens() {
  const css = getComputedStyle(document.documentElement)
  const v = (n: string, fb: string) => css.getPropertyValue(n).trim() || fb
  return {
    fg: v('--color-fg', '#f3f7ff'),
    fg2: v('--color-fg-2', 'rgba(216,228,255,.84)'),
    fg3: v('--color-fg-3', 'rgba(176,196,245,.68)'),
    line: 'rgba(140,180,255,0.14)',
    surface: '#0b1c51',
    s1: v('--color-series-1', '#4a8af7'),
    s2: v('--color-series-2', '#c2802a'),
    ok: v('--color-ok', '#36e6a6'),
    danger: v('--color-danger', '#ff6d6d'),
    tooltipBg: 'rgba(8, 26, 84, 0.96)',
    tooltipBorder: 'rgba(170, 205, 255, 0.55)'
  }
}

/** Shared axis / tooltip styling: recessive hairline grid, text tokens, crosshair. */
export function baseOption(): ChartOption {
  const t = chartTokens()
  return {
    animation: false,
    textStyle: { color: t.fg3, fontFamily: 'inherit', fontSize: 11 },
    grid: { left: 8, right: 16, top: 16, bottom: 8, containLabel: true },
    tooltip: {
      trigger: 'axis',
      axisPointer: { type: 'cross', lineStyle: { color: t.fg3, width: 1 }, crossStyle: { color: t.fg3 }, label: { backgroundColor: '#163a9c', color: t.fg } },
      backgroundColor: t.tooltipBg,
      borderColor: t.tooltipBorder,
      textStyle: { color: t.fg, fontSize: 12 },
      extraCssText: 'border-radius:10px;box-shadow:0 12px 32px rgba(0,8,50,.5);'
    }
  }
}

export function timeAxis(): Record<string, unknown> {
  const t = chartTokens()
  return {
    type: 'time',
    axisLine: { lineStyle: { color: t.line } },
    axisTick: { show: false },
    axisLabel: { color: t.fg3, hideOverlap: true },
    splitLine: { show: false }
  }
}

export function valueAxis(fmt?: (v: number) => string, position: 'left' | 'right' = 'right'): Record<string, unknown> {
  const t = chartTokens()
  return {
    type: 'value',
    scale: true,
    position,
    axisLine: { show: false },
    axisTick: { show: false },
    axisLabel: { color: t.fg3, formatter: fmt },
    splitLine: { lineStyle: { color: t.line, width: 1, type: 'solid' } }
  }
}

export function EChart({ option, height, ariaLabel, className }: { option: ChartOption; height: number | string; ariaLabel: string; className?: string }) {
  const el = useRef<HTMLDivElement>(null)
  const chart = useRef<echarts.ECharts | null>(null)

  useEffect(() => {
    if (!el.current) return
    const c = echarts.init(el.current, undefined, { renderer: 'canvas' })
    chart.current = c
    const ro = new ResizeObserver(() => c.resize())
    ro.observe(el.current)
    return () => {
      ro.disconnect()
      c.dispose()
      chart.current = null
    }
  }, [])

  useEffect(() => {
    chart.current?.setOption(option, { notMerge: true, lazyUpdate: true })
  }, [option])

  return <div ref={el} role="img" aria-label={ariaLabel} className={className} style={{ height, width: '100%' }} />
}
