import './styles.css'

import * as Tooltip from '@radix-ui/react-tooltip'
import { QueryClient, QueryClientProvider, useQuery } from '@tanstack/react-query'
import {
  Link,
  Outlet,
  RouterProvider,
  createRootRoute,
  createRoute,
  createRouter
} from '@tanstack/react-router'
import {
  Activity,
  BarChart3,
  BookOpen,
  Boxes,
  Database,
  Gauge,
  ListFilter,
  NotebookText,
  RefreshCw,
  ShieldCheck,
  TableProperties
} from 'lucide-react'
import React from 'react'
import { createRoot } from 'react-dom/client'

import { consoleRouteCatalog, primaryNavRoutes, type ConsoleRouteDefinition } from './routeCatalog'
import { ChartPanel } from './ui/ChartPanel'
import { DataTable } from './ui/DataTable'
import { MetricCard } from './ui/MetricCard'
import { CaveatChips, MetricHelp, PageExplainer } from './ui/help'
import {
  CatalogPayload,
  EventRow,
  Page,
  ReportPayload,
  StatusPayload,
  TradeRow,
  fetchJson,
  pageQuery
} from './api'

type RecordEvent = EventRow & { payload_json?: string | null }

type JournalFilter = {
  request_id: string
  actor_id: string
  subject_kind: string
  subject_id: string
  event_type: string
}

type EventRelated = {
  decision?: Record<string, unknown> | null
  forecasts?: Array<Record<string, unknown>>
  outcomes?: Array<Record<string, unknown>>
  sources?: Array<Record<string, unknown>>
  subject_events?: RecordEvent[]
}

type ConsoleFilter = {
  strategy?: { strategy_id?: string | null }
  instrument?: { instrument_id?: string[] }
  decision?: { decision_type?: string[] }
}

const TRADE_DECISION_TYPES = ['actual_enter', 'paper_enter', 'add', 'reduce', 'actual_exit', 'paper_exit']

function stripEmptyFilter(filter: ConsoleFilter): ConsoleFilter {
  const next: ConsoleFilter = {}
  if (filter.strategy?.strategy_id) next.strategy = { strategy_id: filter.strategy.strategy_id }
  if (filter.instrument?.instrument_id?.length) next.instrument = { instrument_id: filter.instrument.instrument_id }
  if (filter.decision?.decision_type?.length) next.decision = { decision_type: filter.decision.decision_type }
  return next
}

function encodeFilter(filter: ConsoleFilter) {
  const json = JSON.stringify(stripEmptyFilter(filter))
  const bytes = new TextEncoder().encode(json)
  let binary = ''
  bytes.forEach((byte) => { binary += String.fromCharCode(byte) })
  return btoa(binary).replaceAll('+', '-').replaceAll('/', '_').replace(/=+$/, '')
}

function decodeFilter(value: string | null): ConsoleFilter {
  if (!value) return {}
  try {
    const padded = value.replaceAll('-', '+').replaceAll('_', '/') + '='.repeat((4 - (value.length % 4)) % 4)
    const binary = atob(padded)
    const bytes = Uint8Array.from(binary, (char) => char.charCodeAt(0))
    const parsed = JSON.parse(new TextDecoder().decode(bytes)) as ConsoleFilter
    return stripEmptyFilter({
      strategy: parsed.strategy?.strategy_id ? { strategy_id: parsed.strategy.strategy_id } : undefined,
      instrument: parsed.instrument?.instrument_id?.[0] ? { instrument_id: [String(parsed.instrument.instrument_id[0])] } : undefined,
      decision: parsed.decision?.decision_type?.length
        ? { decision_type: parsed.decision.decision_type.map(String).filter((item) => TRADE_DECISION_TYPES.includes(item)) }
        : undefined
    })
  } catch {
    return {}
  }
}

function useConsoleFilter() {
  const read = React.useCallback(() => decodeFilter(new URLSearchParams(window.location.search).get('f')), [])
  const [filter, setFilterState] = React.useState<ConsoleFilter>(read)
  React.useEffect(() => {
    const onPop = () => setFilterState(read())
    window.addEventListener('popstate', onPop)
    return () => window.removeEventListener('popstate', onPop)
  }, [read])
  const setFilter = React.useCallback((next: ConsoleFilter) => {
    const stripped = stripEmptyFilter(next)
    setFilterState(stripped)
    const url = new URL(window.location.href)
    if (Object.keys(stripped).length === 0) url.searchParams.delete('f')
    else url.searchParams.set('f', encodeFilter(stripped))
    window.history.pushState({}, '', `${url.pathname}${url.search}${url.hash}`)
  }, [])
  return [filter, setFilter] as const
}

function tableFilterParams(filter: ConsoleFilter, supported: Array<'strategy_id' | 'instrument_id' | 'decision_type'>) {
  return {
    strategy_id: supported.includes('strategy_id') ? filter.strategy?.strategy_id : undefined,
    instrument_id: supported.includes('instrument_id') ? filter.instrument?.instrument_id?.[0] : undefined,
    decision_type: supported.includes('decision_type') ? filter.decision?.decision_type?.[0] : undefined
  }
}

function FilterBar({ filter, onChange, supportsStrategy = true }: { filter: ConsoleFilter; onChange: (filter: ConsoleFilter) => void; supportsStrategy?: boolean }) {
  const decisionType = filter.decision?.decision_type?.[0] ?? ''
  const instrumentId = filter.instrument?.instrument_id?.[0] ?? ''
  const strategyId = filter.strategy?.strategy_id ?? ''
  const update = (patch: ConsoleFilter) => onChange(stripEmptyFilter({ ...filter, ...patch }))
  return (
    <section className="mb-4 rounded border border-border bg-card p-4">
      <div className="mb-3 flex flex-wrap items-center justify-between gap-2">
        <div>
          <h3 className="text-sm font-semibold">Supported filters</h3>
          <p className="text-xs text-muted-foreground">URL-backed local fields: decision type, instrument ID, and strategy ID where supported.</p>
        </div>
        <button type="button" className="rounded border border-border px-3 py-1 text-sm" onClick={() => onChange({})}>Clear filters</button>
      </div>
      <div className="grid gap-3 md:grid-cols-3">
        <label className="text-sm">Decision type
          <select className="mt-1 w-full rounded border border-border bg-background px-2 py-2" value={decisionType} onChange={(event) => update({ decision: { decision_type: event.target.value ? [event.target.value] : [] } })}>
            <option value="">Any supported trade type</option>
            {TRADE_DECISION_TYPES.map((item) => <option key={item} value={item}>{item}</option>)}
          </select>
        </label>
        <label className="text-sm">Instrument ID
          <input className="mt-1 w-full rounded border border-border bg-background px-2 py-2" value={instrumentId} placeholder="Exact local instrument_id" onChange={(event) => update({ instrument: { instrument_id: event.target.value.trim() ? [event.target.value.trim()] : [] } })} />
        </label>
        {supportsStrategy ? <label className="text-sm">Strategy ID
          <input className="mt-1 w-full rounded border border-border bg-background px-2 py-2" value={strategyId} placeholder="Exact strategy_id or __none__" onChange={(event) => update({ strategy: { strategy_id: event.target.value.trim() || null } })} />
        </label> : null}
      </div>
    </section>
  )
}

const queryClient = new QueryClient({
  defaultOptions: {
    queries: {
      staleTime: 15_000,
      refetchOnWindowFocus: false,
      retry: 1
    }
  }
})

const ICONS = {
  Activity,
  BarChart3,
  BookOpen,
  Boxes,
  Gauge,
  ListFilter,
  NotebookText,
  ShieldCheck,
  TableProperties
}

function useStatus() {
  return useQuery({
    queryKey: ['status'],
    queryFn: () => fetchJson<StatusPayload>('/api/console/status'),
    refetchInterval: 30_000
  })
}

function useReport(tool: string, args: Record<string, unknown> = { filter: {} }) {
  return useQuery({
    queryKey: ['report', tool, args],
    queryFn: () =>
      fetchJson<ReportPayload>(`/api/console/reports/${tool}/run`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(args)
      })
  })
}

function Shell() {
  const status = useStatus()
  const nav = primaryNavRoutes.map((route) => ({
    to: route.path,
    label: route.label,
    icon: ICONS[route.icon]
  }))

  return (
    <Tooltip.Provider>
      <div className="min-h-screen bg-background text-foreground">
        <a href="#console-main" className="sr-only focus:not-sr-only focus:fixed focus:left-3 focus:top-3 focus:z-50 focus:rounded focus:bg-card focus:px-3 focus:py-2 focus:text-sm focus:shadow">
          Skip to main content
        </a>
        <aside className="fixed inset-y-0 left-0 hidden w-64 border-r border-border bg-card/90 px-4 py-5 lg:block">
          <Link to="/" className="mb-6 flex items-center gap-3">
            <span className="grid size-10 place-items-center rounded bg-primary text-sm font-bold text-white">
              TT
            </span>
            <span>
              <span className="block text-xs uppercase tracking-wide text-muted-foreground">
                Trade Trace
              </span>
              <span className="block text-lg font-semibold">Console</span>
            </span>
          </Link>
          <nav className="space-y-1" aria-label="Primary">
            {nav.map((item) => (
              <Link
                key={item.to}
                to={item.to}
                className="flex items-center gap-3 rounded px-3 py-2 text-sm text-muted-foreground hover:bg-accent hover:text-foreground [&.active]:bg-accent [&.active]:font-medium [&.active]:text-foreground"
              >
                <item.icon className="size-4" aria-hidden />
                {item.label}
              </Link>
            ))}
          </nav>
        </aside>
        <div className="lg:pl-64">
          <header className="sticky top-0 z-20 border-b border-border bg-background/95 px-4 py-3 backdrop-blur md:px-6">
            <div className="flex flex-wrap items-center justify-between gap-3">
              <div>
                <p className="text-xs uppercase tracking-wide text-muted-foreground">
                  Local analytics dashboard
                </p>
                <h1 className="text-xl font-semibold">Read-only Console</h1>
              </div>
              <div className="flex items-center gap-2">
                <span className="rounded border border-border px-2.5 py-1 text-xs font-medium">
                  {status.data?.read_only ? 'read-only' : 'unavailable'}
                </span>
                <button
                  className="inline-flex items-center gap-2 rounded border border-border px-3 py-1.5 text-sm"
                  onClick={() => queryClient.invalidateQueries()}
                >
                  <RefreshCw className="size-4" aria-hidden />
                  Refresh
                </button>
              </div>
            </div>
            <nav className="mt-3 flex gap-2 overflow-x-auto pb-1 lg:hidden" aria-label="Mobile primary">
              {nav.map((item) => (
                <Link
                  key={item.to}
                  to={item.to}
                  className="inline-flex shrink-0 items-center gap-2 rounded border border-border px-3 py-1.5 text-sm text-muted-foreground hover:bg-accent hover:text-foreground [&.active]:bg-accent [&.active]:font-medium [&.active]:text-foreground"
                >
                  <item.icon className="size-4" aria-hidden />
                  {item.label}
                </Link>
              ))}
            </nav>
          </header>
          <main id="console-main" className="mx-auto max-w-7xl px-4 py-6 md:px-6">
            <Outlet />
          </main>
        </div>
      </div>
    </Tooltip.Provider>
  )
}

function PageHeader({ title, eyebrow }: { title: string; eyebrow: string }) {
  return (
    <div className="mb-5">
      <p className="text-sm font-medium uppercase tracking-wide text-muted-foreground">{eyebrow}</p>
      <h2 className="mt-1 text-3xl font-semibold">{title}</h2>
    </div>
  )
}

