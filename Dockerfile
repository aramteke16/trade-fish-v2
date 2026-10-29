FROM python:3.12-slim

WORKDIR /app

ENV DEBIAN_FRONTEND=noninteractive
ENV PYTHONUNBUFFERED=1
ENV TZ=Asia/Kolkata
ENV ASSISTANT_HOST=0.0.0.0
ENV ASSISTANT_PORT=8080

RUN apt-get update \
 && apt-get install -y --no-install-recommends tzdata \
 && ln -snf /usr/share/zoneinfo/$TZ /etc/localtime \
 && echo $TZ > /etc/timezone \
 && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY assistant assistant
COPY research research

# Prices, the actor, and portfolio.db come from the mounted ./data volume.
# .env is mounted beside them. The page, the Friday ticker, and /now share one container.
CMD ["sh", "-c", "python -m assistant ui & ui=$!; python -m assistant schedule & sched=$!; python -m assistant bot & bot=$!; trap 'kill $ui $sched $bot 2>/dev/null' INT TERM; while kill -0 $ui 2>/dev/null && kill -0 $sched 2>/dev/null && kill -0 $bot 2>/dev/null; do sleep 2; done; echo 'a process exited' >&2; kill $ui $sched $bot 2>/dev/null; wait"]
