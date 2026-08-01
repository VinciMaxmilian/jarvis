# Plano de Implementação: Jarvis Mobile (React Native + Expo)

O objetivo deste plano é detalhar a criação de um aplicativo móvel (focado em iOS, mas compatível com Android) para o ecossistema Jarvis. O projeto utilizará **React Native com o framework Expo** e ficará isolado na pasta `apps/mobile`.

## User Review Required

> [!IMPORTANT]
> **Configuração Inicial do Projeto:** Ao iniciar a execução, usaremos o comando `npx create-expo-app apps/mobile --template blank-typescript` para gerar toda a fundação do aplicativo. Isso criará uma estrutura padrão que será modificada para se alinhar com a arquitetura descrita abaixo.

## Proposed Changes

Toda a lógica e os arquivos ficarão contidos no novo diretório `apps/mobile`.

### 1. Inicialização e Dependências

Serão instaladas as seguintes bibliotecas principais no ambiente Expo:
- **Navegação:** `@react-navigation/native`, `@react-navigation/bottom-tabs` (para as abas inferiores) e `@react-navigation/native-stack`.
- **Autenticação Cloudflare:** `react-native-webview` (para carregar a tela de login do CF Access) e `expo-secure-store` (para salvar os cookies de sessão de forma criptografada no aparelho).
- **Networking:** `axios` (para gerenciar requisições à API e interceptar headers).
- **Gerenciamento de Estado:** `zustand` (leve e eficiente para manter os chats, histórico e metas).
- **Estilização:** Criação de um Design System utilizando os próprios `StyleSheet` nativos do React Native ou biblioteca similar, com suporte a tema escuro (Dark Mode).

### 2. Estrutura de Diretórios (dentro de `apps/mobile`)

O projeto seguirá uma estrutura modularizada e organizada dentro de uma pasta `src/`:

```text
apps/mobile/
├── App.tsx                  # Ponto de entrada e configuração dos Providers (Navegação/Contextos)
└── src/
    ├── api/                 # Configuração do Axios e serviços de busca
    │   ├── client.ts        # Instância do Axios que injeta o Cookie do Cloudflare
    │   ├── chat.ts          # Chamadas para os routers de chat da API Python
    │   └── goals.ts         # Chamadas para metas
    ├── components/          # Componentes visuais reaproveitáveis
    │   ├── MessageBubble.tsx# Balão de chat (usuário/IA)
    │   ├── InputBar.tsx     # Barra de digitação do chat
    │   └── GoalCard.tsx     # Card de meta
    ├── screens/             # Telas principais do aplicativo
    │   ├── LoginScreen.tsx  # Tela com WebView para autenticação no Cloudflare Access
    │   ├── ChatScreen.tsx   # Tela principal de interação
    │   ├── HistoryScreen.tsx# Lista de conversas passadas
    │   └── SettingsScreen.tsx# Configurações do app/IA
    ├── store/               # Gerenciamento de estado (Zustand)
    │   ├── useAuthStore.ts  # Gerencia token do Cloudflare e estado de login
    │   └── useChatStore.ts  # Gerencia a lista de mensagens do chat ativo
    └── theme/               # Cores, espaçamentos e tipografia
        └── colors.ts
```

### 3. Fluxo de Autenticação e Cloudflare Access

1. Ao abrir o app, o `App.tsx` verifica no `SecureStore` se já existe um Cookie do Cloudflare válido salvo.
2. **Se não houver (ou estiver expirado):** O usuário é levado para a `LoginScreen`. Esta tela abre um `WebView` apontando para a URL pública do Jarvis (ex: `https://jarvis.seu-dominio.com`).
3. O usuário fará o login (email/GitHub/OTP) dentro do WebView.
4. O código React Native irá interceptar os cookies de navegação do WebView através da prop `onNavigationStateChange`.
5. Quando detectar o cookie `CF_Authorization`, o WebView é fechado, o cookie é salvo no celular (SecureStore), e o usuário vai para a tela de Chat.
6. A partir desse momento, todas as chamadas do Axios usarão: `headers: { Cookie: "CF_Authorization=..." }`.

### 4. Integração com a API

- O backend (Python/FastAPI em `apps/api`) continuará intacto.
- O app consumirá as mesmas rotas que a versão Web consome, garantindo que Histórico e Metas (Goals) fiquem sempre sincronizados entre Web e Mobile.

## Verification Plan

### Etapas de Validação Local
- Acessaremos a pasta `apps/mobile`.
- Rodaremos `npx expo start` (que levanta o empacotador Metro do React Native).
- Você poderá verificar o aplicativo rodando escaneando o QR Code fornecido pelo terminal diretamente no aplicativo **Expo Go** (disponível gratuitamente na App Store do seu iPhone).

### Validação do Login Externo
- Validaremos se o WebView consegue renderizar a tela do Cloudflare Access corretamente e capturar o cookie após o login bem sucedido.

### Validação da Interface (UI)
- Testar o input do teclado (garantindo que o layout "suba" quando o teclado do iOS aparecer, utilizando `KeyboardAvoidingView`).


## Adendo: 
Foi pedido para colocar o brain de fundo na aba de conversa, mas não está funcionando muito bem:
- Para deixar mais facil de ver os nodes acendendo e os traces, deixe todo o brain cinza (só na aba de chat), e alem de acender, vai colorindo de volta os nodes e traces