function LoadingBlock({ label = 'Loading' }: { label?: string }) {
  return (
    <div className="rounded border border-border bg-card p-5" role="status" aria-live="polite" aria-busy="true">
      <p className="text-sm font-medium text-foreground">{label}…</p>
      <div className="mt-4 grid gap-3 sm:grid-cols-3" aria-hidden>
        {[0, 1, 2].map((item) => <div key={item} className="h-16 rounded bg-muted" />)}
      </div>
    </div>
  )
}

function ErrorBlock({ error }: { error: unknown }) {
  return (
    <div className="rounded border border-danger/30 bg-danger/10 p-5 text-sm text-danger" role="alert">
      <p className="font-semibold">Unable to load data</p>
      <p className="mt-1">{error instanceof Error ? error.message : 'The local console endpoint did not return data for this view.'}</p>
    </div>
  )
}

function CopyId({ value }: { value: unknown }) {
  const text = String(value ?? '')
  return (
    <button
      type="button"
      className="font-mono text-xs underline decoration-dotted underline-offset-2"
      title="Copy ID"
      onClick={() => navigator.clipboard?.writeText(text)}
    >
      {text || 'n/a'}
    </button>
  )
}

function ChipList({ value }: { value: unknown }) {
  const values = Array.isArray(value) ? value : value == null || value === '' ? [] : [value]
  if (values.length === 0) return <span className="text-muted-foreground">n/a</span>
  return (
    <span className="flex flex-wrap gap-1">
      {values.map((item) => (
        <span key={String(item)} className="rounded border border-border px-1.5 py-0.5 text-xs">
          {String(item)}
        </span>
      ))}
    </span>
  )
}

function JsonBlock({ value }: { value: unknown }) {
  let parsed = value
  if (typeof value === 'string') {
    try {
      parsed = JSON.parse(value)
    } catch {
      parsed = value
    }
  }
  return <pre className="max-h-80 overflow-auto rounded border border-border bg-card p-3 text-xs">{typeof parsed === 'string' ? parsed : JSON.stringify(parsed, null, 2)}</pre>
}

function recordSubject(row: Record<string, unknown>, subjectKind?: string) {
  if (subjectKind === 'event') return null
  const id = String(row.decision_id ?? row.id ?? row.position_id ?? '')
  return id && subjectKind ? { kind: subjectKind, id } : null
}

function RecordDetail({ row, subjectKind }: { row: Record<string, unknown>; subjectKind?: string }) {
  const subject = recordSubject(row, subjectKind)
  const eventId = subjectKind === 'event' ? Number(row.id) : null
  const relatedEvents = useQuery({
    queryKey: ['record-events', subject?.kind, subject?.id],
    enabled: Boolean(subject),
    queryFn: () =>
      fetchJson<RecordEvent[]>(
        pageQuery('/api/console/record-events', { subject_kind: subject!.kind, subject_id: subject!.id, limit: 10 })
      )
  })
  const directEvent = useQuery({
    queryKey: ['event-detail', eventId],
    enabled: eventId != null && Number.isFinite(eventId),
    queryFn: () => fetchJson<RecordEvent>(`/api/console/events/${eventId}`)
  })
  const events = eventId != null ? (directEvent.data ? [directEvent.data] : []) : (relatedEvents.data ?? [])
  const loading = relatedEvents.isLoading || directEvent.isLoading
  return (
    <div className="space-y-3">
      <div>
        <p className="mb-1 text-xs font-semibold uppercase tracking-wide text-muted-foreground">Record fields</p>
        <JsonBlock value={row} />
      </div>
      <div>
        <p className="mb-1 text-xs font-semibold uppercase tracking-wide text-muted-foreground">Raw payload access</p>
        {loading ? (
          <p className="text-sm text-muted-foreground">Loading raw payload…</p>
        ) : events.length === 0 ? (
          <p className="text-sm text-muted-foreground">No contributing record IDs available.</p>
        ) : (
          <div className="space-y-2">
            {events.map((event) => (
              <details key={event.id} className="rounded border border-border p-3">
                <summary className="cursor-pointer text-sm font-medium">Event {event.id}: {event.event_type}</summary>
                <div className="mt-2 space-y-2">
                  <a className="text-sm underline" href={`/api/console/raw/${event.id}`} target="_blank" rel="noreferrer">
                    Open raw payload endpoint
                  </a>
                  <JsonBlock value={event.payload_json ?? event} />
                </div>
              </details>
            ))}
          </div>
        )}
      </div>
    </div>
  )
}

function ReportGroupDetail({ row, rawEnvelope }: { row: Record<string, unknown>; rawEnvelope: unknown }) {
  const recordIds = row.record_ids && typeof row.record_ids === 'object' ? row.record_ids : null
  const hasRecordIds = recordIds && Object.values(recordIds as Record<string, unknown>).some((value) => Array.isArray(value) && value.length > 0)
  return (
    <div className="space-y-3">
      <div>
        <p className="mb-1 text-xs font-semibold uppercase tracking-wide text-muted-foreground">Contributing record IDs</p>
        {hasRecordIds ? <JsonBlock value={recordIds} /> : <p className="text-sm text-muted-foreground">No contributing record IDs available.</p>}
      </div>
      <div>
        <p className="mb-1 text-xs font-semibold uppercase tracking-wide text-muted-foreground">Report group evidence</p>
        <JsonBlock value={row} />
      </div>
      <details className="rounded border border-border p-3">
        <summary className="cursor-pointer text-sm font-medium">Raw report envelope</summary>
        <div className="mt-2"><JsonBlock value={rawEnvelope ?? { message: 'Raw report envelope unavailable' }} /></div>
      </details>
    </div>
  )
}

function metricValue(metrics: Record<string, unknown> | undefined, key: string) {
  const value = metrics?.[key]
  if (value == null || value === '') return 'n/a'
  if (typeof value === 'number') return Number.isInteger(value) ? String(value) : value.toFixed(4).replace(/0+$/, '').replace(/\.$/, '')
  return String(value)
}

function recordCount(row: { record_ids?: Record<string, unknown> }, key: string) {
  const value = row.record_ids?.[key]
  return Array.isArray(value) ? value.length : 0
}

function ReportCaveatPanel({ title, query, children }: { title: string; query: ReturnType<typeof useReport>; children?: React.ReactNode }) {
  const caveats = [query.data?.summary_sample_warning, ...(query.data?.summary_caveats ?? [])].filter(Boolean)
  return (
    <section className="rounded border border-border bg-card p-4">
      <h3 className="mb-2 font-semibold">{title}</h3>
      {children ? <p className="mb-2 text-sm text-muted-foreground">{children}</p> : null}
      {caveats.length ? <CaveatChips value={caveats} /> : <p className="text-sm text-muted-foreground">No summary caveats were returned by this local report.</p>}
    </section>
  )
}

function StrategyReviewSection() {
  const performance = useReport('report.strategy_performance', { filter: {} })
  const calibration = useReport('report.compare', { base_report: 'calibration', group_by: 'strategy_id', filter: {} })
  const calibrationByKey = React.useMemo(() => new Map((calibration.data?.groups ?? []).map((row) => [row.key, row])), [calibration.data?.groups])
  const rows = (performance.data?.groups ?? []).map((row) => {
    const calibrationRow = calibrationByKey.get(row.key)
    return {
      ...row,
      calibration_metrics: calibrationRow?.metrics ?? {},
      calibration_sample_size: calibrationRow?.sample_size ?? 0,
      calibration_warning: calibrationRow?.sample_warning ?? null,
      calibration_record_ids: calibrationRow?.record_ids ?? {},
    }
  })
  return (
    <section className="space-y-3">
      <h3 className="text-lg font-semibold">Supported strategy process/performance comparison</h3>
      {performance.isLoading || calibration.isLoading ? <LoadingBlock label="Loading strategy review" /> : performance.isError ? <ErrorBlock error={performance.error} /> : calibration.isError ? <ErrorBlock error={calibration.error} /> : (
        <div className="space-y-4">
          <ReportCaveatPanel title="Comparison caveats" query={performance}>P&L/performance associations come from the strategy performance report. Calibration is joined only where the local calibration compare report has scored forecasts for the same strategy key.</ReportCaveatPanel>
          <DataTable
            rows={rows}
            emptyMessage="No strategy performance groups were returned by the local report."
            columns={[
              { key: 'label', header: 'Strategy group' },
              { key: 'sample_size', header: 'Trades' },
              { key: 'realized_pnl', header: 'Realized P&L', accessor: (row) => metricValue(row.metrics, 'realized_pnl') },
              { key: 'calibration_sample_size', header: 'Scored forecasts' },
              { key: 'brier', header: 'Brier', accessor: (row) => metricValue(row.calibration_metrics as Record<string, unknown>, 'brier') },
              { key: 'decision_evidence', header: 'Evidence', accessor: (row) => `${recordCount(row, 'decisions')} decisions / ${recordCount(row, 'positions')} positions` },
              { key: 'sample_warning', header: 'Caveats', cell: (value) => <CaveatChips value={value} /> }
            ]}
            renderDetail={(row) => <ReportGroupDetail row={{ ...row, record_ids: { ...(row.record_ids ?? {}), calibration_forecasts: (row.calibration_record_ids as Record<string, string[]>).forecasts ?? [] } }} rawEnvelope={{ performance: performance.data?.raw_envelope, calibration: calibration.data?.raw_envelope }} />}
          />
        </div>
      )}
    </section>
  )
}

function PlaybookReviewSection() {
  const adherence = useReport('report.playbook_adherence', { filter: {} })
  const rows = adherence.data?.groups ?? []
  const totalRows = numberValue(adherence.data?.summary_metrics.total_adherence_rows) ?? 0
  return (
    <section className="space-y-3">
      <h3 className="text-lg font-semibold">Supported playbook rule-adherence review</h3>
      {adherence.isLoading ? <LoadingBlock label="Loading playbook adherence" /> : adherence.isError ? <ErrorBlock error={adherence.error} /> : (
        <div className="space-y-4">
          <ReportCaveatPanel title="Adherence coverage" query={adherence}>{totalRows > 0 ? 'Rule states are shown because local decision_playbook_rules rows exist. Statuses are journaled process states, not advice or outcome causality.' : 'No local adherence rows were found; rule followed/violated/unknown states are not fabricated.'}</ReportCaveatPanel>
          {totalRows > 0 ? <DataTable
            rows={rows}
            emptyMessage="No playbook-version adherence groups were returned by the local report."
            columns={[
              { key: 'label', header: 'Playbook/version' },
              { key: 'sample_size', header: 'Decisions' },
              { key: 'followed', header: 'Followed', accessor: (row) => metricValue(row.metrics, 'followed') },
              { key: 'overridden', header: 'Violated/overridden', accessor: (row) => metricValue(row.metrics, 'overridden') },
              { key: 'considered', header: 'Considered/unknown', accessor: (row) => metricValue(row.metrics, 'considered') },
              { key: 'not_applicable', header: 'Not applicable', accessor: (row) => metricValue(row.metrics, 'not_applicable') },
              { key: 'total_adherence_rows', header: 'Rule rows', accessor: (row) => metricValue(row.metrics, 'total_adherence_rows') },
              { key: 'sample_warning', header: 'Caveats', cell: (value) => <CaveatChips value={value} /> }
            ]}
            renderDetail={(row) => <ReportGroupDetail row={row} rawEnvelope={adherence.data?.raw_envelope} />}
          /> : null}
        </div>
      )}
    </section>
  )
}

