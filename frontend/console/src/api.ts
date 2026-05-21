export type Page<T> = {
  rows: T[]
  next_cursor: string | null
  limit: number
}

export type StatusPayload = {
  db_path: string
  generated_at?: string
  last_event_at?: string | null
  lazy_write_handlers_blocked?: string[]
  logs_available?: boolean
  read_only: boolean
  reason?: string
  row_counts?: Record<string, number>
  schema_version?: number | null
}

export type CatalogPayload = {
  routes: string[]
  report_tools: string[]
  lazy_write_handlers_blocked: string[]
}

export type ReportPayload = {
  tool: string
  summary_metrics: Record<string, unknown>
  summary_caveats: unknown[]
  summary_sample_warning?: string | null
  groups: Array<{
    key: string
    label: string
    metrics: Record<string, unknown>
    sample_size: number
    sample_warning?: string | null
    record_ids: Record<string, string[]>
  }>
  evidence: {
    tool: string
    cli_invocation: string
    request_id: string
    record_ids: Record<string, string[]>
    examples?: Array<Record<string, unknown>>
  }
  as_of?: string | null
  raw_envelope: unknown
}

export type TradeRow = Record<string, unknown> & {
  decision_id: string
  decision_type: string
  decision_at: string
  instrument_symbol?: string | null
  side?: string | null
  quantity?: number | null
  price?: number | null
  caveats?: string[]
}

export type PositionCaveatEntry = Record<string, unknown> & {
  code?: string
  label?: string
  summary?: string
  severity?: string
}

export type PositionRow = Record<string, unknown> & {
  position_id: string
  instrument_id: string
  instrument_symbol?: string | null
  instrument_title?: string | null
  kind: string
  side?: string | null
  status: string
  outcome: string
  opened_at: string
  closed_at?: string | null
  net_quantity: number
  avg_entry_price?: number | null
  add_count: number
  reduce_count: number
  event_count: number
  opening_decision_id?: string | null
  opening_strategy_id?: string | null
  opening_strategy_slug?: string | null
  opening_strategy_name?: string | null
  caveats?: string[]
  caveat_entries?: PositionCaveatEntry[]
}

export type PositionEvent = Record<string, unknown> & {
  id: string
  event_type: string
  quantity_delta?: number | null
  price?: number | null
  fees?: number | null
  slippage?: number | null
  created_at?: string | null
  decision_id?: string | null
}

export type PositionThesisSummary = Record<string, unknown> & {
  id: string
  side?: string | null
  created_at?: string | null
  body_snippet?: string | null
}

export type PositionSourceSummary = Record<string, unknown> & {
  id: string
  kind?: string | null
  title?: string | null
  ref?: string | null
  uri?: string | null
  stance?: string | null
  edge_type?: string | null
  excerpt?: string | null
}

export type PositionTagSummary = Record<string, unknown> & {
  tag: string
  decision_id?: string | null
}

export type PositionStrategySummary = Record<string, unknown> & {
  id: string
  slug?: string | null
  name?: string | null
}

export type PositionRiskRollup = Record<string, unknown> & {
  initial_risk_amount?: number | null
  declared_risk_amount?: number | null
  declared_risk_unit?: string | null
  realized_r_multiple?: number | null
  unrealized_r_multiple?: number | null
  total_fees?: number | null
  total_slippage?: number | null
}

export type PositionDetail = PositionRow & {
  venue_id?: string | null
  venue_kind?: string | null
  updated_at?: string | null
  realized_pnl?: number | null
  unrealized_pnl?: number | null
  initial_risk_amount?: number | null
  realized_r_multiple?: number | null
  unrealized_r_multiple?: number | null
  opening_playbook_version_id?: string | null
  opening_thesis_id?: string | null
  thesis?: PositionThesisSummary | null
  strategy?: PositionStrategySummary | null
  sources?: PositionSourceSummary[]
  tags?: PositionTagSummary[]
  decision_ids?: string[]
  risk_rollup?: PositionRiskRollup | null
  events?: PositionEvent[]
}

export type EventRow = Record<string, unknown> & {
  id: number
  event_type: string
  subject_kind?: string | null
  actor_id?: string | null
  created_at?: string | null
}

export async function fetchJson<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(path, {
    headers: { Accept: 'application/json', ...(init?.headers ?? {}) },
    ...init
  })
  if (!response.ok) {
    let message = `${response.status} ${response.statusText}`
    try {
      const body = await response.json()
      message = body?.detail?.message ?? body?.detail ?? message
    } catch {
      // Keep the HTTP status message when the body is not JSON.
    }
    throw new Error(String(message))
  }
  return response.json() as Promise<T>
}

export type PageQueryValue = string | number | readonly (string | number | null | undefined)[] | null | undefined

export function pageQuery(path: string, params: Record<string, PageQueryValue>) {
  const url = new URL(path, window.location.origin)
  for (const [key, value] of Object.entries(params)) {
    const values = Array.isArray(value) ? value : [value]
    for (const item of values) {
      if (item !== undefined && item !== null && item !== '') {
        url.searchParams.append(key, String(item))
      }
    }
  }
  return `${url.pathname}${url.search}`
}

