import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import i18n, { localeStorageKey, resolveInitialLocale, selectLocale } from '../src/i18n/config'
import en from '../src/i18n/locales/en.json'
import ptBR from '../src/i18n/locales/pt-BR.json'

beforeEach(() => {
  localStorage.clear()
  vi.spyOn(navigator, 'languages', 'get').mockReturnValue([])
  vi.spyOn(navigator, 'language', 'get').mockReturnValue('')
})
afterEach(() => vi.restoreAllMocks())

describe('initial locale', () => {
  it.each([
    [['fr', 'en-US', 'pt-BR'], 'pt', 'en'],
    [['ro', 'pt-PT', 'en'], 'en', 'pt-BR'],
    [['PT-br'], '', 'pt-BR'],
    [['en'], '', 'en'],
    [[], 'en-GB', 'en'],
    [['it'], 'en-AU', 'en'],
    [['fr', 'ro'], 'it', 'pt-BR'],
    [[], '', 'pt-BR'],
  ])('resolves %j with language %s to %s', (languages, language, expected) => {
    vi.spyOn(navigator, 'languages', 'get').mockReturnValue(languages)
    vi.spyOn(navigator, 'language', 'get').mockReturnValue(language)
    expect(resolveInitialLocale()).toBe(expected)
  })

  it.each(['pt-BR', 'en'])('prefers saved %s over browser languages', (locale) => {
    localStorage.setItem(localeStorageKey, locale)
    vi.spyOn(navigator, 'languages', 'get').mockReturnValue(['en', 'pt'])
    expect(resolveInitialLocale()).toBe(locale)
  })

  it.each(['fr', 'en-US', 'pt', '', 'null'])('ignores stale saved value %s', (locale) => {
    localStorage.setItem(localeStorageKey, locale)
    vi.spyOn(navigator, 'languages', 'get').mockReturnValue(['en'])
    expect(resolveInitialLocale()).toBe('en')
  })

  it('survives an unavailable storage getter', () => {
    vi.spyOn(window, 'localStorage', 'get').mockImplementation(() => { throw new Error('blocked') })
    expect(resolveInitialLocale()).toBe('pt-BR')
  })

  it('survives a failed storage read', () => {
    vi.spyOn(Storage.prototype, 'getItem').mockImplementation(() => { throw new Error('blocked') })
    vi.spyOn(navigator, 'language', 'get').mockReturnValue('en')
    expect(resolveInitialLocale()).toBe('en')
  })
})

it('persists only valid manual selections and restores them on the next visit', async () => {
  await selectLocale('en')
  expect(localStorage.getItem(localeStorageKey)).toBe('en')
  expect(localStorage.length).toBe(1)
  expect(resolveInitialLocale()).toBe('en')
  await selectLocale('fr')
  expect(i18n.language).toBe('en')
  expect(localStorage.getItem(localeStorageKey)).toBe('en')
})

it('keeps the selected locale when storage writes fail', async () => {
  vi.spyOn(Storage.prototype, 'setItem').mockImplementation(() => { throw new Error('quota') })
  await selectLocale('pt-BR')
  expect(i18n.language).toBe('pt-BR')
  expect(document.documentElement.lang).toBe('pt-BR')
})

it('falls back to Portuguese for an absent English translation and tolerates unknown keys', async () => {
  await i18n.changeLanguage('en')
  i18n.addResource('pt-BR', 'translation', 'fallbackTest', 'Texto de fallback')
  try {
    expect(i18n.t('fallbackTest')).toBe('Texto de fallback')
    expect(i18n.t('unknown.key')).toBe('unknown.key')
  } finally {
    delete i18n.getResourceBundle('pt-BR', 'translation').fallbackTest
  }
})

function keys(value: object, prefix = ''): string[] {
  return Object.entries(value).flatMap(([key, child]) => {
    const path = prefix ? `${prefix}.${key}` : key
    return typeof child === 'string' ? [path] : keys(child, path)
  }).sort()
}

it('keeps matching semantic keys in both catalogues', () => {
  expect(keys(en)).toEqual(keys(ptBR))
})