function PageTable<T extends Record<string, unknown>>({
  endpoint,
  queryKey,
  columns,
  emptyMessage,
  subjectKind,
  filters = {}
}: {
  endpoint: string
  queryKey: string
  columns: Parameters<typeof DataTable<T>>[0]['columns']
  emptyMessage: string
  subjectKind?: string
  filters?: Record<string, string | number | null | undefined>
}) {
  const [cursor, setCursor] = React.useState<string | null>(null)
  const [history, setHistory] = React.useState<string[]>([])
  const limit = 100
  const query = useQuery({
    queryKey: [queryKey, cursor, filters],
    queryFn: () => fetchJson<Page<T>>(pageQuery(endpoint, { limit, cursor, ...filters }))
  })
  const nextCursor = query.data?.next_cursor ?? null
  return query.isLoading ? (
    <LoadingBlock />
  ) : query.isError ? (
    <ErrorBlock error={query.error} />
  ) : (
    <div className="space-y-3">
      <DataTable
        rows={query.data?.rows ?? []}
        columns={columns}
        emptyMessage={emptyMessage}
        renderDetail={(row) => <RecordDetail row={row} subjectKind={subjectKind} />}
      />
      <div className="flex items-center justify-between gap-3 text-sm text-muted-foreground">
        <span>
          Showing up to {query.data?.limit ?? limit} rows{nextCursor ? '; more rows available' : ''}.
        </span>
        <div className="flex gap-2">
          <button
            type="button"
            className="rounded border border-border px-3 py-1 disabled:opacity-50"
            disabled={history.length === 0}
            onClick={() => {
              const previous = history.at(-1) ?? null
              setHistory((items) => items.slice(0, -1))
              setCursor(previous === '' ? null : previous)
            }}
          >
            Previous
          </button>
          <button
            type="button"
            className="rounded border border-border px-3 py-1 disabled:opacity-50"
            disabled={!nextCursor}
            onClick={() => {
              setHistory((items) => [...items, cursor ?? ''])
              setCursor(nextCursor)
            }}
          >
            Next
          </button>
        </div>
      </div>
    </div>
  )
}

function OverviewPage() {
  const [filter, setFilter] = useConsoleFilter()
  const reportArgs = React.useMemo(() => ({ filter: stripEmptyFilter(filter) }), [filter])
  const aggregateReportArgs = React.useMemo(() => ({}), [])
  const status = useStatus()
  const pnl = useReport('report.pnl', aggregateReportArgs)
  const risk = useReport('report.risk', aggregateReportArgs)
  const strategy = useReport('report.strategy_performance', reportArgs)
  const calibration = useReport('report.calibration', reportArgs)
  const evidence = useReport('report.source_quality', {})

  if (status.isLoading) return <LoadingBlock />
  if (status.isError) return <ErrorBlock error={status.error} />

  const counts = status.data?.row_counts ?? {}
  return (
    <>
      <PageHeader eyebrow="Dashboard" title="Journal intelligence at a glance" />
      <PageExplainer answers="What is in this local journal and which headline report metrics are available." data="/api/console/status plus backend aggregate reports. Strategy performance and calibration honor supported URL filters; P&L and risk rollups are local aggregate reports and are not scoped by the global filter today." read="Counts are journal inventory; report cards are backend aggregates with definitions on metric labels." mislead="A count is not performance, and filtered or missing report inputs can make headline metrics unavailable." />
      <FilterBar filter={filter} onChange={setFilter} />
      <section className="grid gap-4 md:grid-cols-2 xl:grid-cols-4">
        <MetricCard label="Events" value={counts.events ?? 0} icon={Database} href="/journal" />
        <MetricCard label="Decisions" value={counts.decisions ?? 0} icon={ListFilter} href="/decisions" />
        <MetricCard label="Strategies" value={counts.strategies ?? 0} icon={Boxes} href="/strategies" />
        <MetricCard label="Schema" value={status.data?.schema_version ?? 'n/a'} icon={ShieldCheck} />
      </section>
      <section className="mt-5 grid gap-4 xl:grid-cols-2">
        <ReportSummary title="P&L rollup" query={pnl} metricKeys={['realized_pnl', 'unrealized_pnl', 'mark_to_market_pnl']} href="/reports/pnl" />
        <ReportSummary title="Risk rollup" query={risk} metricKeys={['mean_r', 'expectancy_r', 'win_rate_r']} href="/reports/risk" />
        <ReportSummary title="Strategy performance" query={strategy} metricKeys={['total_trades', 'realized_pnl', 'win_rate']} href="/reports/strategy" />
        <ReportSummary title="Calibration" query={calibration} metricKeys={['sample_size', 'brier', 'ece']} href="/calibration" />
      </section>
      <section className="mt-5 grid gap-4 xl:grid-cols-2">
        <OverviewReportGroups title="P&L contributors" query={pnl} href="/reports/pnl" metricKeys={['realized_pnl', 'unrealized_pnl', 'mark_to_market_pnl']} />
        <OverviewReportGroups title="Risk contributors" query={risk} href="/reports/risk" metricKeys={['mean_r', 'expectancy_r', 'win_rate_r']} />
        <OverviewReportGroups title="Strategy contributors" query={strategy} href="/reports/strategy" metricKeys={['realized_pnl', 'closed_count', 'open_count']} />
        <OverviewReportGroups title="Calibration contributors" query={calibration} href="/calibration" metricKeys={['brier', 'ece', 'sample_size']} />
      </section>
      <section className="mt-5 grid gap-4 xl:grid-cols-2">
        <ReportCaveatPanel title="Evidence/provenance coverage" query={evidence}>Source-quality is a local journal-level diagnostic. Open Evidence to inspect contributing samples and raw envelopes.</ReportCaveatPanel>
        <UnsupportedPanel title="Trend, calendar, and equity-style views" message="Supported report envelopes in this Console do not provide period buckets or equity time series. The dashboard does not invent trend/calendar/equity metrics from frontend-only math." />
      </section>
    </>
  )
}

function ReportSummary({
  title,
  query,
  metricKeys,
  href
}: {
  title: string
  query: ReturnType<typeof useReport>
  metricKeys: string[]
  href?: string
}) {
  if (query.isLoading) return <LoadingBlock label={`Loading ${title}`} />
  if (query.isError) return <ErrorBlock error={query.error} />
  const metrics = query.data?.summary_metrics ?? {}
  const values = metricKeys.map((key) => ({
    name: key.replaceAll('_', ' '),
    value: String(metrics[key] ?? 'n/a')
  }))
  return (
    <article className="rounded border border-border bg-card p-5">
      <div className="mb-4 flex items-start justify-between gap-4">
        <div>
          <h3 className="text-lg font-semibold">{title}</h3>
          <p className="text-sm text-muted-foreground">{query.data?.evidence.cli_invocation}</p>
        </div>
        {href ? <a className="text-sm underline" href={href}>Open table</a> : null}
      </div>
      <div className="grid gap-3 sm:grid-cols-3">
        {values.map((metric) => (
          <div key={metric.name} className="rounded border border-border p-3">
            <p className="text-xs uppercase tracking-wide text-muted-foreground"><MetricHelp label={metric.name} /></p>
            <p className="mt-1 text-2xl font-semibold">{metric.value}</p>
          </div>
        ))}
      </div>
    </article>
  )
}


function UnsupportedPanel({ title, message }: { title: string; message: string }) {
  return <section className="rounded border border-border bg-card p-4"><h3 className="mb-2 font-semibold">{title}</h3><p className="text-sm text-muted-foreground">{message}</p></section>
}

function OverviewReportGroups({ title, query, href, metricKeys }: { title: string; query: ReturnType<typeof useReport>; href: string; metricKeys: string[] }) {
  if (query.isLoading) return <LoadingBlock label={`Loading ${title}`} />
  if (query.isError) return <ErrorBlock error={query.error} />
  const rows = (query.data?.groups ?? []).slice(0, 5)
  const chartRows = rows.map((row) => ({ name: row.label || row.key, value: numberValue(row.metrics?.[metricKeys[0]]) ?? row.sample_size ?? 0 }))
  const columns = [
    { key: 'label', header: 'Group' },
    { key: 'sample_size', header: 'Sample' },
    ...metricKeys.map((key) => ({ key, header: key.replaceAll('_', ' '), accessor: (row: Record<string, unknown>) => metricValue(row.metrics as Record<string, unknown>, key) })),
    { key: 'sample_warning', header: 'Caveats', cell: (value: unknown) => <CaveatChips value={value} /> }
  ]
  return (
    <section className="rounded border border-border bg-card p-4">
      <div className="mb-3 flex items-start justify-between gap-3">
        <div><h3 className="font-semibold">{title}</h3><p className="text-sm text-muted-foreground">Top local report groups; open the full dashboard for contributing examples and record IDs.</p></div>
        <a className="shrink-0 text-sm underline" href={href}>Open details</a>
      </div>
      {rows.length ? <ChartPanel title={`${title} chart`} rows={chartRows} /> : <p className="text-sm text-muted-foreground">No supported groups were returned by this report.</p>}
      <div className="mt-3"><DataTable rows={rows} emptyMessage="No supported contributors." columns={columns} renderDetail={(row) => <ReportGroupDetail row={row} rawEnvelope={query.data?.raw_envelope} />} /></div>
    </section>
  )
}

function PnlDashboardPage() {
  const reportArgs = React.useMemo(() => ({}), [])
  const query = useReport('report.pnl', reportArgs)
  const metrics = query.data?.summary_metrics ?? {}
  const groups = query.data?.groups ?? []
  const pnlBreakdown = ['realized_pnl', 'unrealized_pnl', 'mark_to_market_pnl'].map((key) => ({ name: key.replaceAll('_', ' '), value: numberValue(metrics[key]) ?? 0 }))
  const positionBreakdown = ['closed_position_count', 'open_position_count'].map((key) => ({ name: key.replaceAll('_', ' '), value: numberValue(metrics[key]) ?? 0 }))
  const groupRows = groups.map((row) => ({ ...row, realized_pnl: metricValue(row.metrics, 'realized_pnl'), unrealized_pnl: metricValue(row.metrics, 'unrealized_pnl'), mark_to_market_pnl: metricValue(row.metrics, 'mark_to_market_pnl'), closed_count: metricValue(row.metrics, 'closed_count'), open_count: metricValue(row.metrics, 'open_count') }))
  return (
    <>
      <PageHeader eyebrow="P&L" title="Realized, unrealized, and grouped performance" />
      <PageExplainer answers="What supported local position reports say about realized/unrealized P&L and open/closed counts." data="report.pnl summary metrics, groups, examples, record IDs, and raw report envelope. This local aggregate report is not scoped by the global filter today." read="Realized/unrealized totals and group rows are backend report outputs; expand rows for contributing position IDs." mislead="This is not broker reconciliation, live marking, frontend P&L math, or trading advice." />
      {query.isLoading ? <LoadingBlock /> : query.isError ? <ErrorBlock error={query.error} /> : (
        <div className="space-y-4">
          <section className="grid gap-4 md:grid-cols-2 xl:grid-cols-4">
            <MetricCard label="Realized P&L" value={metricValue(metrics, 'realized_pnl')} icon={BarChart3} href="#pnl-groups" />
            <MetricCard label="Unrealized P&L" value={metricValue(metrics, 'unrealized_pnl')} icon={BarChart3} href="#pnl-groups" />
            <MetricCard label="Total P&L" value={metricValue(metrics, 'mark_to_market_pnl')} icon={BarChart3} href="#pnl-groups" />
            <MetricCard label="Open mark coverage" value={metricValue(metrics, 'open_mark_coverage')} icon={ShieldCheck} href="#pnl-evidence" />
          </section>
          <section className="grid gap-4 xl:grid-cols-2"><ChartPanel title="P&L breakdown" rows={pnlBreakdown} /><ChartPanel title="Position state counts" rows={positionBreakdown} /></section>
          <ReportCaveatPanel title="P&L caveats" query={query}>Totals come from the backend report over local positions. Missing open marks reduce coverage; no frontend-only pricing is performed.</ReportCaveatPanel>
          <section id="pnl-groups" className="space-y-3"><h3 className="text-lg font-semibold">Grouped performance and examples</h3><DataTable rows={groupRows} emptyMessage="No P&L groups were returned by the local report." columns={[{ key: 'label', header: 'Group' }, { key: 'sample_size', header: 'Positions' }, { key: 'realized_pnl', header: 'Realized P&L' }, { key: 'unrealized_pnl', header: 'Unrealized P&L' }, { key: 'mark_to_market_pnl', header: 'Total P&L' }, { key: 'closed_count', header: 'Closed' }, { key: 'open_count', header: 'Open' }, { key: 'sample_warning', header: 'Caveats', cell: (value) => <CaveatChips value={value} /> }]} renderDetail={(row) => <ReportGroupDetail row={row} rawEnvelope={query.data?.raw_envelope} />} /></section>
          <UnsupportedPanel title="Trend/calendar/equity-like visualizations" message="report.pnl currently returns aggregate/grouped position metrics, not period buckets or an equity curve. This Console intentionally shows an unsupported state rather than deriving a time series in the frontend." />
          <details id="pnl-evidence" className="rounded border border-border p-3"><summary className="cursor-pointer text-sm font-medium">Report evidence and raw envelope</summary><div className="mt-2"><JsonBlock value={{ evidence: query.data?.evidence, raw_envelope: query.data?.raw_envelope }} /></div></details>
        </div>
      )}
    </>
  )
}

