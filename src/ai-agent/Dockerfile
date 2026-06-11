FROM python:3.11-slim AS builder

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir --target=/app/deps -r requirements.txt

FROM python:3.11-slim

WORKDIR /app

RUN addgroup --system agent && adduser --system --group agent

COPY --from=builder /app/deps /app/deps
COPY main.py k8s_client.py ./

ENV PYTHONPATH=/app/deps
ENV PYTHONUNBUFFERED=1

USER agent

EXPOSE 8000

CMD ["python", "-m", "uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"]
