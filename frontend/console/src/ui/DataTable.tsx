import type { ReactNode } from 'react'
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
  searchable = true
}: {
  rows: T[]
  columns: Column<T>[]
  emptyMessage?: string
  searchable?: boolean
}) {
  const [globalFilter, setGlobalFilter] = useState('')
  const [sorting, setSorting] = useState<SortingState>([])
  const columnDefs = useMemo(
    () =>
      columns.map<ColumnDef<T>>((column) => ({
        id: column.key,
        header: column.header,
        accessorFn: (row) => (column.accessor ? column.accessor(row) : row[column.key]),
        cell: (ctx) => {
          const value = ctx.getValue()
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

  return (
    <div className="overflow-hidden rounded border border-border bg-card">
      {searchable ? (
        <div className="border-b border-border p-3">
          <label className="sr-only" htmlFor="table-search">
            Search table
          </label>
          <input
            id="table-search"
            className="w-full rounded border border-border bg-background px-3 py-2 text-sm md:max-w-sm"
            placeholder="Search rows"
            value={globalFilter}
            onChange={(event) => setGlobalFilter(event.target.value)}
          />
        </div>
      ) : null}
      <div className="max-h-[620px] overflow-auto">
        <table className="min-w-full border-collapse text-sm">
          <thead className="sticky top-0 bg-muted text-left text-xs uppercase tracking-wide text-muted-foreground">
            {table.getHeaderGroups().map((headerGroup) => (
              <tr key={headerGroup.id}>
                {headerGroup.headers.map((header) => (
                  <th key={header.id} className="border-b border-border px-3 py-2 font-medium">
                    <button
                      type="button"
                      className="inline-flex items-center gap-1 text-left uppercase tracking-wide"
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
            {table.getRowModel().rows.map((row) => (
              <tr key={row.id} className="border-b border-border last:border-0">
                {row.getVisibleCells().map((cell) => (
                  <td key={cell.id} className="max-w-72 truncate px-3 py-2">
                    {flexRender(cell.column.columnDef.cell, cell.getContext())}
                  </td>
                ))}
              </tr>
            ))}
            {table.getRowModel().rows.length === 0 ? (
              <tr>
                <td className="px-3 py-8 text-center text-muted-foreground" colSpan={columns.length}>
                  {emptyMessage}
                </td>
              </tr>
            ) : null}
          </tbody>
        </table>
      </div>
    </div>
  )
}