function TradesPage() {
  const [filter, setFilter] = useConsoleFilter()
  return (
    <>
      <PageHeader eyebrow="Trades" title="Trade decisions and caveats" />
      <PageExplainer answers="Which recorded trading decisions make up the trade history." data="/api/console/trades from journal decisions and position read models." read="Use filters to narrow rows; caveat chips explain missing risk, marks, sources, or other local limitations." mislead="Rows are journal-derived records, not broker statements; non-trading decisions are excluded here." />
      <FilterBar filter={filter} onChange={setFilter} />
      <PageTable<TradeRow>
        endpoint="/api/console/trades"
        queryKey="trades"
        filters={tableFilterParams(filter, ['strategy_id', 'instrument_id', 'decision_type'])}
        subjectKind="decision"
        emptyMessage="No matching trades for the selected view."
        columns={[
          { key: 'decision_id', header: 'Decision', cell: (value) => <CopyId value={value} /> },
          { key: 'decision_type', header: 'Type', cell: (value) => <ChipList value={value} /> },
          {
            key: 'instrument',
            header: 'Instrument',
            accessor: (row) => row.instrument_symbol ?? row.instrument_title ?? row.instrument_id
          },
          { key: 'side', header: 'Side' },
          { key: 'quantity', header: 'Qty' },
          { key: 'price', header: 'Price' },
          { key: 'caveats', header: 'Caveats', cell: (value) => <CaveatChips value={value} /> }
        ]}
      />
    </>
  )
}

function ReportPage({
  tool,
  title,
  args
}: {
  tool: string
  title: string
  args?: Record<string, unknown>
}) {
  const [filter, setFilter] = useConsoleFilter()
  const supportsGlobalFilter = tool !== 'report.risk'
  const reportArgs = React.useMemo(() => {
    if (tool === 'report.source_quality') return { ...(args ?? {}) }
    if (!supportsGlobalFilter) return { ...(args ?? {}) }
    return { ...(args ?? {}), filter: stripEmptyFilter(filter) }
  }, [args, filter, supportsGlobalFilter, tool])
  const query = useReport(tool, reportArgs)
  if (tool === 'report.calibration') {
    return <CalibrationPage query={query} filter={filter} setFilter={setFilter} />
  }
  if (tool === 'report.source_quality') {
    return <EvidencePage query={query} />
  }
  if (tool === 'report.pnl') {
    return <PnlDashboardPage />
  }
  if (tool === 'report.risk') {
    return <RiskDashboardPage query={query} />
  }
  const metrics = query.data?.summary_metrics ?? {}
  const chartRows = Object.entries(metrics)
    .filter(([, value]) => typeof value === 'number')
    .slice(0, 8)
    .map(([name, value]) => ({ name: name.replaceAll('_', ' '), value: Number(value) }))

  return (
    <>
      <PageHeader eyebrow="Report" title={title} />
      <PageExplainer answers={supportsGlobalFilter ? "What this backend report says for the selected local filter." : "What this backend aggregate report says for the local journal."} data={`${tool} report output, summary metrics, groups, evidence, and raw report envelope.${supportsGlobalFilter ? '' : ' This local aggregate report is not scoped by the global filter today.'}`} read="Metric labels include definitions where known; group rows show sample size and warnings." mislead="Low sample size, missing inputs, or comparisons across groups do not establish causality or advice." />
      {supportsGlobalFilter ? <FilterBar filter={filter} onChange={setFilter} /> : null}
      {query.isLoading ? (
        <LoadingBlock />
      ) : query.isError ? (
        <ErrorBlock error={query.error} />
      ) : (
        <div className="space-y-4">
          <section className="grid gap-4 md:grid-cols-2 xl:grid-cols-4">
            {Object.entries(metrics)
              .slice(0, 8)
              .map(([key, value]) => (
                <MetricCard key={key} label={key.replaceAll('_', ' ')} value={String(value ?? 'n/a')} icon={BarChart3} />
              ))}
          </section>
          <ChartPanel title="Metric profile" rows={chartRows} />
          <DataTable
            rows={query.data?.groups ?? []}
            columns={[
              { key: 'label', header: 'Group' },
              { key: 'sample_size', header: 'Sample' },
              { key: 'sample_warning', header: 'Warning', cell: (value) => <CaveatChips value={value} /> },
              { key: 'metrics', header: 'Metrics' }
            ]}
            renderDetail={(row) => <ReportGroupDetail row={row} rawEnvelope={query.data?.raw_envelope} />}
          />
        </div>
      )}
    </>
  )
}

function reportGroups(report: ReportPayload | undefined) {
  return (report?.groups ?? []) as Array<Record<string, unknown> & { metrics?: Record<string, unknown>; record_ids?: Record<string, string[]> }>
}

function ProcessReportError({ title, query }: { title: string; query: ReturnType<typeof useReport> }) {
  if (!query.isError) return null
  return <UnsupportedPanel title={`${title} unavailable`} message={`The local ${title} report did not return a supported envelope: ${query.error instanceof Error ? query.error.message : 'unknown error'}. This panel is deferred instead of simulated.`} />
}

function decisionVelocityFilter(filter: ConsoleFilter): ConsoleFilter {
  return stripEmptyFilter({ decision: filter.decision })
}

function ProcessAnalyticsPage() {
  const [filter, setFilter] = useConsoleFilter()
  const emptyReportArgs = React.useMemo(() => ({ filter: {} }), [])
  const staleWatchArgs = React.useMemo(() => ({ filter: {}, mode: 'stale' }), [])
  const velocityArgs = React.useMemo(() => ({ filter: decisionVelocityFilter(filter), bucket: 'week' }), [filter])
  const mistakes = useReport('report.mistakes', emptyReportArgs)
  const strengths = useReport('report.strengths', emptyReportArgs)
  const watchlist = useReport('report.watchlist', staleWatchArgs)
  const unscored = useReport('report.unscored_forecasts', emptyReportArgs)
  const velocity = useReport('report.decision_velocity', velocityArgs)
  const loading = [mistakes, strengths, watchlist, unscored, velocity].some((query) => query.isLoading)
  const tagRows = (label: string, report: ReportPayload | undefined) => reportGroups(report).map((row) => ({
    ...row,
    panel: label,
    tag: row.key,
    decision_count: metricValue(row.metrics, 'decision_count'),
    scored_forecast_count: metricValue(row.metrics, 'scored_forecast_count'),
    mean_brier: metricValue(row.metrics, 'mean_brier')
  }))
  const watchRows = reportGroups(watchlist.data).map((row) => ({ ...row, age_days: metricValue(row.metrics, 'age_days'), review_by: metricValue(row.metrics, 'review_by'), overdue: metricValue(row.metrics, 'overdue') }))
  const unscoredRows = reportGroups(unscored.data).map((group) => ({
    ...group,
    examples_count: Array.isArray(group.examples) ? group.examples.length : 0,
    forecast_record_count: recordCount(group, 'forecasts')
  }))
  const velocityRows = reportGroups(velocity.data).map((row) => ({ ...row, key: String(row.key ?? ''), count: metricValue(row.metrics, 'count'), by_type: row.metrics?.by_type ?? {} }))
  return (
    <>
      <PageHeader eyebrow="Process" title="Supported local process analytics" />
      <PageExplainer answers="What existing local reports observe about recurring tags, stale watches, unscored forecast backlog, and decision-count velocity." data="report.mistakes, report.strengths, report.watchlist(mode=stale), report.unscored_forecasts, and report.decision_velocity envelopes with examples, record IDs, warnings, and caveats. Process subreports differ in filter support: mistake, strength, watchlist, and unscored backlog panels are intentionally run with empty filters; only decision velocity receives the supported decision-type slice of the URL filter." read="Rows use language such as associated with and observed in local records. Brier/tag rows are associations over scored forecasts, not causes. Backlog panels show only fields supplied by local report models." mislead="This page does not infer psychology, causality, coaching advice, broker/live market data, community benchmarks, or unsupported cost metrics." />
      <FilterBar filter={filter} onChange={setFilter} />
      <section className="mb-4 rounded border border-border bg-card p-4">
        <h3 className="mb-2 font-semibold">Process filter support</h3>
        <p className="text-sm text-muted-foreground">The selector is URL-backed for navigation consistency, but these local process reports do not share one filter contract. Mistakes, strengths, stale watchlist, and unscored forecasts are requested with empty filters because their backend contracts reject non-empty filter leaves. Decision velocity is requested only with the supported decision_type filter; instrument and strategy selections are not applied to process report calls.</p>
      </section>
      {loading ? <LoadingBlock label="Loading supported process reports" /> : (
        <div className="space-y-4">
          <section className="grid gap-4 md:grid-cols-2 xl:grid-cols-5">
            <MetricCard label="Mistake tags observed" value={metricValue(mistakes.data?.summary_metrics, 'tag_count')} icon={Activity} href="#process-tags" />
            <MetricCard label="Strength tags observed" value={metricValue(strengths.data?.summary_metrics, 'tag_count')} icon={ShieldCheck} href="#process-tags" />
            <MetricCard label="Stale watches" value={metricValue(watchlist.data?.summary_metrics, 'watch_count')} icon={ListFilter} href="#process-watch" />
            <MetricCard label="Unscored forecasts" value={metricValue(unscored.data?.summary_metrics, 'unscored_count')} icon={Database} href="#process-unscored" />
            <MetricCard label="Decisions counted" value={metricValue(velocity.data?.summary_metrics, 'total_decisions')} icon={BarChart3} href="#process-velocity" />
          </section>
          {[mistakes, strengths, watchlist, unscored, velocity].map((query, index) => <ProcessReportError key={index} title={['mistakes', 'strengths', 'watchlist', 'unscored forecasts', 'decision velocity'][index]} query={query} />)}
          <section id="process-tags" className="space-y-3">
            <h3 className="text-lg font-semibold">Recurring tag associations observed in local records</h3>
            <p className="text-sm text-muted-foreground">Mistake and strength reports rank decision tags by backend mean Brier where scored forecasts exist. These are associated with calibration outcomes in local records; they are not caused-by claims.</p>
            <DataTable rows={[...tagRows('mistake association', mistakes.data), ...tagRows('strength association', strengths.data)]} emptyMessage="No supported mistake/strength tag groups were returned." columns={[{ key: 'panel', header: 'Report' }, { key: 'tag', header: 'Tag' }, { key: 'decision_count', header: 'Decisions' }, { key: 'scored_forecast_count', header: 'Scored forecasts' }, { key: 'mean_brier', header: 'Mean Brier' }, { key: 'sample_warning', header: 'Warning', cell: (value) => <CaveatChips value={value} /> }]} renderDetail={(row) => <ReportGroupDetail row={row} rawEnvelope={row.panel === 'mistake association' ? mistakes.data?.raw_envelope : strengths.data?.raw_envelope} />} />
          </section>
          <section id="process-watch" className="space-y-3">
            <h3 className="text-lg font-semibold">Stale watchlist backlog observed in local records</h3>
            <DataTable rows={watchRows} emptyMessage="No stale watch decisions were returned by report.watchlist." columns={[{ key: 'label', header: 'Watch' }, { key: 'age_days', header: 'Age days' }, { key: 'review_by', header: 'Review by' }, { key: 'overdue', header: 'Overdue' }]} renderDetail={(row) => <ReportGroupDetail row={row} rawEnvelope={watchlist.data?.raw_envelope} />} />
          </section>
          <section id="process-unscored" className="space-y-3">
            <h3 className="text-lg font-semibold">Unscored forecast backlog observed in local records</h3>
            <DataTable rows={unscoredRows} emptyMessage="No unscored forecast backlog was returned by report.unscored_forecasts." columns={[{ key: 'label', header: 'Backlog group' }, { key: 'sample_size', header: 'Forecasts' }, { key: 'examples_count', header: 'Examples' }, { key: 'forecast_record_count', header: 'Record IDs' }, { key: 'sample_warning', header: 'Warning', cell: (value) => <CaveatChips value={value} /> }]} renderDetail={(row) => <ReportGroupDetail row={row} rawEnvelope={unscored.data?.raw_envelope} />} />
          </section>
          <section id="process-velocity" className="space-y-3">
            <h3 className="text-lg font-semibold">Decision velocity/count buckets observed in local records</h3>
            <ChartPanel title="Weekly decision counts" rows={velocityRows.map((row) => ({ name: String(row.key), value: Number(row.metrics?.count ?? 0) }))} />
            <DataTable rows={velocityRows} emptyMessage="No decision velocity buckets were returned by report.decision_velocity." columns={[{ key: 'label', header: 'Bucket' }, { key: 'count', header: 'Decision count' }, { key: 'by_type', header: 'By type' }]} renderDetail={(row) => <ReportGroupDetail row={row} rawEnvelope={velocity.data?.raw_envelope} />} />
          </section>
          <UnsupportedPanel title="Deferred unsupported process features" message="Psychology scoring, mentor/community comparisons, prescriptive coaching, tag co-occurrence, and cost/frequency/example panels beyond fields returned by these local reports need an explicit backend data contract. Follow-up candidate: add a read-only process analytics contract that supplies supported co-occurrence and cost fields with caveats and examples." />
        </div>
      )}
    </>
  )
}

