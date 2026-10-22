import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { beforeEach, expect, it, vi } from 'vitest'
import App from '../src/App'
import i18n, { localeStorageKey } from '../src/i18n/config'

beforeEach(async () => {
  vi.stubGlobal('fetch', vi.fn().mockResolvedValue(new Response(null, { status: 401 })))
  localStorage.clear()
  await i18n.changeLanguage('pt-BR')
})

it('shows the Portuguese landing page and switches every section live to English', async () => {
  const user = userEvent.setup()
  render(<App />)
  expect(screen.getByRole('link', { name: 'CivicFlow' })).toBeVisible()
  expect(screen.getByRole('heading', { name: 'Uma conexão mais próxima com sua cidade.' })).toBeVisible()
  expect(screen.getByText('Serviços ao cidadão')).toBeVisible()
  expect(screen.getByText('Sua cidade. Sua voz.')).toBeVisible()
  expect(screen.getByText(/Uma forma mais simples/)).toBeVisible()
  expect(screen.getByText('Em breve')).toBeVisible()
  expect(screen.getByRole('heading', { name: 'O chat do cidadão está chegando.' })).toBeVisible()
  expect(screen.getByText(/Esta experiência ainda está em desenvolvimento/)).toBeVisible()
  expect(screen.getByText('Feito para comunidades mais conectadas.')).toBeVisible()
  expect(document.documentElement.lang).toBe('pt-BR')

  await user.tab() // Brand link
  await user.tab() // Native select supports browser keyboard interaction.
  const selector = screen.getByRole('combobox', { name: 'Idioma' })
  expect(selector).toHaveFocus()
  expect(screen.getByRole('option', { name: 'Português' })).toBeVisible()
  expect(screen.getByRole('option', { name: 'English' })).toBeVisible()
  // jsdom does not implement native arrow-key option selection.
  await user.selectOptions(selector, 'en')
  expect(screen.getByRole('combobox', { name: 'Language' })).toHaveFocus()
  expect(screen.getByRole('heading', { name: 'A closer connection to your city.' })).toBeVisible()
  expect(screen.getByText('Citizen services')).toBeVisible()
  expect(screen.getByText('Your city. Your voice.')).toBeVisible()
  expect(screen.getByText(/A simpler way to find city services/)).toBeVisible()
  expect(screen.getByText('Coming soon')).toBeVisible()
  expect(screen.getByRole('heading', { name: 'Citizen chat is on its way.' })).toBeVisible()
  expect(screen.getByText(/This experience is still being built/)).toBeVisible()
  expect(screen.getByText('Built for more connected communities.')).toBeVisible()
  expect(document.documentElement.lang).toBe('en')
  await waitFor(() => expect(localStorage.getItem(localeStorageKey)).toBe('en'))

  await user.selectOptions(selector, 'pt-BR')
  expect(screen.getByRole('combobox', { name: 'Idioma' })).toHaveFocus()
  expect(document.documentElement.lang).toBe('pt-BR')
})
