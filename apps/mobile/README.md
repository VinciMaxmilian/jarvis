# Jarvis Mobile

App React Native (Expo SDK 57) para o ecossistema Jarvis. Fala com a **mesma
origem** que o PWA — `https://ia.atmosintelli.com.br` —, atrás do mesmo
Cloudflare Access, consumindo os mesmos routers de `apps/api`.

## Rodar

```powershell
cd apps/mobile
npx expo start          # sobe o Metro; leia o QR code no Expo Go (iOS/Android)
npm run typecheck       # tsc --noEmit
```

Para apontar para um backend local sem editar arquivo versionado:

```powershell
$env:EXPO_PUBLIC_API_BASE_URL = "http://192.168.0.10:8000"; npx expo start
```

A precedência é `EXPO_PUBLIC_API_BASE_URL` → `expo.extra.apiBaseUrl` (`app.json`)
→ constante em `src/config.ts`.

## Mapa do código

```text
App.tsx                       providers, gate de auth, tabs + stack
src/
  config.ts                   origem HTTP e WS
  api/                        axios com credencial do Access; um módulo por router
    client.ts                 instância única, interceptor de 401, probeSession()
    chat.ts                   ChatSocket (WebSocket) + fallback POST
    graph.ts                  /graph.json reduzido para caber num celular
  components/
    Brain/brainHtml.ts        motor do cérebro (canvas 2D dentro de um WebView)
    Brain/BrainCanvas.tsx     ponte RN -> motor (comandos por injectJavaScript)
    MessageBubble.tsx  InputBar.tsx  GoalCard.tsx
  screens/                    Login, Chat, Goals, Brain, History, Settings
  store/                      useAuthStore (sessão), useChatStore (conversa)
  navigation/types.ts         param lists (evita ciclo App <-> telas)
  theme/colors.ts             tokens espelhando apps/web/src/index.css
```

### Autenticação — os dois modos

O cookie `CF_Authorization` é HttpOnly, então "ler o cookie no WebView" só
funciona em implantações que afrouxem isso. O app tenta os dois caminhos:

- **`token`** — o sniffer injetado conseguiu ler o JWT. Vai para o SecureStore e
  toda requisição manda `Cf-Access-Jwt-Assertion` **e** `Cookie` explicitamente,
  inclusive no handshake do WebSocket.
- **`cookieJar`** — não deu para ler, mas com `sharedCookiesEnabled` o cookie que
  o WebView gravou é o mesmo que o axios usa. A prova é empírica:
  `probeSession()` bate em `GET /api/tools/`.

### O brain na aba de chat

Cada nó guarda dois valores independentes: `flash` (o acender, decai em ~2 s) e
`lit` (a cor, **não** volta atrás). No modo `chat` o cérebro nasce todo cinza —
luminância perceptual Rec. 601, não média de canais — e vai sendo *colorido de
volta* conforme os `tool_call` tocam arquivos. Arestas seguem a média do `lit`
das duas pontas; vizinhos de um nó tocado ganham `lit` parcial, o que faz a cor
se espalhar em vez de aparecer em pontos soltos.

O casamento `tool_call` → nó é por `source_file`, com contenção fuzzy nos dois
sentidos (o caminho chega absoluto do container, relativo do repo ou com barra
invertida).

---

## O que precisa de validação manual

Nada abaixo foi verificado nesta máquina: não há modelo de inferência aqui, e
Expo Go não roda em Windows. `npx tsc --noEmit` passa limpo e o Metro sobe — é
todo o sinal automatizado que existe.

### 1. Login no Cloudflare Access (o item de maior risco)

- [ ] O WebView renderiza a tela do Access e conclui o login (email/OTP/GitHub).
- [ ] Ao voltar para a origem, o app entra sozinho. Se ficar parado, o botão
      **JÁ ENTREI** força a verificação — se só ele funcionar, o gatilho de
      `onNavigationStateChange` não está pegando o fim do fluxo.
- [ ] Qual modo ficou ativo: veja **Ajustes → SESSÃO → modo**. `cookie do
      sistema` = `cookieJar`, `JWT capturado` = `token`.
- [ ] **Risco conhecido:** provedores de identidade (Google, notoriamente)
      rejeitam user agents de WebView com `disallowed_useragent`. Se acontecer,
      a saída é `expo-web-browser`/ASWebAuthenticationSession em vez do WebView —
      mudança de dependência, decisão do dono.
- [ ] Fechar e reabrir o app mantém a sessão (SecureStore + probe de boot).
- [ ] **Ajustes → SAIR** volta para o login e não reconecta o socket sozinho.

### 2. Chat

- [ ] O cabeçalho mostra `LINKED` (socket aberto). `OFFLINE` persistente indica
      que o proxy cortou o Upgrade — nesse caso o envio ainda funciona pelo
      fallback HTTP e a faixa âmbar avisa que não há streaming nem brain.
- [ ] Texto chega em streaming, token a token.
- [ ] Chips âmbar com nome de tool aparecem na bolha durante a resposta.
- [ ] **Teclado do iOS:** a barra de digitação sobe junto e não fica atrás da tab
      bar. É o ajuste mais provável de precisar de retoque
      (`keyboardVerticalOffset` em `ChatScreen`).
- [ ] **NOVA** limpa a conversa e o cérebro volta ao cinza.

### 3. Brain

- [ ] `/graph.json` carrega através do Access (é servido pelo nginx do PWA, não
      pela API). Falha aparece como faixa "Brain sem grafo: ...".
- [ ] Aba **Chat**: fundo cinza, nós acendendo e **ganhando cor** conforme as
      tools rodam — o adendo do plano. Verificar que a cor *permanece* depois do
      flash apagar.
- [ ] Aba **Brain**: colorido, arrastar gira, pinçar aproxima.
- [ ] Desempenho num aparelho real: o grafo é reduzido para ~260 nós / 900
      arestas em `src/api/graph.ts`. Se engasgar, `MAX_NODES` é o botão.
- [ ] Duas instâncias do WebView coexistem (fundo do chat + aba Brain). Se a
      memória apertar em aparelho antigo, desmontar a aba Brain quando ela perde
      foco é a primeira mitigação.

### 4. Metas

- [ ] Criar meta, expandir (carrega tarefas sob demanda), executar.
- [ ] **EXECUTAR** roda a decomposição inteira dentro da requisição e pode levar
      minutos (timeout do cliente: 10 min). Confirmar que a tela continua
      utilizável e que a lista recarrega ao fim.

### 5. Ajustes

- [ ] Trocar de provider atualiza o modelo para o default dele.
- [ ] Salvar (PUT) persiste e os PERFIS EM VIGOR são relidos.
- [ ] Com o provider desligado, a seção de perfis mostra o erro **sem** impedir a
      troca de provider.

### Fora de escopo, registrado

- Sem streaming de progresso de metas: `GET /goals/{id}/stream` é SSE e o `fetch`
  do React Native não faz streaming de resposta. O chat contorna com WebSocket;
  metas não têm canal equivalente. Pull-to-refresh cobre o intervalo.
- Sem markdown nas mensagens (o PWA usa `react-markdown` + KaTeX).
- Sem push notifications, sem modo offline, sem testes automatizados.
