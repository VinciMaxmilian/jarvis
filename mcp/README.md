# MCP Skills

Esta pasta contém as habilidades extras do J.A.R.V.I.S. baseadas no Model Context Protocol (MCP).

Cada pasta aqui dentro representa uma habilidade (um servidor MCP isolado) que o agente pode chamar quando necessário. 

## Como funciona
1. O J.A.R.V.I.S. pode criar dinamicamente novas pastas de habilidades aqui.
2. Cada habilidade deve ser um projeto isolado (em Python ou Node.js).
3. O `manager.py` detecta e inicia as habilidades, registrando-as no orquestrador.

## Criando uma habilidade manual
- **Python**: crie uma pasta, adicione `main.py` e um `requirements.txt`.
- **Node.js**: crie uma pasta, adicione `index.js` (ou similar) e um `package.json`.
