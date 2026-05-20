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
  AlertTriangle,
  BarChart3,
  BookOpen,
  Boxes,
  Database,
  FileJson,
  Gauge,
  ListFilter,
  NotebookText,
  RefreshCw,
  ShieldCheck,
  TableProperties
} from 'lucide-react'
import React from 'react'
import { createRoot } from 'react-dom/client'

import { ChartPanel } from './ui/ChartPanel'
import { DataTable } from './ui/DataTable'
import { MetricCard } from './ui/MetricCard'
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

const queryClient = new QueryClient({
  defaultOptions: {
    queries: {
      staleTime: 15_000,
      refetchOnWindowFocus: false,
      retry: 1
    }
  }
})

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
  const nav = [
    { to: '/', label: 'Overview', icon: Gauge },
    { to: '/trades', label: 'Trades', icon: TableProperties },
    { to: '/reports', label: 'Reports', icon: BarChart3 },
    { to: '/calibration', label: 'Calibration', icon: Activity },
    { to: '/evidence', label: 'Evidence', icon: ShieldCheck },
    { to: '/strategies', label: 'Strategies', icon: Boxes },
    { to: '/playbooks', label: 'Playbooks', icon: BookOpen },
    { to: '/journal', label: 'Journal', icon: NotebookText },
    { to: '/decisions', label: 'Decisions', icon: ListFilter },
    { to: '/logs', label: 'Logs', icon: AlertTriangle },
    { to: '/raw', label: 'Raw JSON', icon: FileJson }
  ]

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

function PageTable<T extends Record<string, unknown>>({
  endpoint,
  queryKey,
  columns,
  emptyMessage
}: {
  endpoint: string
  queryKey: string
  columns: Parameters<typeof DataTable<T>>[0]['columns']
  emptyMessage: string
}) {
  const [cursor, setCursor] = React.useState<string | null>(null)
  const [history, setHistory] = React.useState<string[]>([])
  const limit = 100
  const query = useQuery({
    queryKey: [queryKey, cursor],
    queryFn: () => fetchJson<Page<T>>(pageQuery(endpoint, { limit, cursor }))
  })
  const nextCursor = query.data?.next_cursor ?? null
  return query.isLoading ? (
    <LoadingBlock />
  ) : query.isError ? (
    <ErrorBlock error={query.error} />
  ) : (
    <div className="space-y-3">
      <DataTable rows={query.data?.rows ?? []} columns={columns} emptyMessage={emptyMessage} />
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
  const status = useStatus()
  const pnl = useReport('report.pnl')
  const risk = useReport('report.risk')

  if (status.isLoading) return <LoadingBlock />
  if (status.isError) return <ErrorBlock error={status.error} />

  const counts = status.data?.row_counts ?? {}
  return (
    <>
      <PageHeader eyebrow="Dashboard" title="Journal intelligence at a glance" />
      <section className="grid gap-4 md:grid-cols-2 xl:grid-cols-4">
        <MetricCard label="Events" value={counts.events ?? 0} icon={Database} />
        <MetricCard label="Decisions" value={counts.decisions ?? 0} icon={ListFilter} />
        <MetricCard label="Strategies" value={counts.strategies ?? 0} icon={Boxes} />
        <MetricCard label="Schema" value={status.data?.schema_version ?? 'n/a'} icon={ShieldCheck} />
      </section>
      <section className="mt-5 grid gap-4 xl:grid-cols-2">
        <ReportSummary title="P&L rollup" query={pnl} metricKeys={['realized_pnl', 'unrealized_pnl', 'mtm_pnl']} />
        <ReportSummary title="Risk rollup" query={risk} metricKeys={['mean_r', 'expectancy_r', 'win_rate']} />
      </section>
    </>
  )
}

function ReportSummary({
  title,
  query,
  metricKeys
}: {
  title: string
  query: ReturnType<typeof useReport>
  metricKeys: string[]
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
      </div>
      <div className="grid gap-3 sm:grid-cols-3">
        {values.map((metric) => (
          <div key={metric.name} className="rounded border border-border p-3">
            <p className="text-xs uppercase tracking-wide text-muted-foreground">{metric.name}</p>
            <p className="mt-1 text-2xl font-semibold">{metric.value}</p>
          </div>
        ))}
      </div>
    </article>
  )
}

function TradesPage() {
  return (
    <>
      <PageHeader eyebrow="Trades" title="Trade decisions and caveats" />
      <PageTable<TradeRow>
        endpoint="/api/console/trades"
        queryKey="trades"
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
          { key: 'caveats', header: 'Caveats', cell: (value) => <ChipList value={value} /> }
        ]}
      />
    </>
  )
}

