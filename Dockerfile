FROM python:3.12-slim

# Instala Node.js 20+, git e tzdata (fuso horário de Brasília)
RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
    ca-certificates \
    gnupg \
    git \
    tzdata \
    && curl -fsSL https://deb.nodesource.com/setup_20.x | bash - \
    && apt-get install -y --no-install-recommends nodejs \
    && apt-get clean && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Instala dependências Python
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Instala dependências Node da ponte WhatsApp
COPY whatsapp-bridge/package.json ./whatsapp-bridge/package.json
RUN cd whatsapp-bridge && npm install --omit=dev

# Copia o restante do código
COPY . .

ENV PYTHONUTF8=1
ENV TZ=America/Sao_Paulo
ENV PORT=8000

EXPOSE 8000

CMD ["sh", "-c", "python -m uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-8000}"]
