FROM python:3.12-slim

WORKDIR /app

# Variables de entorno por defecto para Cloud Run
ENV PORT=8080
ENV PYTHONUNBUFFERED=1
ENV CELERY_BROKER_URL=redis://localhost:6379/0
ENV CELERY_RESULT_BACKEND=redis://localhost:6379/0

# Instalar dependencias de sistema mínimas
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    redis-server \
    tesseract-ocr \
    tesseract-ocr-spa \
    && rm -rf /var/lib/apt/lists/*

# Copiar e instalar dependencias de Python
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copiar el código fuente
COPY . .

# Exponer el puerto
EXPOSE 8080

# Ejecutar el script que inicializa redis, celery y uvicorn
CMD ["bash", "entrypoint.sh"]
