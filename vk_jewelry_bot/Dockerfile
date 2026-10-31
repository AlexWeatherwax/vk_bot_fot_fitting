FROM python:3.11-slim

# Local inference must not initialize ONNX Runtime telemetry.
ENV ORT_DISABLE_TELEMETRY=1

# Системные библиотеки, нужные opencv/mediapipe для работы с изображениями
RUN apt-get update && apt-get install -y --no-install-recommends \
    libgl1 \
    libglib2.0-0 \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

# .env в образ не кладём — прокидывается на этапе docker run / docker-compose (env_file/--env-file)
CMD ["python", "run.py"]