function ReportPage({
  tool,
  title,
  args = { filter: {} }
}: {
  tool: string
  title: string
  args?: Record<string, unknown>
}) {
  const query = useReport(tool, args)
  const metrics = query.data?.summary_metrics ?? {}
  const chartRows = Object.entries(metrics)
    .filter(([, value]) => typeof value === 'number')
    .slice(0, 8)
    .map(([name, value]) => ({ name: name.replaceAll('_', ' '), value: Number(value) }))

  return (
    <>
      <PageHeader eyebrow="Report" title={title} />
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
              { key: 'sample_warning', header: 'Warning' },
              { key: 'metrics', header: 'Metrics' }
            ]}
          />
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
      {query.isLoading ? <LoadingBlock /> : query.isError ? <ErrorBlock error={query.error} /> : (
        <DataTable rows={(query.data?.report_tools ?? []).map((tool) => ({ tool }))} columns={[{ key: 'tool', header: 'Tool' }]} />
      )}
    </>
  )
}

function EventsPage({ endpoint, title }: { endpoint: string; title: string }) {
  return (
    <>
      <PageHeader eyebrow="Audit" title={title} />
      <PageTable<EventRow>
        endpoint={endpoint}
        queryKey={endpoint}
        emptyMessage="No audit rows match this view."
        columns={[
          { key: 'id', header: 'ID', cell: (value) => <CopyId value={value} /> },
          { key: 'event_type', header: 'Type', cell: (value) => <ChipList value={value} /> },
          { key: 'subject_kind', header: 'Subject' },
          { key: 'actor_id', header: 'Actor' },
          { key: 'created_at', header: 'Created' }
        ]}
      />
    </>
  )
}

function StrategiesPage() {
  return (
    <>
      <PageHeader eyebrow="Strategies" title="Strategy records" />
      <PageTable<Record<string, unknown>>
        endpoint="/api/console/strategies"
        queryKey="strategies"
        emptyMessage="No strategy records exist in this journal."
        columns={[
          { key: 'id', header: 'ID', cell: (value) => <CopyId value={value} /> },
          { key: 'name', header: 'Name' },
          { key: 'slug', header: 'Slug' },
          { key: 'status', header: 'Status', cell: (value) => <ChipList value={value} /> },
          { key: 'created_at', header: 'Created' }
        ]}
      />
    </>
  )
}

function PlaybooksPage() {
  return (
    <>
      <PageHeader eyebrow="Playbooks" title="Playbook records" />
      <PageTable<Record<string, unknown>>
        endpoint="/api/console/playbooks"
        queryKey="playbooks"
        emptyMessage="No playbook records exist in this journal."
        columns={[
          { key: 'id', header: 'ID', cell: (value) => <CopyId value={value} /> },
          { key: 'name', header: 'Name' },
          { key: 'description', header: 'Description' },
          { key: 'status', header: 'Status', cell: (value) => <ChipList value={value} /> },
          { key: 'created_at', header: 'Created' }
        ]}
      />
    </>
  )
}

