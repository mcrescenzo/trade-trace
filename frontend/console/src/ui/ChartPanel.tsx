import * as echarts from 'echarts'
import { useEffect, useRef } from 'react'

export function ChartPanel({
  title,
  rows
}: {
  title: string
  rows: Array<{ name: string; value: number }>
}) {
  const ref = useRef<HTMLDivElement | null>(null)

  useEffect(() => {
    if (!ref.current) return
    const chart = echarts.init(ref.current, undefined, { renderer: 'canvas' })
    chart.setOption({
      animation: false,
      grid: { left: 36, right: 16, top: 20, bottom: 70 },
      tooltip: { trigger: 'axis' },
      xAxis: { type: 'category', data: rows.map((row) => row.name), axisLabel: { rotate: 35 } },
      yAxis: { type: 'value' },
      series: [{ type: 'bar', data: rows.map((row) => row.value), itemStyle: { color: '#2563eb' } }]
    })
    const resize = () => chart.resize()
    window.addEventListener('resize', resize)
    return () => {
      window.removeEventListener('resize', resize)
      chart.dispose()
    }
  }, [rows])

  return (
    <article className="rounded border border-border bg-card p-4">
      <h3 className="mb-3 text-lg font-semibold">{title}</h3>
      <div ref={ref} className="h-80 w-full" role="img" aria-label={title} />
    </article>
  )
}

