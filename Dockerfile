FROM python:3.12-slim
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
WORKDIR /app
RUN useradd -m trader
COPY pyproject.toml README.md LICENSE NOTICE SOUL.md ./
COPY hermes_trader ./hermes_trader
RUN pip install --no-cache-dir ".[crypto]" && mkdir -p /app/data && chown -R trader /app
USER trader
VOLUME ["/app/data"]
ENTRYPOINT ["hermes-trader"]
CMD ["run"]
