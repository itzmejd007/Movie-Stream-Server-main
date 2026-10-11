FROM python:3.10-slim

WORKDIR /app

# Install system dependencies: git, ffmpeg, build essentials for pyrotgfork & tgcrypto
RUN apt-get update && apt-get install -y --no-install-recommends \
    git \
    ffmpeg \
    gcc \
    python3-dev \
    curl \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .
RUN chmod +x start.sh

EXPOSE 8000 7860

CMD ["bash", "start.sh"]
