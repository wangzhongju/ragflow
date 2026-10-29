# 从源码启动后端

默认二次开发使用 [整工程容器挂载](../operations.html#mount)，Python 修改后 `bash docker/docker.sh restart app` 即重新加载。下面是确有需要在宿主机运行后端的流程；不要同时启动同端口的容器应用。

```bash
uv sync --python 3.13 --all-extras
uv run python3 ragflow_deps/download_deps.py
bash docker/docker.sh start storage
source .venv/bin/activate
export PYTHONPATH=$(pwd)
bash docker/runtime/launch_backend_service.sh
```

先根据 [部署手册](../../docker/README.md) 配置 `docker/env/app.env`，其中存储 IP 指向实际存储主机。源码入口加载该文件；宿主机 `conf/service_conf.yaml` 也需设置为相同的连接参数，不要直接使用 CI 示例端口。前端开发遵循 `web/CLAUDE.md`。

Go 编译和测试使用工程根目录 `build.sh`，原生依赖由该脚本配置，详见 [internal/development.md](../../internal/development.md)。CI 多后端矩阵定义单独位于 `docker/ci/`。
