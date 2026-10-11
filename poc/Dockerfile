FROM python:3.12-slim
WORKDIR /app
COPY poc/requirements.txt /app/requirements.txt
RUN --mount=type=secret,id=proxy_ca \
    if [ -f /run/secrets/proxy_ca ]; then export PIP_CERT=/run/secrets/proxy_ca; fi; \
    pip install --no-cache-dir -r requirements.txt
COPY poc /app/poc
COPY shared /app/shared
COPY dist /app/dist
WORKDIR /app/poc
ENV UI_DIR=/app/dist TELEMETRY_DIR=/app/telemetry PYTHONUNBUFFERED=1
CMD ["uvicorn", "app:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "1", "--no-access-log"]
