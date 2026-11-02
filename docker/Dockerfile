FROM ubuntu:24.04 AS base
USER root
SHELL ["/bin/bash", "-c"]
WORKDIR /ragflow
ENV DEBIAN_FRONTEND=noninteractive \
    PATH="/opt/python/bin:${PATH}" \
    PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=/ragflow \
    NLTK_DATA=/usr/local/share/nltk_data \
    TIKA_SERVER_JAR=file:///ragflow/tika-server-standard-3.3.0.jar \
    UV_PYTHON_DOWNLOADS=never UV_HTTP_TIMEOUT=200 UV_HTTP_RETRIES=3 \
    DOTNET_SYSTEM_GLOBALIZATION_INVARIANT=1

# docker.sh fetch/build verifies this host cache before Docker starts.
# SSH tunnel configuration belongs to docker/env/build.env, never the image.
COPY docker/runtime/install-system.sh /tmp/install-system.sh
RUN --mount=type=bind,source=third_partys,target=/third_partys,readonly \
    --mount=type=cache,id=ragflow_apt,target=/var/cache/apt,sharing=locked \
    bash /tmp/install-system.sh /third_partys && rm /tmp/install-system.sh
COPY docker/config/nginx/nginx.conf docker/config/nginx/proxy.conf /etc/nginx/
COPY docker/config/nginx/ragflow.conf.* /etc/nginx/conf.d/

# The optional Go CI model service shares the same verified model cache.
FROM base AS deepdoc
WORKDIR /app
ENV PYTHONPATH=/app
RUN uv venv --python /opt/python/bin/python3.13 /app/.venv && \
    uv pip install --python /app/.venv/bin/python litserve onnxruntime opencv-python-headless numpy pillow pyclipper python-multipart shapely six huggingface_hub
RUN mkdir -p /app/rag/res && cp -a /ragflow/rag/res/deepdoc /app/rag/res/
COPY deepdoc/vision /app/deepdoc/vision
COPY deepdoc/server /app/deepdoc/server
RUN /app/.venv/bin/python /app/deepdoc/server/docker_stubs.py
ENTRYPOINT ["/app/.venv/bin/python", "/app/deepdoc/server/deepdoc_server.py", "--model-dir", "/app/rag/res/deepdoc"]

FROM base AS builder
RUN --mount=type=cache,id=ragflow_apt,target=/var/cache/apt,sharing=locked \
    apt-get -o Acquire::Retries=5 update && \
    apt-get install -y --no-install-recommends build-essential libpython3-dev libicu-dev libgbm-dev
COPY pyproject.toml uv.lock ./
RUN --mount=type=cache,id=ragflow_uv,target=/root/.cache/uv,sharing=locked \
    CC=gcc CXX=g++ AR=ar uv sync --python /opt/python/bin/python3.13 --frozen --no-install-project && \
    .venv/bin/python3 -m ensurepip --upgrade
COPY web/package.json web/package-lock.json web/.npmrc ./web/
RUN --mount=type=cache,id=ragflow_npm,target=/root/.npm,sharing=locked \
    cd web && NODE_OPTIONS=--max-old-space-size=8192 npm ci
RUN --mount=type=bind,source=.git,target=/ragflow/.git \
    git describe --tags --match=v* --first-parent --always > /ragflow/VERSION
COPY web ./web
COPY docs ./docs
RUN --mount=type=cache,id=ragflow_npm,target=/root/.npm,sharing=locked \
    cd web && NODE_OPTIONS=--max-old-space-size=8192 VITE_BUILD_SOURCEMAP=false VITE_MINIFY=esbuild npm run build

FROM base AS runtime
ENV VIRTUAL_ENV=/ragflow/.venv PATH="/ragflow/.venv/bin:${PATH}"
COPY --from=builder /ragflow/.venv /ragflow/.venv
COPY --from=builder /ragflow/VERSION /opt/ragflow-runtime/VERSION
COPY --from=builder /ragflow/VERSION /ragflow/VERSION
COPY docker/runtime /ragflow/docker/runtime
COPY docker/runtime/entrypoint.sh /ragflow/entrypoint.sh
COPY docker/config/service_conf.ci.yaml.template /ragflow/conf/service_conf.yaml.template
COPY bin /ragflow/bin
COPY admin ./admin
COPY api ./api
COPY conf ./conf
COPY deepdoc ./deepdoc
COPY rag ./rag
COPY agent ./agent
COPY mcp ./mcp
COPY common ./common
COPY memory ./memory
COPY tools/scripts ./tools/scripts
COPY pyproject.toml uv.lock ./
COPY --from=builder /ragflow/web/dist /ragflow/web/dist
ENV APP_MODE=prod
LABEL org.ragflow.mode=prod
ENTRYPOINT ["bash", "/ragflow/entrypoint.sh"]
