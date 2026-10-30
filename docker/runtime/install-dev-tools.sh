#!/usr/bin/env bash
# Image build only: tools and a Python interpreter accessible to non-root users.
set -euo pipefail
export DEBIAN_FRONTEND=noninteractive
if [[ ${NEED_MIRROR:-0} == 1 ]]; then
  sed -i 's|http://archive.ubuntu.com/ubuntu|http://mirrors.aliyun.com/ubuntu|g; s|http://security.ubuntu.com/ubuntu|http://mirrors.aliyun.com/ubuntu|g' /etc/apt/sources.list.d/ubuntu.sources
fi
apt-get -o Acquire::Retries=3 update
apt-get install -y --no-install-recommends sudo vim bash-completion less git curl wget \
  unzip procps iproute2 iputils-ping ca-certificates
# Keep the package index: this is an interactive development environment, and
# sudo apt-get install must work immediately after entering a new container.
apt-get clean

# uv's bundled Python was under /root; do not open /root to other users.
if [[ -d /root/.local/share/uv/python ]]; then
  mkdir -p /opt/uv
  mv /root/.local/share/uv/python /opt/uv/python
  ln -s /opt/uv/python /root/.local/share/uv/python
  python_target=$(readlink -f /ragflow/.venv/bin/python)
  ln -sfn "$python_target" /ragflow/.venv/bin/python
fi
if [[ -d /root/nltk_data ]]; then
  mv /root/nltk_data /usr/local/share/nltk_data
  ln -s /usr/local/share/nltk_data /root/nltk_data
fi
