FROM ubuntu:24.04

RUN apt-get update && apt-get install -y \
    git curl wget python3 python3-pip nodejs npm \
    gh patch \
    # Playwright system dependencies
    libnss3 libatk1.0-0 libatk-bridge2.0-0 libcups2 \
    libdrm2 libxkbcommon0 libxcomposite1 libxdamage1 \
    libxfixes3 libxrandr2 libgbm1 libasound2 \
    && rm -rf /var/lib/apt/lists/*

# Playwright + Chromium at IMAGE build time — not per task
RUN npm install -g playwright && npx playwright install chromium

# Bun runtime
RUN curl -fsSL https://bun.sh/install | bash
ENV PATH="/root/.bun/bin:$PATH"

WORKDIR /app
COPY requirements.txt .
RUN pip3 install -r requirements.txt --break-system-packages

COPY . .
WORKDIR /workspace

CMD ["python3", "/app/worker/main.py"]
