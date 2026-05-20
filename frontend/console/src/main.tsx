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
                className="flex items-center gap-3 rounded px-3 py-2 text-sm text-muted-foreground hover:bg-accent hover:text-foreground [&.active]:bg-accent [&.active]:text-foreground"
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
                  className="inline-flex shrink-0 items-center gap-2 rounded border border-border px-3 py-1.5 text-sm text-muted-foreground [&.active]:bg-accent [&.active]:text-foreground"
                >
                  <item.icon className="size-4" aria-hidden />
                  {item.label}
                </Link>
              ))}
            </nav>
          </header>
          <main className="mx-auto max-w-7xl px-4 py-6 md:px-6">
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
  return <div className="rounded border border-border bg-card p-5 text-sm text-muted-foreground">{label}</div>
}

function ErrorBlock({ error }: { error: unknown }) {
  return (
    <div className="rounded border border-danger/30 bg-danger/10 p-5 text-sm text-danger">
      {error instanceof Error ? error.message : 'Unable to load data'}
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
        <ReportSummary title="Risk rollup" query={risk} metricKeys={['mean_r', 'expectancy_r', 'win_rate']} href="/reports/risk" />
        <ReportSummary title="Strategy performance" query={strategy} metricKeys={['total_trades', 'realized_pnl', 'win_rate']} href="/reports/strategy" />
        <ReportSummary title="Calibration" query={calibration} metricKeys={['sample_size', 'brier', 'ece']} href="/calibration" />
      </section>
      <section className="mt-5 grid gap-4 xl:grid-cols-2">
        <OverviewReportGroups title="P&L contributors" query={pnl} href="/reports/pnl" metricKeys={['realized_pnl', 'unrealized_pnl', 'mark_to_market_pnl']} />
        <OverviewReportGroups title="Risk contributors" query={risk} href="/reports/risk" metricKeys={['mean_r', 'expectancy_r', 'win_rate']} />
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
    case 'report':
      return () => <ReportPage tool={definition.tool!} title={definition.title!} args={definition.args} />
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
