# Cabeçalhos de segurança — snippet incluído em CADA location que declara
# `add_header` próprio.
#
# POR QUE UM ARQUIVO SEPARADO E POR QUE REPETIDO EM TODA LOCATION:
# `add_header` no nginx NÃO é acumulativo entre níveis. A herança do bloco de
# cima só acontece quando o nível de baixo não declara NENHUM `add_header`. Ou
# seja: bastaria um `add_header Cache-Control ...` dentro de /assets/ para que
# TODOS os cabeçalhos de segurança do `server` sumissem daquela location, em
# silêncio, sem erro de configuração. Este include existe para tornar essa
# repetição explícita e impossível de esquecer.
#
# POR QUE A EXTENSÃO É .inc E NÃO .conf:
# o nginx.conf da imagem faz `include /etc/nginx/conf.d/*.conf`. Um arquivo
# .conf aqui seria incluído sozinho no contexto `http`, fora de qualquer
# `server`, e aplicaria estes cabeçalhos globalmente — que é o oposto do
# controle explícito que queremos.
#
# `always` em todos: sem ele o cabeçalho só sai em respostas 2xx/3xx. Um 404 do
# SPA ou um 502 do proxy também precisam de nosniff e de Referrer-Policy.

# Impede o browser de "adivinhar" o Content-Type. Sem isso, um .json com
# conteúdo controlado por terceiro pode ser interpretado como HTML/JS.
add_header X-Content-Type-Options "nosniff" always;

# Nada deste app é feito para viver dentro de frame. DENY mata clickjacking sem
# custo: nenhuma página do PWA usa <iframe> (verificado em apps/web/src/).
add_header X-Frame-Options "DENY" always;

# Não vaza o path completo (que pode conter id de conversa) para origem externa;
# same-origin continua recebendo a URL inteira.
add_header Referrer-Policy "strict-origin-when-cross-origin" always;

# O app não usa nenhuma dessas APIs (verificado: não há getUserMedia,
# SpeechRecognition nem geolocation em apps/web/src/). Desligar por padrão é de
# graça e limita o estrago de um script de terceiro injetado.
add_header Permissions-Policy "camera=(), microphone=(), geolocation=(), payment=(), usb=()" always;

# Isola o browsing context de janelas abertas por/para outra origem.
add_header Cross-Origin-Opener-Policy "same-origin" always;

# --------------------------------------------------------------------------- #
# CSP: EM REPORT-ONLY, DE PROPÓSITO.
#
# Não é cargo cult nem preguiça — é o que a página realmente carrega hoje
# (apps/web/index.html):
#   - fonts.googleapis.com  -> <link rel=stylesheet> (CSS de fonte)
#   - fonts.gstatic.com     -> arquivos .woff2 referenciados por aquele CSS
#   - cdn.jsdelivr.net      -> katex.min.css + as fontes do KaTeX
# Além disso o React escreve `style={{...}}` inline em quase toda página e o
# Tailwind v4 injeta CSS em runtime: `style-src` SEM 'unsafe-inline' apaga o
# layout inteiro.
#
# Em REPORT-ONLY o browser avalia a política e reporta violação no console, mas
# NÃO bloqueia nada. Isso permite versionar a política real, ver o que ela
# quebraria e promover para `Content-Security-Policy` (enforce) só depois que o
# console estiver limpo. Ligar em enforce hoje, sem essa passagem, é a forma
# mais rápida de publicar uma tela branca.
#
# Para ENFORCE no futuro: troque o nome do cabeçalho abaixo, e antes disso
# elimine as dependências de CDN (auto-hospedar Inter/JetBrains Mono/KaTeX
# encolhe a política para 'self' e ainda tira 3 conexões externas do caminho
# crítico).
#
# connect-src cobre ws: e wss: porque o chat abre WebSocket para a MESMA origem
# (apps/web/src/pages/ChatPage.tsx monta a URL com window.location.host) — e
# 'self' em connect-src NÃO cobre o esquema ws:/wss: em todos os browsers.
add_header Content-Security-Policy-Report-Only "default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline' https://fonts.googleapis.com https://cdn.jsdelivr.net; font-src 'self' data: https://fonts.gstatic.com https://cdn.jsdelivr.net; img-src 'self' data: blob:; connect-src 'self' ws: wss:; frame-ancestors 'none'; base-uri 'self'; form-action 'self'; object-src 'none'" always;

# --------------------------------------------------------------------------- #
# HSTS: DELIBERADAMENTE AUSENTE AQUI.
#
# Quem termina TLS é a Cloudflare; este nginx só fala HTTP em claro dentro do
# túnel. HSTS é política de HOST e vale para o host inteiro, com validade longa
# e efeito difícil de reverter — o lugar dele é o painel da Cloudflare (SSL/TLS
# -> Edge Certificates -> HSTS), onde dá para ligar, ver e desligar. Emitir daqui
# também gruda o cabeçalho no acesso local de teste (127.0.0.1:<porta>), e um
# browser que decida honrar HSTS em loopback transforma um teste em dor de
# cabeça permanente.
