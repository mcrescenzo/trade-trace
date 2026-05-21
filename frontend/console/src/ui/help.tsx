import type { ReactNode } from 'react'
import { AlertTriangle, HelpCircle } from 'lucide-react'

export const METRIC_DEFINITIONS: Record<string, string> = {
  pnl: 'P&L is profit and loss recorded in the journal/read models. P&L rollups are local aggregate reports and are not scoped by the global filter today. It is not broker reconciliation.',
  realized_pnl: 'Realized P&L from recorded closes/reductions where the backend can match quantities and prices.',
  unrealized_pnl: 'Open-position P&L using recorded marks when available. Missing marks reduce coverage.',
  mtm_pnl: 'Mark-to-market P&L combines realized amounts with backend-valued open exposure where marks exist.',
  r: 'R is return normalized by declared risk for a decision or position. Rows without declared risk are caveated or excluded by reports.',
  mean_r: 'Average R across backend-scored rows in the selected filter.',
  expectancy_r: 'Average expected result in R units from recorded outcomes. Interpret with sample size and missing-risk caveats.',
  win_rate: 'Share of scored decisions with positive recorded result. Pending, missing, or unsupported rows may be excluded.',
  brier: 'Brier score measures probability forecast error against resolved outcomes; lower is better for that scored set.',
  brier_score: 'Brier score measures probability forecast error against resolved outcomes; lower is better for that scored set.',
  log_score: 'Log score evaluates forecast probability assigned to the resolved outcome; availability depends on backend scoring inputs.',
  ece: 'Expected calibration error compares forecast confidence buckets with observed outcome frequency. It is sensitive to low sample sizes.',
  evidence_coverage: 'Share of rows or aggregates with attached source/evidence records in the journal. It does not prove source correctness.',
  sample_size: 'Number of backend rows included in this metric or group after filters and exclusions.',
  sample_warning: 'Backend warning that the sample may be too small, sparse, or filtered for confident interpretation.',
  summary_sample_warning: 'Backend warning that the report-level sample may be too small, sparse, or filtered for confident interpretation.',
  summary_caveats: 'Report-level limitations such as missing marks, missing risk, unresolved outcomes, or sparse evidence.'
}

const CAVEAT_DEFINITIONS: Record<string, string> = {
  missing_risk: 'Missing declared risk',
  risk_missing: 'Missing declared risk',
  missing_risk_budget: 'Missing risk budget',
  missing_source: 'Missing source evidence',
  source_missing: 'Missing source evidence',
  missing_sources: 'Missing source evidence',
  missing_mark: 'Missing open-position mark',
  mark_missing: 'Missing open-position mark',
  missing_price: 'Missing recorded price',
  missing_quantity: 'Missing quantity',
  missing_strategy: 'Missing strategy link',
  missing_thesis: 'Missing thesis link',
  low_n: 'Small sample size',
  low_sample: 'Small sample size',
  insufficient_sample: 'Insufficient sample size',
  ambiguous_outcome: 'Ambiguous outcome',
  disputed_outcome: 'Disputed outcome',
  void_outcome: 'Void outcome',
  unresolved_outcome: 'Unresolved outcome',
  late_forecast: 'Forecast recorded late',
  sparse_evidence: 'Sparse evidence coverage',
  evidence_unavailable: 'Evidence unavailable',
  pending: 'Pending or unresolved row',
  open_position: 'Open position depends on marks'
}

export function humanizeKey(value: unknown): string {
  return String(value ?? '')
    .trim()
    .replace(/[_-]+/g, ' ')
    .replace(/\s+/g, ' ')
    .replace(/\b\w/g, (letter) => letter.toUpperCase())
}

export function formatCaveatLabel(value: unknown): string {
  const key = String(value ?? '').trim().toLowerCase().replace(/[\s-]+/g, '_')
  return CAVEAT_DEFINITIONS[key] ?? humanizeKey(value)
}

export function getMetricDefinition(label: string): string | undefined {
  const key = label.toLowerCase().trim().replace(/[^a-z0-9]+/g, '_').replace(/^_|_$/g, '')
  return METRIC_DEFINITIONS[key]
}

export function CaveatChips({ value }: { value: unknown }) {
  const values = Array.isArray(value) ? value : value == null || value === '' ? [] : [value]
  if (values.length === 0) return <span className="text-muted-foreground">n/a</span>
  return (
    <span className="flex flex-wrap gap-1">
      {values.map((item) => (
        <span key={String(item)} title={String(item)} className="inline-flex items-center gap-1 rounded border border-amber-500/50 bg-amber-100 px-1.5 py-0.5 text-xs font-medium text-amber-900 dark:border-amber-300/50 dark:bg-amber-300/15 dark:text-amber-100">
          <AlertTriangle className="size-3" aria-hidden />
          {formatCaveatLabel(item)}
        </span>
      ))}
    </span>
  )
}

export function MetricHelp({ label, children }: { label: string; children?: ReactNode }) {
  const definition = children ?? getMetricDefinition(label)
  if (!definition) return <>{label}</>
  return (
    <span className="inline-flex items-center gap-1" title={String(definition)}>
      <span>{label}</span>
      <HelpCircle className="size-3.5 text-muted-foreground" aria-label={`${label} definition`} />
    </span>
  )
}

export function PageExplainer({
  answers,
  data,
  read,
  mislead
}: {
  answers: string
  data: string
  read: string
  mislead: string
}) {
  return (
    <section className="mb-4 grid gap-3 rounded border border-border bg-card p-4 text-sm md:grid-cols-2 xl:grid-cols-4">
      <div><p className="font-semibold">Answers</p><p className="mt-1 text-muted-foreground">{answers}</p></div>
      <div><p className="font-semibold">Data used</p><p className="mt-1 text-muted-foreground">{data}</p></div>
      <div><p className="font-semibold">How to read it</p><p className="mt-1 text-muted-foreground">{read}</p></div>
      <div><p className="font-semibold">Can mislead when</p><p className="mt-1 text-muted-foreground">{mislead}</p></div>
    </section>
  )
}
