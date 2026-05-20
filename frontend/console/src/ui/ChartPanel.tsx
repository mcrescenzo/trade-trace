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
      aria: { enabled: true, decal: { show: true } },
      color: ['#2563eb'],
      grid: { left: 44, right: 18, top: 28, bottom: 76, containLabel: true },
      legend: { show: true, top: 0, left: 0, data: ['Value'] },
      tooltip: { trigger: 'axis', valueFormatter: (value: unknown) => String(value) },
      xAxis: { type: 'category', name: 'Group', data: rows.map((row) => row.name), axisLabel: { rotate: 35, hideOverlap: true } },
      yAxis: { type: 'value', name: 'Value' },
      series: [{ name: 'Value', type: 'bar', data: rows.map((row) => row.value), itemStyle: { color: '#2563eb' } }]
    })
    const resize = () => chart.resize()
    const observer = new ResizeObserver(resize)
    observer.observe(ref.current)
    window.addEventListener('resize', resize)
    return () => {
      observer.disconnect()
      window.removeEventListener('resize', resize)
      chart.dispose()
    }
  }, [rows])

  return (
    <article className="min-w-0 overflow-hidden rounded border border-border bg-card p-4">
      <div className="mb-3 flex flex-wrap items-start justify-between gap-2">
        <div>
          <h3 className="text-lg font-semibold">{title}</h3>
          <p className="text-xs text-muted-foreground">Bar chart; y-axis unit is value/count as returned by the local report.</p>
        </div>
        <span className="rounded border border-border px-2 py-1 text-xs text-muted-foreground">Legend: Value</span>
      </div>
      {rows.length === 0 ? (
        <div className="rounded border border-dashed border-border bg-background/70 p-6 text-center text-sm text-muted-foreground">No chartable values were returned for this view.</div>
      ) : (
        <div ref={ref} className="h-80 w-full min-w-0" role="img" aria-label={`${title}. Bar chart of ${rows.length} value${rows.length === 1 ? '' : 's'}.`} />
      )}
    </article>
  )
}

