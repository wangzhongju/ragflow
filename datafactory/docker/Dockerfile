FROM python:3.13-slim-bookworm

# The platform's own runtime. It shares nothing with the RAGFlow image: the
# application code is bind-mounted from the repository at /ragflow.
COPY backend/pyproject.toml /tmp/datafactory-pyproject.toml
RUN python -c "import subprocess, sys, tomllib; deps = tomllib.load(open('/tmp/datafactory-pyproject.toml', 'rb'))['project']['dependencies']; subprocess.check_call([sys.executable, '-m', 'pip', 'install', '--no-cache-dir', *deps])"

WORKDIR /ragflow/datafactory/backend
EXPOSE 9390
CMD ["python", "-m", "uvicorn", "datafactory.app.main:create_app", "--factory", "--host", "0.0.0.0", "--port", "9390"]
