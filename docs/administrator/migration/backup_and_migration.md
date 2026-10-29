# 本工程备份与迁移

应用和存储统一由 `docker/docker.sh` 管理。完整冷备份、在线 MySQL 导出、Elasticsearch 快照、恢复顺序和双应用停写要求见 [操作手册](../../operations.html#backup)。

冷备份前须停止所有连接该存储的应用；现场包括 91 和 92。备份脚本只归档 `ragflow-storage` 的七个数据卷，不删除卷。恢复先在独立目录/独立卷验证，再安排切换，不能直接覆盖在用数据。

```bash
# 两台应用主机分别执行
bash docker/docker.sh stop app
# 92 存储主机执行
APP_STOPPED=1 APP_URLS="http://192.168.88.91:9380 http://192.168.88.92:9380" \
  bash docker/scripts/backup.sh
```

真实配置、SQL、对象及模型注册备份可能包含敏感数据，仅存于权限受限的 `docker/backups/` 或独立备份位置，不提交 Git。91 的其他工程存储不在本手册的操作范围内。