function DecisionsPage() {
  return (
    <>
      <PageHeader eyebrow="Decisions" title="Recorded decisions" />
      <PageTable<Record<string, unknown>>
        endpoint="/api/console/decisions"
        queryKey="decisions"
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

function LogsPage() {
  const query = useQuery({
    queryKey: ['logs'],
    queryFn: () => fetchJson<Record<string, unknown>>('/api/console/logs?tail=200')
  })
  return (
    <>
      <PageHeader eyebrow="Logs" title="Operational log tail" />
      {query.isLoading ? <LoadingBlock /> : query.isError ? <ErrorBlock error={query.error} /> : (
        <pre className="overflow-auto rounded border border-border bg-card p-4 text-xs">
          {JSON.stringify(query.data, null, 2)}
        </pre>
      )}
    </>
  )
}

const rootRoute = createRootRoute({ component: Shell })
const indexRoute = createRoute({ getParentRoute: () => rootRoute, path: '/', component: OverviewPage })
const tradesRoute = createRoute({ getParentRoute: () => rootRoute, path: '/trades', component: TradesPage })
const reportsRoute = createRoute({ getParentRoute: () => rootRoute, path: '/reports', component: CatalogPage })
const pnlRoute = createRoute({ getParentRoute: () => rootRoute, path: '/reports/pnl', component: () => <ReportPage tool="report.pnl" title="P&L analytics" /> })
const riskRoute = createRoute({ getParentRoute: () => rootRoute, path: '/reports/risk', component: () => <ReportPage tool="report.risk" title="Risk analytics" /> })
const performanceRoute = createRoute({ getParentRoute: () => rootRoute, path: '/reports/performance', component: () => <ReportPage tool="report.decision_velocity" title="Performance timeline" /> })
const strategyRoute = createRoute({ getParentRoute: () => rootRoute, path: '/reports/strategy', component: () => <ReportPage tool="report.strategy_performance" title="Strategy performance" /> })
const decisionIntelRoute = createRoute({ getParentRoute: () => rootRoute, path: '/reports/decisions', component: () => <ReportPage tool="report.watchlist" title="Decision intelligence" /> })
const compareRoute = createRoute({
  getParentRoute: () => rootRoute,
  path: '/reports/compare',
  component: () => (
    <ReportPage
      tool="report.compare"
      title="Compare"
      args={{ base_report: 'calibration', group_by: 'strategy_id', filter: {} }}
    />
  )
})
const calibrationRoute = createRoute({ getParentRoute: () => rootRoute, path: '/calibration', component: () => <ReportPage tool="report.calibration" title="Calibration and integrity" /> })
const evidenceRoute = createRoute({ getParentRoute: () => rootRoute, path: '/evidence', component: () => <ReportPage tool="report.source_quality" title="Evidence and provenance" /> })
const strategiesRoute = createRoute({ getParentRoute: () => rootRoute, path: '/strategies', component: StrategiesPage })
const playbooksRoute = createRoute({ getParentRoute: () => rootRoute, path: '/playbooks', component: PlaybooksPage })
const journalRoute = createRoute({ getParentRoute: () => rootRoute, path: '/journal', component: () => <EventsPage endpoint="/api/console/events" title="Journal events" /> })
const decisionsRoute = createRoute({ getParentRoute: () => rootRoute, path: '/decisions', component: DecisionsPage })
const logsRoute = createRoute({ getParentRoute: () => rootRoute, path: '/logs', component: LogsPage })
const rawRoute = createRoute({ getParentRoute: () => rootRoute, path: '/raw', component: () => <EventsPage endpoint="/api/console/events" title="Raw events" /> })

const routeTree = rootRoute.addChildren([
  indexRoute,
  tradesRoute,
  reportsRoute,
  pnlRoute,
  riskRoute,
  performanceRoute,
  strategyRoute,
  decisionIntelRoute,
  compareRoute,
  calibrationRoute,
  evidenceRoute,
  strategiesRoute,
  playbooksRoute,
  journalRoute,
  decisionsRoute,
  logsRoute,
  rawRoute
])

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
