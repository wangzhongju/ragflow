FROM python:3.11-slim-bookworm


COPY --from=ghcr.io/astral-sh/uv:0.7.5 /uv /uvx /bin/
ENV MPLBACKEND=Agg
ENV MPLCONFIGDIR=/tmp/matplotlib
ENV MATPLOTLIBRC=/usr/local/etc/matplotlibrc

COPY requirements.txt .
COPY matplotlibrc /usr/local/etc/matplotlibrc

RUN apt-get update && \
    apt-get install -y --no-install-recommends curl gcc && \
    mkdir -p /tmp/matplotlib && \
    uv pip install --system -r requirements.txt && \
    rm -rf /var/lib/apt/lists/*

WORKDIR /workspace

CMD ["sleep", "infinity"]