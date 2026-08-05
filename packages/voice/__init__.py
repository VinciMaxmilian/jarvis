"""Peças da conversação por voz: quebra em frases e síntese (TTS).

Vive em `packages/` e não em `apps/api/` pelo mesmo motivo dos outros pacotes: o
roteador do FastAPI é um adaptador, não o dono da regra. Aqui não se importa nada
de `apps/`, e `tests/test_architecture.py` reprova o contrário.
"""
