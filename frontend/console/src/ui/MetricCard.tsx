import type { LucideIcon } from 'lucide-react'

import { MetricHelp } from './help'

export function MetricCard({
  label,
  value,
  icon: Icon,
  help
}: {
  label: string
  value: string | number
  icon: LucideIcon
  help?: string
}) {
  return (
    <article className="rounded border border-border bg-card p-4">
      <div className="flex items-center justify-between gap-3">
        <p className="text-sm font-medium text-muted-foreground"><MetricHelp label={label}>{help}</MetricHelp></p>
        <Icon className="size-4 text-primary" aria-hidden />
      </div>
      <p className="mt-3 truncate text-3xl font-semibold">{value}</p>
    </article>
  )
}

