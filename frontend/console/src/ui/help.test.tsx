import { render, screen } from '@testing-library/react'
import { describe, expect, it } from 'vitest'

import { CaveatChips, MetricHelp, PageExplainer, formatCaveatLabel } from './help'

describe('console help helpers', () => {
  it('translates raw caveat keys to human-readable labels', () => {
    expect(formatCaveatLabel('missing_risk_budget')).toBe('Missing risk budget')
    expect(formatCaveatLabel('low-N')).toBe('Small sample size')
    expect(formatCaveatLabel('custom_snake_case')).toBe('Custom Snake Case')
  })

  it('renders caveat chips without exposing raw snake_case as product copy', () => {
    render(<CaveatChips value={['missing_source', 'low_n']} />)
    expect(screen.getByText('Missing source evidence')).toBeInTheDocument()
    expect(screen.getByText('Small sample size')).toBeInTheDocument()
    expect(screen.queryByText('missing_source')).not.toBeInTheDocument()
  })

  it('renders metric help and page explainer copy', () => {
    render(
      <>
        <MetricHelp label="win rate" />
        <PageExplainer answers="question" data="source" read="reading" mislead="caveat" />
      </>
    )
    expect(screen.getByLabelText('win rate definition')).toBeInTheDocument()
    expect(screen.getByText('Answers')).toBeInTheDocument()
    expect(screen.getByText('Can mislead when')).toBeInTheDocument()
  })
})
