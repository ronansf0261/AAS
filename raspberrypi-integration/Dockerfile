# Use a imagem base do Python 3
FROM python:3.11-slim

# Defina o diretório de trabalho no contêiner
WORKDIR /app

# Copie o arquivo de requirements para o contêiner
COPY requirements.txt .

# Instale as dependências Python
RUN pip install --no-cache-dir -r requirements.txt

# Copie o restante do código para o contêiner
COPY . .

# Comando para rodar a aplicação
CMD ["python", "main.py"]