type PeriodControls = { decision_at_gte: string; decision_at_lt: string }

function isoFromLocalInput(value: string) {
  return value ? new Date(value).toISOString() : undefined
}

function reviewVelocityFilter(period: PeriodControls): Record<string, unknown> {
  const timeWindow = {
    decision_at_gte: isoFromLocalInput(period.decision_at_gte),
    decision_at_lt: isoFromLocalInput(period.decision_at_lt)
  }
  return { time_window: Object.fromEntries(Object.entries(timeWindow).filter(([, value]) => value)) }
}

function reportCaveats(label: string, report: ReportPayload | undefined) {
  return [report?.summary_sample_warning, ...(report?.summary_caveats ?? [])]
    .filter(Boolean)
    .map((caveat) => ({ report: label, caveat }))
}

function hasEvidenceMetadata(report: ReportPayload | undefined) {
  return Boolean(report?.evidence && typeof report.evidence === 'object' && ('record_ids' in report.evidence || 'examples' in report.evidence))
}

function evidenceCount(report: ReportPayload | undefined) {
  return Object.values(report?.evidence?.record_ids ?? {}).reduce((total, ids) => total + (Array.isArray(ids) ? ids.length : 0), 0)
}

function ReviewMetric({ title, query, metrics, href, note }: { title: string; query: ReturnType<typeof useReport>; metrics: string[]; href: string; note: string }) {
  if (query.isLoading) return <LoadingBlock label={`Loading ${title}`} />
  if (query.isError) return <UnsupportedPanel title={`${title} unavailable`} message={`The local report did not return a supported envelope: ${query.error instanceof Error ? query.error.message : 'unknown error'}. This section is labeled unavailable rather than simulated.`} />
  return (
    <article className="rounded border border-border bg-card p-4">
      <div className="mb-3 flex items-start justify-between gap-3">
        <div><h3 className="font-semibold">{title}</h3><p className="text-xs text-muted-foreground">{note}</p></div>
        <a className="shrink-0 text-sm underline" href={href}>Open evidence</a>
      </div>
      <div className="grid gap-2 sm:grid-cols-3">
        {metrics.map((key) => <div key={key} className="rounded border border-border p-2"><p className="text-xs uppercase tracking-wide text-muted-foreground"><MetricHelp label={key.replaceAll('_', ' ')} /></p><p className="font-semibold">{metricValue(query.data?.summary_metrics, key)}</p></div>)}
      </div>
      <div className="mt-3"><CaveatChips value={[query.data?.summary_sample_warning, ...(query.data?.summary_caveats ?? [])].filter(Boolean)} /></div>
    </article>
  )
}

function ReviewExamples({ title, query, href }: { title: string; query: ReturnType<typeof useReport>; href: string }) {
  if (query.isLoading || query.isError) return null
  const exampleRows = (query.data?.groups ?? []).slice(0, 4).map((row) => ({ ...row, evidence_records: Object.values(row.record_ids ?? {}).reduce((total, ids) => total + (Array.isArray(ids) ? ids.length : 0), 0) }))
  return (
    <section className="space-y-3">
      <div className="flex items-start justify-between gap-3"><div><h3 className="text-lg font-semibold">{title}</h3><p className="text-sm text-muted-foreground">Displayed only from returned report groups; labels are observed contributors, not advice or causal rankings.</p></div><a className="text-sm underline" href={href}>Open full report</a></div>
      <DataTable rows={exampleRows} emptyMessage="No supported examples/groups were returned for this section." columns={[{ key: 'label', header: 'Observed group' }, { key: 'sample_size', header: 'N' }, { key: 'evidence_records', header: 'Evidence IDs' }, { key: 'sample_warning', header: 'Low-N/caveats', cell: (value) => <CaveatChips value={value} /> }]} renderDetail={(row) => <ReportGroupDetail row={row} rawEnvelope={query.data?.raw_envelope} />} />
    </section>
  )
}

function ReviewPage() {
  const [period, setPeriod] = React.useState<PeriodControls>({ decision_at_gte: '', decision_at_lt: '' })
  const [copied, setCopied] = React.useState(false)
  const emptyArgs = React.useMemo(() => ({ filter: {} }), [])
  const staleArgs = React.useMemo(() => ({ filter: {}, mode: 'stale' }), [])
  const velocityArgs = React.useMemo(() => ({ filter: reviewVelocityFilter(period), bucket: 'week' }), [period])
  const pnl = useReport('report.pnl', {})
  const risk = useReport('report.risk', {})
  const strategy = useReport('report.strategy_performance', emptyArgs)
  const calibration = useReport('report.calibration', emptyArgs)
  const evidence = useReport('report.source_quality', {})
  const mistakes = useReport('report.mistakes', emptyArgs)
  const strengths = useReport('report.strengths', emptyArgs)
  const watchlist = useReport('report.watchlist', staleArgs)
  const unscored = useReport('report.unscored_forecasts', emptyArgs)
  const playbook = useReport('report.playbook_adherence', emptyArgs)
  const velocity = useReport('report.decision_velocity', velocityArgs)
  const reportQueries = { pnl, risk, strategy, calibration, evidence, mistakes, strengths, stale_watchlist: watchlist, unscored_forecasts: unscored, playbook_adherence: playbook, decision_velocity: velocity }
  const reports: Record<string, ReportPayload> = Object.fromEntries(Object.entries(reportQueries).filter(([, query]) => query.isSuccess && query.data).map(([label, query]) => [label, query.data as ReportPayload]))
  const reportStatus: Record<string, { status: 'loading' | 'loaded' | 'unavailable'; error?: string }> = Object.fromEntries(Object.entries(reportQueries).map(([label, query]) => [label, { status: query.isLoading ? 'loading' : query.isError ? 'unavailable' : query.data ? 'loaded' : 'unavailable', error: query.isError ? (query.error instanceof Error ? query.error.message : 'unknown error') : undefined }]))
  const unavailableReports = Object.entries(reportStatus).filter(([, status]) => status.status !== 'loaded').map(([report, status]) => ({ report, status: status.status, error: status.error ?? '' }))
  const packet = { generated_in_browser_at: new Date().toISOString(), scope: { local_only: true, saved: false, period_filter_applied_only_to: 'report.decision_velocity', period }, report_status: reportStatus, unavailable_reports: unavailableReports, reports }
  const caveatRows = Object.entries(reports).flatMap(([label, report]) => reportCaveats(label, report))
  const evidenceRows = Object.entries(reports).filter(([, report]) => hasEvidenceMetadata(report)).map(([label, report]) => ({ report: label, evidence_record_ids: evidenceCount(report), examples: report?.evidence?.examples?.length ?? 0, caveats: [report?.summary_sample_warning, ...(report?.summary_caveats ?? [])].filter(Boolean).length }))
  const loading = Object.values(reportQueries).some((query) => query.isLoading)
  return (
    <>
      <PageHeader eyebrow="Edge review" title="Local period review packet" />
      <PageExplainer answers="A concise, read-only review of existing local aggregate report envelopes for human inspection." data="Overview/P&L/Risk/Strategy/Calibration/Evidence/Process aggregates already exposed by the Console. Optional decision_at dates are sent only to report.decision_velocity, the report with supported period filters." read="Snapshot cards are aggregate local reports unless explicitly marked period-scoped. Caveats, evidence counts, examples, and backlog rows are surfaced only when backend envelopes provide them." mislead="This page is not saved, cloud-shared, broker/live data, financial advice, next-trade recommendations, or frontend-invented period P&L/risk math." />
      <section className="mb-4 rounded border border-border bg-card p-4">
        <div className="mb-3"><h3 className="font-semibold">Period controls</h3><p className="text-sm text-muted-foreground">Optional local datetime range. Applied only to decision velocity/count buckets. Other reports below are labeled local aggregate snapshots because their backend contracts reject period filters today.</p></div>
        <div className="grid gap-3 md:grid-cols-3">
          <label className="text-sm">Decision at start<input type="datetime-local" className="mt-1 w-full rounded border border-border bg-background px-2 py-2" value={period.decision_at_gte} onChange={(event) => setPeriod((current) => ({ ...current, decision_at_gte: event.target.value }))} /></label>
          <label className="text-sm">Decision at end<input type="datetime-local" className="mt-1 w-full rounded border border-border bg-background px-2 py-2" value={period.decision_at_lt} onChange={(event) => setPeriod((current) => ({ ...current, decision_at_lt: event.target.value }))} /></label>
          <div className="flex items-end"><button type="button" className="rounded border border-border px-3 py-2 text-sm" onClick={() => setPeriod({ decision_at_gte: '', decision_at_lt: '' })}>Clear period</button></div>
        </div>
      </section>
      {loading ? <LoadingBlock label="Loading local review packet" /> : <div className="space-y-5">
        <section className="grid gap-4 xl:grid-cols-2">
          <ReviewMetric title="P&L snapshot" query={pnl} metrics={['realized_pnl', 'unrealized_pnl', 'mark_to_market_pnl']} href="/reports/pnl" note="Local aggregate snapshot; not period-scoped." />
          <ReviewMetric title="Risk snapshot" query={risk} metrics={['n_closed_with_risk', 'expectancy_r', 'win_rate_r']} href="/reports/risk" note="Local aggregate snapshot; not period-scoped." />
          <ReviewMetric title="Strategy snapshot" query={strategy} metrics={['total_trades', 'realized_pnl', 'win_rate']} href="/reports/strategy" note="Local aggregate snapshot; not period-scoped here." />
          <ReviewMetric title="Calibration snapshot" query={calibration} metrics={['sample_size', 'brier', 'ece']} href="/calibration" note="Local aggregate snapshot; not period-scoped here." />
          <ReviewMetric title="Evidence diagnostics" query={evidence} metrics={['total_sources', 'total_source_attachments', 'diagnostic_count']} href="/evidence" note="Journal-level source-quality diagnostics." />
          <ReviewMetric title="Decision velocity" query={velocity} metrics={['total_decisions', 'bucket_count', 'avg_per_bucket']} href="/reports/performance" note="Only this card/table uses the selected decision_at period when present." />
        </section>
        <section className="grid gap-4 md:grid-cols-3">
          <MetricCard label="Stale watches observed" value={metricValue(watchlist.data?.summary_metrics, 'watch_count')} icon={ListFilter} href="/process#process-watch" />
          <MetricCard label="Unscored forecasts" value={metricValue(unscored.data?.summary_metrics, 'unscored_count')} icon={Database} href="/process#process-unscored" />
          <MetricCard label="Playbook rows" value={metricValue(playbook.data?.summary_metrics, 'total_adherence_rows')} icon={BookOpen} href="/playbooks" />
        </section>
        <section className="space-y-3"><h3 className="text-lg font-semibold">Review packet links</h3><div className="flex flex-wrap gap-2">{[['P&L','/reports/pnl'], ['Risk','/reports/risk'], ['Strategy','/reports/strategy'], ['Calibration','/calibration'], ['Evidence','/evidence'], ['Process','/process'], ['Journal','/journal'], ['Decisions','/decisions']].map(([label, href]) => <a key={href} className="rounded border border-border px-3 py-2 text-sm underline" href={href}>{label}</a>)}</div></section>
        <ReviewExamples title="Observed performance/process groups" query={strategy} href="/reports/strategy" />
        <ReviewExamples title="Observed mistake associations" query={mistakes} href="/process#process-tags" />
        <ReviewExamples title="Observed strength associations" query={strengths} href="/process#process-tags" />
        <section className="grid gap-4 xl:grid-cols-2">
          <section className="space-y-3"><h3 className="text-lg font-semibold">Recurring caveats and low-N warnings</h3><DataTable rows={caveatRows} emptyMessage="No summary caveats were returned by loaded reports." columns={[{ key: 'report', header: 'Report' }, { key: 'caveat', header: 'Caveat/warning', cell: (value) => <CaveatChips value={value} /> }]} /></section>
          <section className="space-y-3"><h3 className="text-lg font-semibold">Evidence gaps and links</h3><DataTable rows={evidenceRows} emptyMessage="No evidence metadata was returned by loaded reports." columns={[{ key: 'report', header: 'Report' }, { key: 'evidence_record_ids', header: 'Record IDs' }, { key: 'examples', header: 'Examples' }, { key: 'caveats', header: 'Caveats' }]} /></section>
        </section>
        <section className="space-y-3"><h3 className="text-lg font-semibold">Unavailable report slots</h3><DataTable rows={unavailableReports} emptyMessage="All requested report envelopes loaded successfully." columns={[{ key: 'report', header: 'Report' }, { key: 'status', header: 'Status' }, { key: 'error', header: 'Error' }]} /></section>
        <UnsupportedPanel title="Unsupported/deferred review features" message="Saved reviews, journal mutations, cloud sharing, community/mentor review, advice, recommendations for next trades, and period-scoped P&L/risk/strategy/calibration/evidence are not performed by this local page. Unsupported sections are labeled instead of inferred." />
        <details className="rounded border border-border p-3"><summary className="cursor-pointer text-sm font-medium">Displayed local review JSON packet</summary><div className="my-3"><button type="button" className="rounded border border-border px-3 py-1 text-sm" onClick={() => { navigator.clipboard?.writeText(JSON.stringify(packet, null, 2)); setCopied(true) }}>Copy displayed review JSON</button>{copied ? <span className="ml-2 text-sm text-muted-foreground">Copied in browser.</span> : null}</div><JsonBlock value={packet} /></details>
      </div>}
    </>
  )
}

