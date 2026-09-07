FROM python:3.11-slim

# libgomp1 for lightgbm
RUN apt-get update && apt-get install -y --no-install-recommends libgomp1 \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY pyproject.toml ./
COPY tradefish ./tradefish
COPY config ./config
COPY scripts ./scripts
RUN pip install --no-cache-dir .

# PYTHONPATH so templates/static resolve from /app, APP_ROOT so data/ lands in the volume
ENV PYTHONPATH=/app APP_ROOT=/app TZ=Asia/Kolkata PYTHONUNBUFFERED=1
EXPOSE 8000
CMD ["uvicorn", "tradefish.web.app:app", "--host", "0.0.0.0", "--port", "8000"]
