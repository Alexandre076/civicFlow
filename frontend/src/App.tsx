import { useTranslation } from 'react-i18next'
import { selectLocale, supportedLocales } from './i18n/config'
import { env } from './config/env'
import styles from './App.module.css'

export default function App() {
  const { t, i18n } = useTranslation()
  return (
    <div className={styles.shell} data-api-base-url={env.apiBaseUrl}>
      <header className={styles.header}>
        <a className={styles.brand} href="#main">{t('common.brand')}</a>
        <span className={styles.badge}>{t('home.services')}</span>
        <label className={styles.language}>
          {t('common.language')}
          <select value={i18n.resolvedLanguage} onChange={(event) => void selectLocale(event.target.value)}>
            {supportedLocales.map((locale) => (
              <option key={locale} value={locale} lang={locale}>{t(`common.languages.${locale}`)}</option>
            ))}
          </select>
        </label>
      </header>
      <main id="main" className={styles.main}>
        <section className={styles.intro} aria-labelledby="welcome-title">
          <p className={styles.eyebrow}>{t('home.welcome.eyebrow')}</p>
          <h1 id="welcome-title">{t('home.welcome.title')}</h1>
          <p className={styles.description}>
            {t('home.welcome.description')}
          </p>
        </section>
        <section className={styles.placeholder} aria-labelledby="chat-title">
          <span className={styles.badge}>{t('chat.placeholder.badge')}</span>
          <h2 id="chat-title">{t('chat.placeholder.title')}</h2>
          <p>
            {t('chat.placeholder.description')}
          </p>
        </section>
      </main>
      <footer className={styles.footer}>
        <p>{t('home.footer')}</p>
      </footer>
    </div>
  )
}
