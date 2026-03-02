FROM python:3.11-slim

WORKDIR /app

# System deps for lxml (used by BeautifulSoup in ecourts source)
RUN apt-get update && apt-get install -y \
    libxml2-dev libxslt-dev gcc curl \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

EXPOSE 8000

CMD ["uvicorn", "api.main:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "2"]
