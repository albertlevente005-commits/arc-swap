# ARC Swap webapp - eles futtatas (MetaMask-mod + opcionalis Circle-mod)
FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .
RUN adduser --disabled-password --gecos "" app && mkdir -p /app/adat && chown -R app /app
USER app

# .env helyett kornyezeti valtozokkal is konfiguralhato (ARC_HALOZAT, VALTO_ADMIN_TOKEN, ...)
ENV APP_HOST=0.0.0.0 APP_PORT=8060
EXPOSE 8060
HEALTHCHECK --interval=30s --timeout=10s CMD python -c "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8060/healthz', timeout=8).status==200 else 1)"
CMD ["python", "valto_app.py"]
