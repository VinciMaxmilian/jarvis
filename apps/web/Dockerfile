# PWA (React 19 + Vite 8) — imagem de DESENVOLVIMENTO.
#
# ATENÇÃO: o contexto de build é a RAIZ do monorepo, igual às imagens Python.
#   docker build -f apps/web/Dockerfile .
# Isso é deliberado: o único .dockerignore do repo está na raiz, e é ele que
# impede o node_modules do host de entrar no contexto. Com `context: apps/web` o
# ignore não valeria e o build enviaria centenas de MB de binário nativo errado.
#
# Node 22: o Vite 8 exige >= 20.19 / 22.12. Alpine para caber no disco do i5-3470.

# --------------------------------------------------------------------------- #
# Estágio 1 — dependências
# --------------------------------------------------------------------------- #
FROM node:22-alpine AS deps

WORKDIR /app/apps/web

# Só os manifestos: `npm ci` (lockfile obrigatório, instalação reprodutível) só
# roda de novo quando package.json/package-lock.json mudam, não a cada .tsx salvo.
COPY apps/web/package.json apps/web/package-lock.json ./
RUN npm install --legacy-peer-deps --no-audit --no-fund

# --------------------------------------------------------------------------- #
# Estágio 2 — dev server
# --------------------------------------------------------------------------- #
FROM node:22-alpine AS dev

ENV NODE_ENV=development

WORKDIR /app/apps/web

# --chown=node:node não é cosmético: o Vite escreve o dep-cache em
# node_modules/.vite e, sem permissão, recompila as deps a cada boot.
COPY --from=deps --chown=node:node /app/apps/web/node_modules ./node_modules
COPY --chown=node:node apps/web/ ./

# Usuário não-root: a imagem node já traz `node` (uid 1000).
USER node

EXPOSE 5173

# --host 0.0.0.0 é obrigatório: o default do Vite é 127.0.0.1 e, dentro de um
# container, isso não é alcançável pela porta publicada.
# --strictPort: falhar é melhor que subir numa porta que ninguém está mapeando.
CMD ["npm", "run", "dev", "--", "--host", "0.0.0.0", "--port", "5173", "--strictPort"]

# --------------------------------------------------------------------------- #
# Estágio 3 — build
#
# `npm run build` é `tsc -b && vite build`: erro de tipo REPROVA a imagem de
# produção. É de propósito — o dev server do Vite não checa tipo, então este é
# o único ponto do pipeline do front onde o TypeScript é obrigatório.
# --------------------------------------------------------------------------- #
FROM deps AS build
COPY --chown=node:node apps/web/ ./
RUN npm run build

# --------------------------------------------------------------------------- #
# Estágio 4 — prod (nginx servindo o build estático)
#
# É ESTE o estágio que o Cloudflare Tunnel publica (serviço `web-prod` do
# compose, profile `prod`). O estágio `dev` acima nunca deve ir para a internet.
# --------------------------------------------------------------------------- #
FROM nginx:alpine AS prod

# A config default da imagem serve /usr/share/nginx/html na 80 e colidiria com a
# nossa no mesmo `include /etc/nginx/conf.d/*.conf`.
RUN rm /etc/nginx/conf.d/default.conf

# nginx.conf: server na 5173, SPA com fallback para index.html, proxy de /api/
# (com WebSocket) e de /health para a api.
COPY apps/web/nginx.conf /etc/nginx/conf.d/

# security-headers.inc: cabeçalhos de segurança, incluídos POR LOCATION pelo
# nginx.conf. A extensão .inc não é estilo — o nginx.conf da imagem base faz
# `include /etc/nginx/conf.d/*.conf`, e um .conf aqui seria carregado sozinho no
# contexto `http`, fora de qualquer server. O arquivo explica o resto.
#
# Sem este COPY o `include` do nginx.conf falha e o container NÃO SOBE. Isso é
# melhor do que a alternativa: até esta versão o arquivo existia no repositório,
# não era copiado, não era incluído, e a imagem servia o PWA sem nenhum dos
# cabeçalhos que ele documenta — em silêncio.
COPY apps/web/nginx/security-headers.inc /etc/nginx/conf.d/

COPY --from=build /app/apps/web/dist /usr/share/nginx/html

EXPOSE 5173
CMD ["nginx", "-g", "daemon off;"]
