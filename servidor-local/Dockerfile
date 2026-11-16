# Imagem do ambiente Hermes local: servidores AAS (asyncua), gateway do CR3 e simuladores.
# Só instala as bibliotecas; o código entra por volume no docker-compose.yaml
# (mudou o código, basta "docker compose restart <serviço>").
FROM python:3.11-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1

WORKDIR /app
COPY requirements.txt /tmp/requirements.txt
RUN pip install --no-cache-dir -r /tmp/requirements.txt
