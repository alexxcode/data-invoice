FROM python:3.12-slim

WORKDIR /app

# Variables de entorno por defecto para Cloud Run
ENV PORT=8080
ENV PYTHONUNBUFFERED=1

# Instalar dependencias de sistema mínimas
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    && rm -rf /var/lib/apt/lists/*

# Copiar e instalar dependencias de Python
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copiar el código fuente
COPY . .

# Exponer el puerto
EXPOSE 8080

# Ejecutar el servidor FastAPI
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8080"]
