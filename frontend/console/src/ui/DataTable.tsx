import type { ReactNode } from 'react'
import { Fragment } from 'react'
import { useMemo, useState } from 'react'
import {
  ColumnDef,
  SortingState,
  flexRender,
  getCoreRowModel,
  getFilteredRowModel,
  getSortedRowModel,
  useReactTable
} from '@tanstack/react-table'

import { CaveatChips } from './help'

export type Column<T extends Record<string, unknown> = Record<string, unknown>> = {
  key: string
  header: string
  accessor?: (row: T) => unknown
  cell?: (value: unknown, row: T) => ReactNode
}

function formatCell(value: unknown): string {
  if (Array.isArray(value)) return value.length > 0 ? value.join(', ') : 'n/a'
  if (value && typeof value === 'object') return JSON.stringify(value)
  return value == null || value === '' ? 'n/a' : String(value)
}

export function DataTable<T extends Record<string, unknown>>({
  rows,
  columns,
  emptyMessage = 'No rows match this view.',
  searchable = true,
  renderDetail
}: {
  rows: T[]
  columns: Column<T>[]
  emptyMessage?: string
  searchable?: boolean
  renderDetail?: (row: T) => ReactNode
}) {
  const [globalFilter, setGlobalFilter] = useState('')
  const [sorting, setSorting] = useState<SortingState>([])
  const [expandedRowId, setExpandedRowId] = useState<string | null>(null)
  const columnDefs = useMemo(
    () =>
      columns.map<ColumnDef<T>>((column) => ({
        id: column.key,
        header: column.header,
        accessorFn: (row) => (column.accessor ? column.accessor(row) : row[column.key]),
        cell: (ctx) => {
          const value = ctx.getValue()
          if (!column.cell && /caveat|warning/i.test(column.key)) return <CaveatChips value={value} />
          return column.cell ? column.cell(value, ctx.row.original) : formatCell(value)
        }
      })),
    [columns]
  )
  const table = useReactTable({
    data: rows,
    columns: columnDefs,
    state: { globalFilter, sorting },
    onGlobalFilterChange: setGlobalFilter,
    onSortingChange: setSorting,
    getCoreRowModel: getCoreRowModel(),
    getFilteredRowModel: getFilteredRowModel(),
    getSortedRowModel: getSortedRowModel()
  })

  const visibleRows = table.getRowModel().rows
  const tableLabel = columns.map((column) => column.header).join(', ')

  return (
    <div className="min-w-0 overflow-hidden rounded border border-border bg-card">
      {searchable ? (
        <div className="border-b border-border p-3">
          <label className="sr-only" htmlFor="table-search">
            Search table
          </label>
          <input
            id="table-search"
            className="w-full rounded border border-border bg-background px-3 py-2 text-sm shadow-sm md:max-w-sm"
            placeholder="Search rows"
            value={globalFilter}
            onChange={(event) => setGlobalFilter(event.target.value)}
          />
        </div>
      ) : null}
      <div className="max-h-[620px] min-w-0 overflow-auto" tabIndex={0} aria-label={`Scrollable table: ${tableLabel}`}>
        <table className="min-w-full border-collapse text-sm">
          <caption className="sr-only">
            {tableLabel}. {visibleRows.length === 0 ? emptyMessage : `${visibleRows.length} visible row${visibleRows.length === 1 ? '' : 's'}. Use column header buttons to sort.`}
          </caption>
          <thead className="sticky top-0 bg-muted text-left text-xs uppercase tracking-wide text-muted-foreground">
            {table.getHeaderGroups().map((headerGroup) => (
              <tr key={headerGroup.id}>
                {renderDetail ? <th className="border-b border-border px-3 py-2 font-medium">Detail</th> : null}
                {headerGroup.headers.map((header) => (
                  <th key={header.id} className="border-b border-border px-3 py-2 font-medium">
                    <button
                      type="button"
                      className="inline-flex items-center gap-1 rounded text-left uppercase tracking-wide"
                      onClick={header.column.getToggleSortingHandler()}
                    >
                      {flexRender(header.column.columnDef.header, header.getContext())}
                      {header.column.getIsSorted() === 'asc'
                        ? ' ↑'
                        : header.column.getIsSorted() === 'desc'
                          ? ' ↓'
                          : ''}
                    </button>
                  </th>
                ))}
              </tr>
            ))}
          </thead>
          <tbody>
            {visibleRows.map((row) => (
              <Fragment key={row.id}>
                <tr key={row.id} className="border-b border-border last:border-0">
                  {renderDetail ? (
                    <td className="px-3 py-2">
                      <button
                        type="button"
                        className="rounded border border-border px-2 py-1 text-xs shadow-sm"
                        aria-expanded={expandedRowId === row.id}
                        onClick={() => setExpandedRowId((current) => (current === row.id ? null : row.id))}
                      >
                        {expandedRowId === row.id ? 'Hide' : 'Detail'}
                      </button>
                    </td>
                  ) : null}
                  {row.getVisibleCells().map((cell) => (
                    <td key={cell.id} className="max-w-72 whitespace-nowrap px-3 py-2 align-top">
                      {flexRender(cell.column.columnDef.cell, cell.getContext())}
                    </td>
                  ))}
                </tr>
                {renderDetail && expandedRowId === row.id ? (
                  <tr key={`${row.id}-detail`} className="border-b border-border bg-background/70">
                    <td className="px-3 py-3" colSpan={columns.length + 1}>
                      {renderDetail(row.original)}
                    </td>
                  </tr>
                ) : null}
              </Fragment>
            ))}
            {visibleRows.length === 0 ? (
              <tr>
                <td className="px-3 py-8 text-center" colSpan={columns.length + (renderDetail ? 1 : 0)}>
                  <div className="mx-auto max-w-md rounded border border-dashed border-border bg-background/70 p-4">
                    <p className="font-medium text-foreground">No rows to display</p>
                    <p className="mt-1 text-sm text-muted-foreground">{emptyMessage}</p>
                  </div>
                </td>
              </tr>
            ) : null}
          </tbody>
        </table>
      </div>
    </div>
  )
}