function rawData(report: ReportPayload | undefined): Record<string, unknown> {
  const envelope = report?.raw_envelope
  return envelope && typeof envelope === 'object' && 'data' in envelope && typeof (envelope as { data?: unknown }).data === 'object'
    ? ((envelope as { data: Record<string, unknown> }).data ?? {})
    : {}
}

function numberValue(value: unknown) {
  return typeof value === 'number' && Number.isFinite(value) ? value : null
}

function realRecordId(value: unknown) {
  if (typeof value !== 'string') return null
  const trimmed = value.trim()
  return trimmed.length > 0 ? trimmed : null
}

function RiskDashboardPage({ query }: { query: ReturnType<typeof useReport> }) {
  const metrics = query.data?.summary_metrics ?? {}
  const data = rawData(query.data)
  const summary = data.summary && typeof data.summary === 'object' ? data.summary as Record<string, unknown> : {}
  const distribution = Array.isArray(metrics.r_distribution) ? metrics.r_distribution as Array<Record<string, unknown>> : []
  const histogramRows = distribution.map((row) => ({ ...row, bucket: `${row.lower == null ? '-∞' : row.lower} to ${row.upper == null ? '+∞' : row.upper}` }))
  const outcomeRows = [
    { outcome: 'Wins', count: metrics.win_count, definition: 'closed rows with positive realized R' },
    { outcome: 'Losses', count: metrics.loss_count, definition: 'closed rows with negative realized R' },
    { outcome: 'Breakeven', count: metrics.breakeven_count, definition: 'closed rows with zero realized R' },
    { outcome: 'Pending with risk', count: metrics.n_pending_with_risk ?? summary.pending_risk_count, definition: 'declared-risk decisions without closed/resolved P&L yet' },
    { outcome: 'Missing risk budget', count: summary.missing_risk_count, definition: 'closed decisions excluded because declared_risk_amount is missing or zero' }
  ]
  const missingRiskSample = Array.isArray(summary.decisions_missing_risk_sample) ? summary.decisions_missing_risk_sample : []
  const groupExamples = (query.data?.groups ?? []).flatMap((group) => Array.isArray((group as Record<string, unknown>).examples) ? (group as Record<string, unknown>).examples as Array<Record<string, unknown>> : [])
  const examples = query.data?.evidence.examples?.length ? query.data.evidence.examples : groupExamples
  const coverage = numberValue(metrics.coverage)
  return (
    <>
      <PageHeader eyebrow="Risk" title="Risk/R-multiple and position analytics" />
      <PageExplainer answers="What the local report can say about realized R-multiples, expectancy, outcomes, payoff, pending-risk rows, and missing risk budgets." data="report.risk summary metrics, R distribution bins, backend caveats, group evidence, examples, and contributing local decision IDs only." read="R metrics include only closed/resolved positions with declared risk. Missing-risk and pending-risk counts explain what was excluded or incomplete." mislead="Low sample size, incomplete outcomes, or missing risk budgets can dominate results. This is not portfolio/live-risk modeling, VaR, leverage/margin analysis, or trading advice." />
      {query.isLoading ? <LoadingBlock /> : query.isError ? <ErrorBlock error={query.error} /> : (
        <div className="space-y-4">
          <section className="rounded border border-warning/40 bg-warning/10 p-4">
            <h3 className="mb-2 font-semibold text-warning">Interpretation limits</h3>
            <p className="mb-2 text-sm text-muted-foreground">This dashboard displays backend-supported local report fields only. It does not infer risk for rows without declared_risk_amount and does not model live exposure.</p>
            <CaveatChips value={[query.data?.summary_sample_warning, ...(query.data?.summary_caveats ?? [])].filter(Boolean)} />
          </section>
          <section className="grid gap-4 md:grid-cols-2 xl:grid-cols-4">
            <MetricCard label="Closed with R" value={metricValue(metrics, 'n_closed_with_risk')} icon={Activity} />
            <MetricCard label="Expectancy R" value={metricValue(metrics, 'expectancy_r')} icon={BarChart3} />
            <MetricCard label="Win rate R" value={metricValue(metrics, 'win_rate_r')} icon={BarChart3} />
            <MetricCard label="Payoff ratio R" value={metricValue(metrics, 'payoff_ratio_r')} icon={BarChart3} />
            <MetricCard label="Mean R" value={metricValue(metrics, 'mean_r')} icon={BarChart3} />
            <MetricCard label="Median R" value={metricValue(metrics, 'median_r')} icon={BarChart3} />
            <MetricCard label="Best R" value={metricValue(metrics, 'best_r')} icon={BarChart3} />
            <MetricCard label="Worst R" value={metricValue(metrics, 'worst_r')} icon={BarChart3} />
          </section>
          <section className="grid gap-4 md:grid-cols-3">
            <div className="rounded border border-border bg-card p-4"><p className="text-sm font-medium">Risk coverage</p><p className="mt-1 text-2xl font-semibold">{coverage == null ? 'n/a' : `${Math.round(coverage * 100)}%`}</p><p className="mt-1 text-xs text-muted-foreground">closed rows with declared risk divided by total closed rows, from report.risk</p></div>
            <div className="rounded border border-border bg-card p-4"><p className="text-sm font-medium">Pending risk rows</p><p className="mt-1 text-2xl font-semibold">{metricValue(metrics, 'n_pending_with_risk')}</p><p className="mt-1 text-xs text-muted-foreground">declared risk exists, but outcome/P&L is incomplete</p></div>
            <div className="rounded border border-border bg-card p-4"><p className="text-sm font-medium">Missing risk budgets</p><p className="mt-1 text-2xl font-semibold">{String(summary.missing_risk_count ?? 'n/a')}</p><p className="mt-1 text-xs text-muted-foreground">excluded from R metrics; inspect samples below when returned</p></div>
          </section>
          <ChartPanel title="R-multiple distribution" rows={histogramRows.map((row: Record<string, unknown>) => ({ name: String(row.bucket), value: Number(row.count ?? 0) }))} />
          <DataTable rows={histogramRows} emptyMessage="No R distribution bins were returned by the local risk report." columns={[{ key: 'bucket', header: 'R bucket' }, { key: 'count', header: 'Count' }]} renderDetail={(row) => <JsonBlock value={row} />} />
          <DataTable rows={outcomeRows} columns={[{ key: 'outcome', header: 'Outcome/risk status' }, { key: 'count', header: 'Count' }, { key: 'definition', header: 'Definition' }]} />
          <DataTable rows={(query.data?.groups ?? []).map((row) => ({ ...row, ...row.metrics }))} emptyMessage="No risk groups were returned by the local report." columns={[{ key: 'label', header: 'Group' }, { key: 'sample_size', header: 'Closed with R' }, { key: 'mean_r', header: 'Mean R' }, { key: 'expectancy_r', header: 'Expectancy R' }, { key: 'win_rate_r', header: 'Win rate R' }, { key: 'payoff_ratio_r', header: 'Payoff' }, { key: 'sample_warning', header: 'Warning', cell: (value) => <CaveatChips value={value} /> }]} renderDetail={(row) => <ReportGroupDetail row={row} rawEnvelope={query.data?.raw_envelope} />} />
          <DataTable rows={examples} emptyMessage="No contributing trade/decision examples were returned by the local risk report." columns={[{ key: 'kind', header: 'Kind' }, { key: 'id', header: 'ID', cell: (value) => <CopyId value={value} /> }, { key: 'summary', header: 'Summary' }]} renderDetail={(row) => {
            const decisionId = realRecordId(row.id)
            return <ReportGroupDetail row={decisionId ? { ...row, record_ids: { decisions: [decisionId] } } : row} rawEnvelope={query.data?.raw_envelope} />
          }} />
          <details className="rounded border border-border p-3"><summary className="cursor-pointer text-sm font-medium">Missing-risk budget sample IDs ({missingRiskSample.length}) and raw report envelope</summary><div className="mt-2"><JsonBlock value={{ decisions_missing_risk_sample: missingRiskSample, record_ids: query.data?.evidence.record_ids, raw_envelope: query.data?.raw_envelope }} /></div></details>
        </div>
      )}
    </>
  )
}

