import { render, screen } from '@testing-library/react'
import { describe, expect, it } from 'vitest'
import App from '../src/App'

describe('application shell', () => {
  it('shows the product name and future citizen chat placeholder', () => {
    render(<App />)

    expect(screen.getByRole('link', { name: 'CivicFlow' })).toBeVisible()
    expect(screen.getByRole('heading', { name: 'Citizen chat is on its way.' })).toBeVisible()
    expect(screen.getByText(/This experience is still being built/)).toBeVisible()
  })
})
