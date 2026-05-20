import type { LucideIcon } from 'lucide-react'

export function MetricCard({
  label,
  value,
  icon: Icon
}: {
  label: string
  value: string | number
  icon: LucideIcon
}) {
  return (
    <article className="rounded border border-border bg-card p-4">
      <div className="flex items-center justify-between gap-3">
        <p className="text-sm font-medium text-muted-foreground">{label}</p>
        <Icon className="size-4 text-primary" aria-hidden />
      </div>
      <p className="mt-3 truncate text-3xl font-semibold">{value}</p>
    </article>
  )
}

