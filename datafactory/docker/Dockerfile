FROM python:3.13-slim

# The platform's own runtime. It shares nothing with the RAGFlow image: the
# application code is bind-mounted from the repository at /ragflow.
RUN pip install --no-cache-dir \
    "fastapi>=0.115" "uvicorn[standard]>=0.32" "pydantic>=2.9" "pydantic-settings>=2.6" \
    "sqlalchemy[asyncio]>=2.0" "asyncmy>=0.2.10" "aiosqlite>=0.20" "alembic>=1.14" "httpx>=0.27" \
    "jinja2>=3.1" "jsonschema>=4.23" "python-ulid>=3.0" "structlog>=24.4" "pyarrow>=18.0" \
    "datasketch>=1.6" "minio>=7.2" "redis>=5.0"

WORKDIR /ragflow/datafactory/backend
EXPOSE 9390
CMD ["python", "-m", "uvicorn", "datafactory.app.main:create_app", "--factory", "--host", "0.0.0.0", "--port", "9390"]