function CalibrationPage({ query, filter, setFilter }: { query: ReturnType<typeof useReport>; filter: ConsoleFilter; setFilter: (filter: ConsoleFilter) => void }) {
  const metrics = query.data?.summary_metrics ?? {}
  const bins = Array.isArray(metrics.reliability_bins) ? metrics.reliability_bins as Array<Record<string, unknown>> : []
  const scored = numberValue(metrics.sample_size) ?? query.data?.groups?.[0]?.sample_size ?? 0
  const lateExcluded = numberValue(metrics.late_recorded_excluded) ?? 0
  const examples = query.data?.evidence.examples ?? []
  const integrity = rawData(query.data).integrity_diagnostics
  const integrityDiagnostics = integrity && typeof integrity === 'object' ? Object.entries(integrity as Record<string, unknown>) : []
  const scoredIds = query.data?.evidence.record_ids.forecasts ?? []
  return (
    <>
      <PageHeader eyebrow="Calibration" title="Forecast reliability and scoring integrity" />
      <PageExplainer answers="Whether locally scored probability forecasts were calibrated against recorded outcomes." data="report.calibration summary metrics, reliability bins, scored forecast examples, record IDs, and calibration-integrity diagnostics when included." read="Brier/log score are loss metrics where lower is better; ECE is average calibration gap; sharpness is confidence dispersion; reliability bins compare forecast probability to observed frequency." mislead="Low-N bins are noisy, unscored or late-recorded forecasts are caveats, and this page is diagnostic only — not trading advice or a new scoring formula." />
      <FilterBar filter={filter} onChange={setFilter} />
      {query.isLoading ? <LoadingBlock /> : query.isError ? <ErrorBlock error={query.error} /> : (
        <div className="space-y-4">
          <section className="grid gap-4 md:grid-cols-2 xl:grid-cols-4">
            <MetricCard label="Scored forecasts" value={String(scored)} icon={Activity} />
            <MetricCard label="Brier score" value={String(metrics.brier ?? 'n/a')} icon={BarChart3} />
            <MetricCard label="ECE" value={String(metrics.ece ?? 'n/a')} icon={BarChart3} />
            <MetricCard label="Late excluded" value={String(lateExcluded)} icon={ShieldCheck} />
          </section>
          <section className="rounded border border-border bg-card p-4">
            <h3 className="mb-2 font-semibold">Scoring caveats</h3>
            <CaveatChips value={[query.data?.summary_sample_warning, ...(query.data?.summary_caveats ?? [])].filter(Boolean)} />
            <p className="mt-2 text-sm text-muted-foreground">Only forecasts with supported local score/outcome records are included. Empty bins are intentionally omitted from charts and shown as zero-count rows below.</p>
          </section>
          <DataTable
            rows={bins}
            emptyMessage="No reliability bins were returned by the local calibration report."
            columns={[
              { key: 'bin_index', header: 'Bin' },
              { key: 'range', header: 'Probability range', accessor: (row) => `${row.lower ?? '?'}–${row.upper ?? '?'}` },
              { key: 'count', header: 'N' },
              { key: 'mean_probability', header: 'Mean p' },
              { key: 'observed_frequency', header: 'Observed' },
              { key: 'gap', header: 'Gap' }
            ]}
            renderDetail={(row) => <JsonBlock value={row} />}
          />
          <ChartPanel title="Observed frequency by non-empty bin" rows={bins.filter((row) => Number(row.count ?? 0) > 0).map((row) => ({ name: `${row.lower}–${row.upper}`, value: Number(row.observed_frequency ?? 0) }))} />
          <DataTable
            rows={examples}
            emptyMessage="No example forecasts were returned by the local calibration report."
            columns={[{ key: 'kind', header: 'Kind' }, { key: 'id', header: 'Forecast', cell: (value) => <CopyId value={value} /> }, { key: 'summary', header: 'Score summary' }]}
            renderDetail={(row) => {
              const forecastId = realRecordId(row.id)
              return <ReportGroupDetail row={forecastId ? { ...row, record_ids: { forecasts: [forecastId] } } : row} rawEnvelope={query.data?.raw_envelope} />
            }}
          />
          {integrityDiagnostics.length ? <DataTable rows={integrityDiagnostics.map(([key, value]) => ({ diagnostic: key, ...(typeof value === 'object' && value ? value as Record<string, unknown> : { value }) }))} columns={[{ key: 'diagnostic', header: 'Integrity diagnostic' }, { key: 'count', header: 'Count' }, { key: 'sample_warning', header: 'Warning', cell: (value) => <CaveatChips value={value} /> }]} renderDetail={(row) => <JsonBlock value={row} />} /> : null}
          <details className="rounded border border-border p-3"><summary className="cursor-pointer text-sm font-medium">Scored forecast record IDs ({scoredIds.length}) and raw report envelope</summary><div className="mt-2"><JsonBlock value={{ record_ids: query.data?.evidence.record_ids, raw_envelope: query.data?.raw_envelope }} /></div></details>
        </div>
      )}
    </>
  )
}

function EvidencePage({ query }: { query: ReturnType<typeof useReport> }) {
  const data = rawData(query.data)
  const summary = data.summary && typeof data.summary === 'object' ? data.summary as Record<string, unknown> : {}
  const diagnostics = data.diagnostics && typeof data.diagnostics === 'object' ? Object.values(data.diagnostics as Record<string, unknown>) as Array<Record<string, unknown>> : []
  return (
    <>
      <PageHeader eyebrow="Evidence" title="Source coverage and provenance diagnostics" />
      <PageExplainer answers="Which local source/provenance hygiene diagnostics the backend source-quality report supports." data="report.source_quality summary and diagnostics: missing sources on entries, stale sources, contradictory sources, duplicates, sensitive-source flags, sample IDs, and raw local samples where present." read="Counts are coverage/hygiene diagnostics; expand rows to inspect sample decisions, sources, theses, and contextual raw report payloads." mislead="This does not validate external truth, fetch sources, rank signals, or provide trading advice; unsupported diagnostics are not fabricated." />
      {query.isLoading ? <LoadingBlock /> : query.isError ? <ErrorBlock error={query.error} /> : (
        <div className="space-y-4">
          <section className="rounded border border-border bg-card p-4">
            <h3 className="mb-2 font-semibold">Journal-level diagnostics</h3>
            <p className="text-sm text-muted-foreground">Source-quality diagnostics are local journal-level provenance health checks. They are intentionally global and are not scoped by Console strategy, instrument, or decision filters.</p>
          </section>
          <section className="grid gap-4 md:grid-cols-2 xl:grid-cols-4">
            <MetricCard label="Sources" value={String(summary.total_sources ?? 'n/a')} icon={Database} />
            <MetricCard label="Attachments" value={String(summary.total_source_attachments ?? 'n/a')} icon={Boxes} />
            <MetricCard label="Stale threshold days" value={String(summary.stale_threshold_days ?? 'n/a')} icon={Activity} />
            <MetricCard label="Diagnostics" value={String(diagnostics.length)} icon={ShieldCheck} />
          </section>
          <section className="rounded border border-border bg-card p-4">
            <h3 className="mb-2 font-semibold">Coverage limits</h3>
            <p className="text-sm text-muted-foreground">Diagnostics appear only when the local report returns them. Missing or zero-count rows mean no supported local evidence was found for that diagnostic, not that an external source is true or complete.</p>
          </section>
          <DataTable
            rows={diagnostics}
            emptyMessage="The local source-quality report returned no diagnostics."
            columns={[
              { key: 'diagnostic', header: 'Diagnostic', cell: (value) => <ChipList value={value} /> },
              { key: 'count', header: 'Count' },
              { key: 'sample_ids', header: 'Sample IDs' },
              { key: 'truncated', header: 'Truncated' }
            ]}
            renderDetail={(row) => <ReportGroupDetail row={{ ...row, record_ids: row.sample_ids as Record<string, string[]> ?? {} }} rawEnvelope={query.data?.raw_envelope} />}
          />
          <details className="rounded border border-border p-3"><summary className="cursor-pointer text-sm font-medium">Raw source-quality report envelope</summary><div className="mt-2"><JsonBlock value={query.data?.raw_envelope} /></div></details>
        </div>
      )}
    </>
  )
}

function CatalogPage() {
  const query = useQuery({
    queryKey: ['catalog'],
    queryFn: () => fetchJson<CatalogPayload>('/api/console/catalog')
  })
  return (
    <>
      <PageHeader eyebrow="Reports" title="Report catalog" />
      <PageExplainer answers="Which safe read-only reports can be inspected from this Console." data="/api/console/catalog safe report tool list." read="Open a report page to see backend metrics, groups, evidence, and caveats." mislead="The catalog lists available local reports only; it is not a recommendation menu or signal scanner." />
      {query.isLoading ? <LoadingBlock /> : query.isError ? <ErrorBlock error={query.error} /> : (
        <DataTable rows={(query.data?.report_tools ?? []).map((tool) => ({ tool }))} columns={[{ key: 'tool', header: 'Tool' }]} />
      )}
    </>
  )
}

function payloadPreview(value: unknown) {
  if (value == null || value === '') return 'No payload stored'
  const text = typeof value === 'string' ? value : JSON.stringify(value)
  return text.length > 240 ? `${text.slice(0, 240)}…` : text
}

function EventAuditDetail({ event }: { event: EventRow }) {
  const detail = useQuery({
    queryKey: ['event-detail', event.id],
    queryFn: () => fetchJson<RecordEvent>(`/api/console/events/${event.id}`)
  })
  const related = useQuery({
    queryKey: ['event-related', event.id],
    queryFn: () => fetchJson<EventRelated>(`/api/console/events/${event.id}/related`)
  })
  const row = detail.data ?? event
  return (
    <div className="space-y-3">
      {detail.isError ? <ErrorBlock error={detail.error} /> : null}
      <div className="grid gap-2 md:grid-cols-2 xl:grid-cols-4">
        {[
          ['Subject ID', row.subject_id],
          ['Request ID', row.request_id],
          ['Idempotency key', row.idempotency_key],
          ['Actor', row.actor_id],
          ['Agent', row.agent_id],
          ['Model', row.model_id],
          ['Environment', row.environment],
          ['Run', row.run_id],
          ['Timestamp', row.created_at]
        ].map(([label, value]) => (
          <div key={String(label)} className="rounded border border-border p-2">
            <p className="text-xs uppercase tracking-wide text-muted-foreground">{String(label)}</p>
            <p className="break-all font-mono text-xs">{String(value ?? 'n/a')}</p>
          </div>
        ))}
      </div>
      <div>
        <p className="mb-1 text-xs font-semibold uppercase tracking-wide text-muted-foreground">Payload preview</p>
        <pre className="overflow-auto rounded border border-border bg-card p-3 text-xs">{payloadPreview(row.payload_json)}</pre>
      </div>
      <details className="rounded border border-border p-3">
        <summary className="cursor-pointer text-sm font-medium">Raw payload access</summary>
        <div className="mt-2 space-y-2">
          <a className="text-sm underline" href={`/api/console/raw/${event.id}`} target="_blank" rel="noreferrer">Open raw payload endpoint</a>
          <JsonBlock value={row.payload_json ?? row} />
        </div>
      </details>
      <div>
        <p className="mb-1 text-xs font-semibold uppercase tracking-wide text-muted-foreground">Related local records</p>
        {related.isLoading ? <p className="text-sm text-muted-foreground">Loading local relationships…</p> : related.isError ? <ErrorBlock error={related.error} /> : <JsonBlock value={related.data ?? {}} />}
      </div>
    </div>
  )
}

