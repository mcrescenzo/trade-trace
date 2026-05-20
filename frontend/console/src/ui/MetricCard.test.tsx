import { render, screen } from '@testing-library/react'
import { Activity } from 'lucide-react'
import { describe, expect, it } from 'vitest'

import { MetricCard } from './MetricCard'

describe('MetricCard', () => {
  it('renders a metric label and value', () => {
    render(<MetricCard label="Events" value={42} icon={Activity} />)
    expect(screen.getByText('Events')).toBeInTheDocument()
    expect(screen.getByText('42')).toBeInTheDocument()
  })
})

