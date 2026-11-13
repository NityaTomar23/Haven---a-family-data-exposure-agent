FROM python:3.11-slim

WORKDIR /app

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    HAVEN_HOST=0.0.0.0 \
    HAVEN_PORT=8000 \
    HAVEN_PROVIDER_MODE=auto \
    HAVEN_SCAN_RATE_LIMIT=10

COPY pyproject.toml ./
RUN pip install --no-cache-dir \
    "fastapi>=0.115.0" \
    "uvicorn[standard]>=0.30.0" \
    "jinja2>=3.1.4" \
    "httpx>=0.27.0" \
    "openai>=1.50.0" \
    "python-dotenv>=1.0.1" \
    "tavily-python>=0.7.0" \
    "pydantic>=2.0.0" \
    "pyyaml>=6.0.0"

COPY src ./src
COPY scripts ./scripts
COPY web ./web
COPY policy ./policy
COPY LICENSE README.md ./

EXPOSE 8000

CMD ["python", "scripts/serve.py"]

