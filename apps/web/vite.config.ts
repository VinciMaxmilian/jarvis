import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

// Alvo do proxy de dev. O front usa caminho relativo (`fetch('/api/...')`), então
// ele DEPENDE deste proxy — e o alvo certo muda com onde o dev server roda:
//   `npm run dev` no host   -> http://127.0.0.1:8000 (porta publicada da api)
//   dentro do container web -> http://api:8000 (nome do serviço no compose;
//                              127.0.0.1 ali seria o próprio container do web)
// Por isso vem de env, com o caso do host como default. O compose injeta
// VITE_PROXY_TARGET=http://api:8000 no serviço `web`.
//
// process.env e não import.meta.env: este arquivo roda no Node (config do Vite),
// antes de existir bundle, e o prefixo VITE_ só vale para o que é exposto ao
// browser. Aqui o valor nunca chega ao cliente.
const proxyTarget = process.env.VITE_PROXY_TARGET || 'http://127.0.0.1:8000'

export default defineConfig({
  plugins: [react()],
  server: {
    // 0.0.0.0 para a porta publicada do container alcançar o dev server. No host
    // isso também escuta na LAN — aceitável: o compose publica só em loopback e a
    // exposição real é decisão do Cloudflare Tunnel (v1.5), não deste arquivo.
    host: true,
    port: 5173,
    strictPort: true,
    // O Vite recusa requisição cujo Host não esteja aqui — é defesa contra DNS
    // rebinding, não frescura. Chegando pelo túnel, o Host é `ia.atmosintelli...`
    // e o dev server respondia "Blocked request".
    //
    // Isto NÃO é a configuração de produção. O que deve ficar exposto à internet
    // é o `web-prod` (nginx, 127.0.0.1:5174, alvo `prod` do Dockerfile): build
    // otimizado, sem HMR, sem WebSocket de desenvolvimento aberto para fora. Esta
    // entrada existe para o caso de o dono querer depurar pelo celular através do
    // túnel, com o Access na frente — e sai da lista no dia em que a rota do
    // dashboard apontar para 5174 em definitivo.
    allowedHosts: ['ia.atmosintelli.com.br'],
    proxy: {
      '/api': {
        target: proxyTarget,
        changeOrigin: true,
        ws: true,
      }
    },
  },
})
