FROM python:3.12-slim

WORKDIR /app

# Системные зависимости для pdfplumber
RUN apt-get update && apt-get install -y \
    libpoppler-cpp-dev \
    poppler-utils \
    gcc \
    tesseract-ocr \
    tesseract-ocr-rus \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

# Создаём __init__.py если нет
RUN find app -type d -exec touch {}/__init__.py \;

EXPOSE 8000

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "2"]
