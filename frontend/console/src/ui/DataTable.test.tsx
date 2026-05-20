import { fireEvent, render, screen, within } from '@testing-library/react'
import { describe, expect, it } from 'vitest'

import { DataTable } from './DataTable'

describe('DataTable', () => {
  it('renders mapped columns with accessor fallback instead of false n/a', () => {
    render(
      <DataTable
        rows={[{ decision_id: 'd1', instrument_symbol: null, instrument_title: 'Acme Corp', caveats: ['missing_risk'] }]}
        columns={[
          { key: 'decision_id', header: 'Decision' },
          { key: 'instrument', header: 'Instrument', accessor: (row) => row.instrument_symbol ?? row.instrument_title },
          { key: 'caveats', header: 'Caveats' }
        ]}
      />
    )

    expect(screen.getByText('Acme Corp')).toBeInTheDocument()
    expect(screen.queryByText('n/a')).not.toBeInTheDocument()
  })

  it('supports bounded client search and sortable mapped columns', () => {
    render(
      <DataTable
        rows={[
          { id: 's2', name: 'Beta', status: 'archived' },
          { id: 's1', name: 'Alpha', status: 'active' }
        ]}
        columns={[
          { key: 'id', header: 'ID' },
          { key: 'name', header: 'Name' },
          { key: 'status', header: 'Status' }
        ]}
      />
    )

    fireEvent.change(screen.getByLabelText('Search table'), { target: { value: 'Alpha' } })
    expect(screen.getByText('Alpha')).toBeInTheDocument()
    expect(screen.queryByText('Beta')).not.toBeInTheDocument()

    fireEvent.change(screen.getByLabelText('Search table'), { target: { value: '' } })
    fireEvent.click(screen.getByRole('button', { name: /name/i }))
    const bodyRows = screen.getAllByRole('row').slice(1)
    expect(within(bodyRows[0]).getByText('Alpha')).toBeInTheDocument()
  })

  it('shows a caller-provided empty state', () => {
    render(<DataTable rows={[]} columns={[{ key: 'id', header: 'ID' }]} emptyMessage="No strategy records exist." />)
    expect(screen.getByText('No strategy records exist.')).toBeInTheDocument()
  })

  it('expands contextual row details on demand', () => {
    render(
      <DataTable
        rows={[{ id: 'd1', type: 'actual_enter' }]}
        columns={[{ key: 'id', header: 'ID' }]}
        renderDetail={(row) => <div>Raw payload access for {String(row.id)}</div>}
      />
    )

    expect(screen.queryByText('Raw payload access for d1')).not.toBeInTheDocument()
    fireEvent.click(screen.getByRole('button', { name: 'Detail' }))
    expect(screen.getByText('Raw payload access for d1')).toBeInTheDocument()
  })
})
