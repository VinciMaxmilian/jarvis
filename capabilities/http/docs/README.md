# http — buscar e enviar por HTTP, só para hosts concedidos

Terceira capability de uso geral. Faz GET e POST, com uma diferença que atravessa
todo o resto: **o host não é conhecido em tempo de escrita, vem no argumento** —
e por isso a conferência de escopo acontece em runtime, a cada chamada.

## Tools

| Tool | O que faz | Idempotente | Aprovação |
|---|---|---|---|
| `http_get` | GET numa URL de host concedido. Devolve status, cabeçalhos e corpo. | sim | não |
| `http_post` | POST com corpo em texto e `Content-Type` escolhido. | não | **sim** |

Chamada, como o kernel a faz:

```python
from capabilities.http.backend.handlers import main

main("http_get", {"url": "https://api.github.com/rate_limit"})
# {"url": "...", "status_code": 200, "headers": {...}, "corpo": "{...}",
#  "bytes": 271, "truncado": False}
```

`http_get` é declarado idempotente porque GET é a definição de idempotente no
HTTP — é o que autoriza o kernel a repetir a chamada depois de uma falha de
transporte sem perguntar. `http_post` exige aprovação porque muda estado do outro
lado, e o outro lado não é do dono.

## Por que a conferência é em runtime

`exemplo_nas` contata um host só, conhecido quando a capability foi escrita, e
declara isso estático: `requires=ToolRequirements(network=(HOST_NAS,))`. O SDK
confere essa declaração contra o manifest **sem rodar nada**.

Uma capability HTTP de uso geral não tem esse host. Então as tools daqui declaram
`requires` **vazio** e `_conferir_host()` compara o host da URL contra
`permissions.network` a cada chamada.

**Consequência aceita:** o harness emite aviso (`_avisos_de_escopo`) dizendo que
os hosts concedidos no manifest não são exigidos por nenhuma tool. O aviso está
certo sobre o fato e errado sobre a conclusão. Aviso não derruba o harness; o que
derrubaria a confiança seria declarar `requires` estático mentindo que só um host
é contatado.

Debaixo disso continua o guarda do kernel, que intercepta `connect()` dentro do
subprocesso e é quem **de fato** impede a conexão. A camada daqui existe para que
a negação chegue a quem chamou como `PermissaoNaoDeclarada` com o host em
`target`, e não como task falhada com erro de socket.

## Três decisões que não são detalhe

**Redirecionamento não é seguido** (`REDIRECIONAMENTOS = False`). Seguir um
`Location` é contatar um host que o chamador não pediu e que a conferência de
escopo já passou. O `Location` volta nos cabeçalhos; quem quiser segui-lo chama
de novo, e o host novo passa pela mesma conferência.

**O corpo é lido em pedaços**, não com `response.text`. Teto de tamanho só é teto
se a leitura para quando ele é atingido — baixar 500 MiB para depois cortar em
1 MiB gasta exatamente a banda e a memória que o teto existe para poupar. Quando
corta, `truncado: true` volta na resposta.

**`status_code` fora de 2xx não é falha da tool.** A requisição foi feita e o
servidor respondeu 404 — isso é resultado, e vai para o modelo decidir. Falha da
tool é não conseguir requisitar: host não concedido, DNS que não resolve,
conexão recusada, timeout.

## Dependência

`httpx` **não** é importado no topo do módulo: o import mora dentro de
`cliente_httpx`. Assim o módulo carrega — e o harness confere o catálogo de
tools — numa máquina onde a dependência não esteja instalada. O cliente é
injetável (`Cliente`, um `Protocol`), que é como a suíte roda sem tocar a rede.

## Concessão

`permissions.network` no `manifest.yaml` traz hoje apenas `api.github.com`, como
concessão de partida. Host fora dessa lista é `PermissaoNaoDeclarada`; lista
vazia significa que a capability não sai da máquina. Ampliar a concessão é
editar o manifest — nunca a lista em código.

## Estado

`status: pending_approval`, `approved_commit: null`. O registry só carrega
`active`, então esta capability ainda não é oferecida a `resolve()`. É o estado
honesto de quem não passou por um Gate 2.
