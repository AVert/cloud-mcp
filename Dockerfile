FROM python:3.13-slim
ENV PYTHONUNBUFFERED=1 SWEB_SPECS_DIR=/app/specs
WORKDIR /app
COPY pyproject.toml README.md LICENSE ./
COPY src ./src
COPY specs ./specs
RUN pip install --no-cache-dir .
RUN useradd -r -u 10001 mcp
USER mcp
ENTRYPOINT ["python", "-m", "sweb_mcp"]
