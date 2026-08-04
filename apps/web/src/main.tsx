import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'
// Fontes do design system Industry, self-hosted. Nunca via fonts.googleapis:
// o PWA tem que abrir offline e a CSP do desk fecha em `font-src 'self'`.
// Só os subsets latin/latin-ext e só os pesos que o DS usa — Barlow 400/500/700
// no corpo, Barlow Condensed 400/600 nos títulos. Cada import extra vira um
// woff2 a mais no precache.
import '@fontsource/barlow/latin-400.css'
import '@fontsource/barlow/latin-500.css'
import '@fontsource/barlow/latin-700.css'
import '@fontsource/barlow/latin-ext-400.css'
import '@fontsource/barlow/latin-ext-500.css'
import '@fontsource/barlow/latin-ext-700.css'
import '@fontsource/barlow-condensed/latin-400.css'
import '@fontsource/barlow-condensed/latin-600.css'
import '@fontsource/barlow-condensed/latin-ext-400.css'
import '@fontsource/barlow-condensed/latin-ext-600.css'
// JetBrains Mono não é do DS, mas o HUD tem leitura numérica e duas páginas
// já pedem a família pelo nome. Vinha do Google Fonts pelo index.html — agora
// é local, senão sobrava exatamente uma requisição remota de fonte.
import '@fontsource/jetbrains-mono/latin-400.css'
import '@fontsource/jetbrains-mono/latin-500.css'
import '@fontsource/jetbrains-mono/latin-ext-400.css'
import '@fontsource/jetbrains-mono/latin-ext-500.css'
import './index.css'
import App from './App'
import { ThemeProvider } from './contexts/ThemeContext'

createRoot(document.getElementById('root')!).render(
  <StrictMode>
    <ThemeProvider>
      <App />
    </ThemeProvider>
  </StrictMode>,
)