function JournalFilterPanel({ filter, onChange }: { filter: JournalFilter; onChange: (filter: JournalFilter) => void }) {
  const set = (key: keyof JournalFilter, value: string) => onChange({ ...filter, [key]: value.trim() })
  return (
    <section className="mb-4 rounded border border-border bg-card p-4">
      <div className="mb-3 flex flex-wrap items-center justify-between gap-2">
        <div>
          <h3 className="text-sm font-semibold">Timeline grouping filters</h3>
          <p className="text-xs text-muted-foreground">Exact local fields only: request/session, subject, actor, and event type.</p>
        </div>
        <button type="button" className="rounded border border-border px-3 py-1 text-sm" onClick={() => onChange({ request_id: '', actor_id: '', subject_kind: '', subject_id: '', event_type: '' })}>Clear filters</button>
      </div>
      <div className="grid gap-3 md:grid-cols-5">
        {(Object.keys(filter) as Array<keyof JournalFilter>).map((key) => (
          <label key={key} className="text-sm">{key.replaceAll('_', ' ')}
            <input className="mt-1 w-full rounded border border-border bg-background px-2 py-2" value={filter[key]} onChange={(event) => set(key, event.target.value)} />
          </label>
        ))}
      </div>
    </section>
  )
}

function EventsPage({ endpoint, title }: { endpoint: string; title: string }) {
  const [cursor, setCursor] = React.useState<string | null>(null)
  const [history, setHistory] = React.useState<string[]>([])
  const [replayIndex, setReplayIndex] = React.useState(0)
  const [filter, setFilter] = React.useState<JournalFilter>({ request_id: '', actor_id: '', subject_kind: '', subject_id: '', event_type: '' })
  const limit = 100
  const filters = React.useMemo(() => Object.fromEntries(Object.entries(filter).filter(([, value]) => value)), [filter])
  const query = useQuery({
    queryKey: ['journal-timeline', cursor, filters],
    queryFn: () => fetchJson<Page<EventRow>>(pageQuery(endpoint, { limit, cursor, ...filters }))
  })
  const rows = query.data?.rows ?? []
  const groups = React.useMemo(() => {
    const grouped = new Map<string, EventRow[]>()
    for (const row of rows) {
      const subjectKey = row.subject_id || row.subject_kind ? `${row.subject_kind ?? 'subject'}:${row.subject_id ?? 'none'}` : ''
      const key = String(row.request_id || row.run_id || subjectKey || row.actor_id || 'ungrouped')
      grouped.set(key, [...(grouped.get(key) ?? []), row])
    }
    return Array.from(grouped.entries())
  }, [rows])
  const replayEvent = rows[replayIndex] ?? null
  return (
    <>
      <PageHeader eyebrow="Audit" title={title} />
      <PageExplainer answers="Which append-only journal events match this local audit/replay view." data={`${endpoint} with exact local filters plus per-event detail, related local records, and raw payload endpoints.`} read="Groups prefer request/session IDs, then available subject fields, then actor, then ungrouped. Replay steps through stored journal events only." mislead="This is not market replay, broker data, advice, or writeback annotation; only locally stored event evidence is shown." />
      <JournalFilterPanel filter={filter} onChange={(next) => { setFilter(next); setCursor(null); setHistory([]); setReplayIndex(0) }} />
      {query.isLoading ? <LoadingBlock /> : query.isError ? <ErrorBlock error={query.error} /> : (
        <div className="space-y-4">
          <section className="rounded border border-border bg-card p-4">
            <div className="mb-3 flex flex-wrap items-center justify-between gap-2">
              <div>
                <h3 className="font-semibold">Local replay</h3>
                <p className="text-sm text-muted-foreground">Step {rows.length === 0 ? 0 : replayIndex + 1} of {rows.length}; journal events only.</p>
              </div>
              <div className="flex gap-2">
                <button type="button" className="rounded border border-border px-3 py-1 text-sm disabled:opacity-50" disabled={replayIndex <= 0} onClick={() => setReplayIndex((index) => Math.max(0, index - 1))}>Previous event</button>
                <button type="button" className="rounded border border-border px-3 py-1 text-sm disabled:opacity-50" disabled={replayIndex >= rows.length - 1} onClick={() => setReplayIndex((index) => Math.min(rows.length - 1, index + 1))}>Next event</button>
              </div>
            </div>
            {replayEvent ? <EventAuditDetail event={replayEvent} /> : <p className="text-sm text-muted-foreground">No events to replay for this filter.</p>}
          </section>
          <div className="space-y-3">
            {groups.map(([group, groupRows]) => (
              <details key={group} open className="rounded border border-border bg-card p-3">
                <summary className="cursor-pointer font-medium">Group {group} · {groupRows.length} event(s)</summary>
                <div className="mt-3">
                  <DataTable rows={groupRows} emptyMessage="No audit rows match this view." columns={[
                    { key: 'id', header: 'ID', cell: (value) => <CopyId value={value} /> },
                    { key: 'event_type', header: 'Type', cell: (value) => <ChipList value={value} /> },
                    { key: 'subject_kind', header: 'Subject' },
                    { key: 'subject_id', header: 'Subject ID', cell: (value) => <CopyId value={value} /> },
                    { key: 'request_id', header: 'Request', cell: (value) => <CopyId value={value} /> },
                    { key: 'actor_id', header: 'Actor' },
                    { key: 'created_at', header: 'Created' }
                  ]} renderDetail={(row) => <EventAuditDetail event={row} />} />
                </div>
              </details>
            ))}
          </div>
          <div className="flex items-center justify-between gap-3 text-sm text-muted-foreground">
            <span>Showing up to {query.data?.limit ?? limit} rows{query.data?.next_cursor ? '; more rows available' : ''}.</span>
            <div className="flex gap-2">
              <button type="button" className="rounded border border-border px-3 py-1 disabled:opacity-50" disabled={history.length === 0} onClick={() => { const previous = history.at(-1) ?? null; setHistory((items) => items.slice(0, -1)); setCursor(previous === '' ? null : previous); setReplayIndex(0) }}>Previous page</button>
              <button type="button" className="rounded border border-border px-3 py-1 disabled:opacity-50" disabled={!query.data?.next_cursor} onClick={() => { setHistory((items) => [...items, cursor ?? '']); setCursor(query.data?.next_cursor ?? null); setReplayIndex(0) }}>Next page</button>
            </div>
          </div>
        </div>
      )}
    </>
  )
}

function StrategiesPage() {
  return (
    <>
      <PageHeader eyebrow="Strategies" title="Strategy performance and process review" />
      <PageExplainer answers="What named strategy records exist and what supported local reports associate with them." data="/api/console/strategies plus read-only report.strategy_performance and report.compare(calibration by strategy_id)." read="Compare supported counts, P&L/performance, calibration coverage, caveats, and drilldown evidence as associations for review." mislead="Strategy rows, performance differences, or calibration gaps do not prove edge, causality, or advice." />
      <StrategyReviewSection />
      <section className="mt-5">
        <h3 className="mb-3 text-lg font-semibold">Strategy inventory</h3>
        <PageTable<Record<string, unknown>>
          endpoint="/api/console/strategies"
          queryKey="strategies"
          subjectKind="strategy"
          emptyMessage="No strategy records exist in this journal."
          columns={[
            { key: 'id', header: 'ID', cell: (value) => <CopyId value={value} /> },
            { key: 'name', header: 'Name' },
            { key: 'slug', header: 'Slug' },
            { key: 'status', header: 'Status', cell: (value) => <ChipList value={value} /> },
            { key: 'created_at', header: 'Created' }
          ]}
        />
      </section>
    </>
  )
}

function PlaybooksPage() {
  return (
    <>
      <PageHeader eyebrow="Playbooks" title="Playbook rule-adherence review" />
      <PageExplainer answers="What playbook records exist and which local rule-adherence evidence is available." data="/api/console/playbooks plus read-only report.playbook_adherence groups, rule-state counts, caveats, examples, and contributing decision/rule IDs." read="Use followed, overridden/violated, considered/unknown, and not-applicable states only where local adherence rows exist." mislead="Adherence state is process evidence, not a recommendation, rule edit, optimization, or proof that a playbook caused outcomes." />
      <PlaybookReviewSection />
      <section className="mt-5">
        <h3 className="mb-3 text-lg font-semibold">Playbook inventory</h3>
        <PageTable<Record<string, unknown>>
          endpoint="/api/console/playbooks"
          queryKey="playbooks"
          subjectKind="playbook"
          emptyMessage="No playbook records exist in this journal."
          columns={[
            { key: 'id', header: 'ID', cell: (value) => <CopyId value={value} /> },
            { key: 'name', header: 'Name' },
            { key: 'description', header: 'Description' },
            { key: 'status', header: 'Status', cell: (value) => <ChipList value={value} /> },
            { key: 'created_at', header: 'Created' }
          ]}
        />
      </section>
    </>
  )
}

function DecisionsPage() {
  const [filter, setFilter] = useConsoleFilter()
  return (
    <>
      <PageHeader eyebrow="Decisions" title="Recorded decisions" />
      <PageExplainer answers="Which trading and non-trading decisions are recorded under the current filter." data="/api/console/decisions journal decision rows." read="Decision type distinguishes entries, exits, watches, skips, and other actions where present." mislead="Not every decision is a trade; missing price or quantity can be valid for non-trading actions." />
      <FilterBar filter={filter} onChange={setFilter} supportsStrategy={false} />
      <PageTable<Record<string, unknown>>
        endpoint="/api/console/decisions"
        queryKey="decisions"
        filters={tableFilterParams(filter, ['instrument_id', 'decision_type'])}
        subjectKind="decision"
        emptyMessage="No matching decisions for this view."
        columns={[
          { key: 'id', header: 'ID', cell: (value) => <CopyId value={value} /> },
          { key: 'type', header: 'Type', cell: (value) => <ChipList value={value} /> },
          { key: 'instrument_id', header: 'Instrument' },
          { key: 'thesis_id', header: 'Thesis' },
          { key: 'side', header: 'Side' },
          { key: 'quantity', header: 'Qty' },
          { key: 'price', header: 'Price' },
          { key: 'created_at', header: 'Created' }
        ]}
      />
    </>
  )
}

function routeComponent(definition: ConsoleRouteDefinition) {
  switch (definition.component) {
    case 'overview':
      return OverviewPage
    case 'trades':
      return TradesPage
    case 'catalog':
      return CatalogPage
    case 'review':
      return ReviewPage
    case 'report':
      return () => <ReportPage tool={definition.tool!} title={definition.title!} args={definition.args} />
    case 'process':
      return ProcessAnalyticsPage
    case 'strategies':
      return StrategiesPage
    case 'playbooks':
      return PlaybooksPage
    case 'events':
      return () => <EventsPage endpoint={definition.endpoint!} title={definition.title!} />
    case 'decisions':
      return DecisionsPage
  }
}

const rootRoute = createRootRoute({ component: Shell })
const routeTree = rootRoute.addChildren(
  consoleRouteCatalog.map((definition) => createRoute({
    getParentRoute: () => rootRoute,
    path: definition.path,
    component: routeComponent(definition)
  }))
)

const router = createRouter({ routeTree })

declare module '@tanstack/react-router' {
  interface Register {
    router: typeof router
  }
}

createRoot(document.getElementById('root')!).render(
  <React.StrictMode>
    <QueryClientProvider client={queryClient}>
      <RouterProvider router={router} />
    </QueryClientProvider>
  </React.StrictMode>
)
