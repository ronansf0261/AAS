# Dockerfile
# Use a imagem original como base
FROM aas_core_v1.1.2

# Copie o arquivo de requisitos para dentro da imagem
COPY ./requirements.txt /app/requirements.txt

# Execute o pip para instalar as bibliotecas listadas no arquivo
RUN pip install -r /app/requirements.txt