#!/usr/bin/env bash
# Shared build-time installation for Dockerfile and Dockerfile.dev.
set -euo pipefail
export DEBIAN_FRONTEND=noninteractive
cache=${1:?third_partys mount required}
rm -f /etc/apt/apt.conf.d/docker-clean
echo 'Binary::apt::APT::Keep-Downloaded-Packages "true";' > /etc/apt/apt.conf.d/keep-cache
chmod 1777 /tmp
apt-get -o Acquire::Retries=5 update
apt-get install -y --no-install-recommends ca-certificates gnupg xz-utils \
  libglib2.0-0 libglx-mesa0 libgl1 pkg-config libgdiplus default-jdk \
  libatk-bridge2.0-0 libgtk-4-1 libnss3 xdg-utils libjemalloc-dev \
  unzip curl wget git vim less sudo bash-completion procps iproute2 iputils-ping \
  ghostscript pandoc lmodern texlive texlive-latex-extra texlive-xetex \
  texlive-lang-chinese fonts-freefont-ttf fonts-noto-cjk postgresql-client

mkdir -p /etc/apt/keyrings
gpg --dearmor -o /etc/apt/keyrings/nginx.gpg "$cache/keys/nginx_signing.key"
gpg --dearmor -o /etc/apt/keyrings/microsoft.gpg "$cache/keys/microsoft.asc"
echo 'deb [signed-by=/etc/apt/keyrings/nginx.gpg] https://nginx.org/packages/mainline/ubuntu/ noble nginx' > /etc/apt/sources.list.d/nginx.list
echo 'deb [arch=amd64 signed-by=/etc/apt/keyrings/microsoft.gpg] https://packages.microsoft.com/ubuntu/22.04/prod jammy main' > /etc/apt/sources.list.d/mssql-release.list
apt-get -o Acquire::Retries=5 update
ACCEPT_EULA=Y apt-get install -y --no-install-recommends nginx=1.31.3-1~noble unixodbc-dev msodbcsql17
apt-mark hold nginx
dpkg -i "$cache/packages/libssl1.1.deb"

mkdir -p /opt/python /usr/share/infinity/resource /opt/chrome /opt/ragflow-runtime /ragflow/rag/res/deepdoc
tar -xzf "$cache/archives/python/cpython-linux-x64.tar.gz" --strip-components=1 -C /opt/python
tar -xJf "$cache/archives/node/node-linux-x64.tar.xz" --strip-components=1 -C /usr/local
tar -xzf "$cache/archives/uv/uv-linux-x64.tar.gz" --strip-components=1 -C /usr/local/bin
tar -xzf "$cache/archives/resource/resource.tar.gz" --strip-components=1 -C /usr/share/infinity/resource
unzip -q "$cache/archives/chrome/chrome-linux64.zip" -d /tmp
cp -a /tmp/chrome-linux64/. /opt/chrome/
rm -rf /tmp/chrome-linux64
ln -s /opt/chrome/chrome /usr/local/bin/chrome
unzip -qj "$cache/archives/chrome/chromedriver-linux64.zip" chromedriver-linux64/chromedriver -d /usr/local/bin
mkdir -p /root/.cache/stagehand/lib/go_3.21.0
install -m 0755 "$cache/stagehand/stagehand-server-v3-linux-x64" /root/.cache/stagehand/lib/go_3.21.0/
cp -a "$cache/nltk_data" /usr/local/share/nltk_data
cp -a "$cache/models/InfiniFlow/deepdoc/." /ragflow/rag/res/deepdoc/
cp -a "$cache/models/InfiniFlow/text_concat_xgb_v1.0/." /ragflow/rag/res/deepdoc/
cp "$cache/tika/"* /opt/ragflow-runtime/
cp "$cache/tiktoken/cl100k_base.tiktoken" /opt/ragflow-runtime/9b5ad71b2ce5302211f9c61530b329a4922fc6a4
cp /opt/ragflow-runtime/* /ragflow/
# Keep apt indexes so users can immediately sudo apt-get install packages.
mkdir -p /etc/nginx/conf.d /var/log/nginx
rm -f /etc/nginx/sites-enabled/default
