# RAGFlow 部署入口

本项目当前使用宿主机工程整体挂载到 `/ragflow` 的方式运行。分离部署为 91 应用 + 92 存储；92 同时提供单机应用验证入口，两端应用连接 92 同一套存储。

- [Docker 目录与命令](../docker/README.md)：目录职责、镜像构建、配置生成与启停。
- [完整操作手册](operations.html)：配置迁移、容器内 MySQL/Redis/MinIO/ES 操作、模型维护、备份恢复、现场验证及回退。
- [更新日志](update.md)：按日期记录问题、解决过程和验证结论。
- [任务与 Graph 排查](troubleshooting.md)、[Kibana 查询](kibana-inspection.md)、[局部数据修正](data-storage-and-local-correction.md)：业务专题。

工程目录均为 `/home/cdky/workspace/github/ragflow`。真实凭据只保存在各主机 `docker/env/*.env`；不写入文档或 Git。91 的旧 RAGFlow 存储属于其他工程，不能操作。

```bash
cd /home/cdky/workspace/github/ragflow
# 应用服务器
bash docker/docker.sh status app
bash docker/docker.sh into app
# 已进入容器；以下路径就是宿主机工程挂载
pwd
python /opt/ragflow-ops/inspect_task.py
exit
```

历史补丁已存在于当前工程源码，挂载后直接生效；不再构建只拷贝少数 Python 文件的补丁镜像。完整依赖/前端构建仍可使用 `docker/Dockerfile`，运行环境镜像使用 `docker/Dockerfile.runtime`。
