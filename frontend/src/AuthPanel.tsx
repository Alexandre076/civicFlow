import { useEffect, useState } from 'react'
import { useTranslation } from 'react-i18next'
import styles from './AuthPanel.module.css'
import i18n, { isLocale } from './i18n/config'

type User = { id: string; display_name: string | null; email: string | null; preferred_locale: string }
type Auth = { user: User; csrf: string }

export default function AuthPanel({ onAuthenticated }: { onAuthenticated: (value: boolean) => void }) {
  const { t } = useTranslation()
  const [auth, setAuth] = useState<Auth | null>(null)
  const [busy, setBusy] = useState(true)
  const [error, setError] = useState(false)
  const [attempt, setAttempt] = useState(0)

  useEffect(() => {
    const controller = new AbortController()
    async function bootstrap() {
      setBusy(true)
      setError(false)
      try {
        const response = await fetch('/api/v1/auth/me', { credentials: 'same-origin', signal: controller.signal })
        if (response.status === 401) return
        if (!response.ok) throw new Error('auth')
        const user: User = await response.json()
        const csrf = response.headers.get('X-CSRF-Token')
        if (!csrf || !isLocale(user.preferred_locale)) throw new Error('auth')
        if (controller.signal.aborted) return
        await i18n.changeLanguage(user.preferred_locale)
        if (controller.signal.aborted) return
        setAuth({ user, csrf })
        onAuthenticated(true)
      } catch {
        if (!controller.signal.aborted) setError(true)
      } finally {
        if (!controller.signal.aborted) setBusy(false)
      }
    }
    void bootstrap()
    return () => controller.abort()
  }, [onAuthenticated, attempt])

  async function logout() {
    if (!auth) return
    setBusy(true)
    setError(false)
    try {
      const response = await fetch('/api/v1/auth/logout', {
        method: 'POST', credentials: 'same-origin', headers: { 'X-CSRF-Token': auth.csrf },
      })
      if (!response.ok && response.status !== 401) throw new Error('logout')
      setAuth(null)
      onAuthenticated(false)
      // No user-scoped history/cache exists yet. Future integrations must clear it here.
    } catch {
      setError(true)
    } finally {
      setBusy(false)
    }
  }

  return <section className={styles.account} aria-label={t('auth.title')} aria-busy={busy}>
    {busy && <p role="status">{t('auth.loading')}</p>}
    {error && <p role="alert">{t('auth.error')}</p>}
    {auth ? <>
      <p>{t('auth.signedIn', { name: auth.user.display_name || auth.user.email || t('auth.citizen') })}</p>
      <button type="button" disabled={busy} onClick={() => void logout()}>{t('auth.logout')}</button>
    </> : !busy && <>
      <a href={`/api/v1/auth/google/login?locale=${encodeURIComponent(i18n.resolvedLanguage || 'pt-BR')}`}>{t('auth.login')}</a>
      {error && <button type="button" onClick={() => setAttempt(attempt + 1)}>{t('auth.retry')}</button>}
    </>}
  </section>
}
