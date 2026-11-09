FROM python:3.11-slim

WORKDIR /app

# Instala dependências de compilação mínimas
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    && rm -rf /var/lib/apt/lists/*

# Copia dependências do projeto
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copia código-fonte e plugins
COPY src/ src/
COPY plugins/ plugins/
COPY config/ config/
COPY pyproject.toml .

# Instala pacote em modo editável
RUN pip install --no-cache-dir -e .

# Cria diretório de dados persistente
RUN mkdir -p data

EXPOSE 8080

ENV PYTHONUNBUFFERED=1

CMD ["python", "-m", "smc_trader.cli", "ui", "--host", "0.0.0.0", "--port", "8080"]
