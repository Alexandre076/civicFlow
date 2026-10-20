import { env } from './config/env'
import styles from './App.module.css'

export default function App() {
  return (
    <div className={styles.shell} data-api-base-url={env.apiBaseUrl}>
      <header className={styles.header}>
        <a className={styles.brand} href="#main">CivicFlow</a>
        <span className={styles.badge}>Citizen services</span>
      </header>
      <main id="main" className={styles.main}>
        <section className={styles.intro} aria-labelledby="welcome-title">
          <p className={styles.eyebrow}>Your city. Your voice.</p>
          <h1 id="welcome-title">A closer connection to your city.</h1>
          <p className={styles.description}>
            A simpler way to find city services, share local concerns,
            and take part in your community.
          </p>
        </section>
        <section className={styles.placeholder} aria-labelledby="chat-title">
          <span className={styles.badge}>Coming soon</span>
          <h2 id="chat-title">Citizen chat is on its way.</h2>
          <p>
            In a future release, you’ll be able to ask questions and explore
            city services through a conversation. This experience is still
            being built.
          </p>
        </section>
      </main>
      <footer className={styles.footer}>
        <p>Built for more connected communities.</p>
      </footer>
    </div>
  )
}
