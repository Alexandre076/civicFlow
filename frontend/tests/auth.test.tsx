import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { beforeEach, expect, it, vi } from 'vitest'
import App from '../src/App'
import i18n from '../src/i18n/config'

beforeEach(async () => {
  await i18n.changeLanguage('pt-BR')
})

it('offers localized login on 401 and passes the selected locale', async () => {
  vi.stubGlobal('fetch', vi.fn().mockResolvedValue(new Response(null, { status: 401 })))
  render(<App />)
  expect(await screen.findByRole('link', { name: 'Entrar com Google' })).toHaveAttribute('href', '/api/v1/auth/google/login?locale=pt-BR')
})

it('applies server locale, keeps CSRF in memory and clears identity on logout', async () => {
  const fetchMock = vi.fn().mockResolvedValueOnce(new Response(JSON.stringify({
    id: 'user1', display_name: '<script>Ana</script>', email: null, preferred_locale: 'en',
  }), { headers: { 'X-CSRF-Token': 'csrf-test' } })).mockResolvedValueOnce(new Response(null, { status: 204 }))
  vi.stubGlobal('fetch', fetchMock)
  render(<App />)
  expect(await screen.findByText('Signed in as <script>Ana</script>')).toBeVisible()
  expect(screen.getByRole('combobox')).toBeDisabled()
  await userEvent.click(screen.getByRole('button', { name: 'Sign out' }))
  expect(await screen.findByRole('link', { name: 'Sign in with Google' })).toBeVisible()
  expect(fetchMock).toHaveBeenLastCalledWith('/api/v1/auth/logout', expect.objectContaining({
    method: 'POST', credentials: 'same-origin', headers: { 'X-CSRF-Token': 'csrf-test' },
  }))
  expect(localStorage.getItem('csrf-test')).toBeNull()
  expect(screen.queryByText('Signed in as <script>Ana</script>')).not.toBeInTheDocument()
})

it('reports service failure and allows retry', async () => {
  vi.stubGlobal('fetch', vi.fn().mockRejectedValueOnce(new Error('offline')).mockResolvedValueOnce(new Response(null, { status: 401 })))
  render(<App />)
  expect(await screen.findByRole('alert')).toHaveTextContent('Não foi possível')
  await userEvent.click(screen.getByRole('button', { name: 'Tentar novamente' }))
  await waitFor(() => expect(screen.queryByRole('alert')).not.toBeInTheDocument())
})
