# 09 部署、备份与恢复

## 1. 部署模式

默认采用单个应用实例，前端静态资源由反向代理或应用静态服务提供，FastAPI 处理 API。Docker Compose 可作为推荐部署方式，但必须提供不使用 Docker 的本地开发方法。

生产数据通过宿主机持久化目录挂载，不存放在容器可随时销毁的可写层。

## 2. 局域网部署要求

- 配置 `APP_ENV=production`。
- 配置强认证凭据；禁止使用示例密码。
- 配置允许的 Host 和 CORS 来源。
- 后端只向反向代理或可信 LAN 暴露必要接口。
- 数据库目录仅服务账号可读写。
- API Key 通过环境变量或受保护的密钥存储机制注入。
- 不开放调试模式和自动重载。
- 记录应用版本、迁移版本和备份时间。

## 3. 环境变量模板

```dotenv
APP_ENV=production
APP_HOST=0.0.0.0
APP_PORT=8000
DATABASE_URL=sqlite:////data/ai_novel_writer.db
APP_AUTH_SECRET=replace-with-a-long-random-secret
ALLOWED_HOSTS=192.168.1.20,localhost
CORS_ORIGINS=http://192.168.1.20
DATA_DIR=/data
LOG_LEVEL=INFO
```

## 4. 备份策略

备份至少包含：SQLite 一致性备份、附件/导出、必要配置、备份时间/应用版本/迁移版本。优先使用一致性备份或停写窗口。每日自动备份，保留日备份与周备份，独立存放，定期恢复演练。

## 5. 恢复步骤

1. 停止应用写入。
2. 选择经过验证的备份。
3. 备份当前待替换数据。
4. 恢复数据库与配套文件。
5. 运行迁移状态检查。
6. 启动并核对作品/章节/版本/设定。
7. 运行关键读写测试。
8. 记录恢复时间和恢复点。

## 6. 更新流程

备份 → 拉新版本 → 看 Release Notes → Alembic migration → 启动 → 健康检查；失败则按预案回滚。

## 7. 不用 Docker 的本地运行

开发和单机试跑不需要 Docker。步骤以仓库根目录的 README「本地开发」为准：后端 `uvicorn app.main:app --reload --host 127.0.0.1 --port 8000`，前端 `npm run dev`。这种绑定只监听本机，未设置 `APP_ACCESS_PASSWORD` 时可以用空口令换会话。

生产或局域网不要使用 `--reload`，也不要把 `APP_HOST` 留在 `127.0.0.1` 的同时又让进程监听 `0.0.0.0`。`APP_HOST` 必须和实际监听地址一致。非回环地址会强制要求口令。

## 8. Compose 启动

在仓库根目录：

```bash
cp .env.example .env
# 编辑 .env：换成真实的 APP_AUTH_SECRET、APP_ACCESS_PASSWORD_HASH、
# APP_SECRET_ENCRYPTION_KEY、ALLOWED_HOSTS、CORS_ORIGINS。
# 不要把示例口令或占位符留在生产配置里。

mkdir -p data
# 数据目录只给运行账号读写。Compose 里的 API 用户是 uid/gid 10001。
# 当前用户没有权限时，给 chown 加上 sudo。
chmod 700 data
chown 10001:10001 data

cd backend
python -m app.cli.hash_password
# 把打印的哈希写入 .env 的 APP_ACCESS_PASSWORD_HASH，并清空 APP_ACCESS_PASSWORD。

cd ..
docker compose --env-file .env -f deploy/compose.yaml config
docker compose --env-file .env -f deploy/compose.yaml up --build -d
```

`deploy/compose.yaml` 把宿主机 `DATA_DIR`（默认 `./data`）挂到容器 `/data`。数据库和 `backups/` 都在这个目录里，不进镜像可写层，也不要提交到 git。Caddy 只反代 API 容器；API 容器同时提供构建好的前端和 `/api`。容器内 uvicorn 不带 `--reload`。

健康检查是容器内的 `GET /api/v1/health`。它不要求登录。`ALLOWED_HOSTS` 要包含 `localhost` 和 `127.0.0.1`，否则探针的 Host 会被拒绝。浏览器使用的局域网主机名也要写进 `ALLOWED_HOSTS`，对应来源写进 `CORS_ORIGINS`。

没有 Docker 时，仍可用上一节的本地进程跑同一套代码。`docker compose config` 只在安装了 Docker Compose 的机器上执行。

## 9. 认证

1. 生成 `APP_AUTH_SECRET`：`python -c "import secrets; print(secrets.token_urlsafe(32))"`。
2. 生成口令哈希：在 `backend` 目录运行 `python -m app.cli.hash_password`，按提示输入至少 12 位、不是常见口令或纯数字的口令。命令不会把口令打到参数或标准输出。
3. 生产环境把哈希放到 `APP_ACCESS_PASSWORD_HASH`，`APP_ACCESS_PASSWORD` 留空。
4. 打开 `http://<局域网地址>:<PUBLISH_PORT>`。页面出现「访问口令」。口令正确后进入作品库。
5. 不带 `Authorization: Bearer` 访问 `/api/v1/novels` 或 `/api/v1/admin/backups` 应得到 401。

只在本机开发、且 `APP_HOST=127.0.0.1` 时，可以不设置口令。这不适用于 `APP_ENV=production`，也不适用于监听局域网地址。

## 10. 备份与恢复演练

应用在运行时就可以做一致性备份。恢复前先停写。

```bash
# 已登录的会话。把 TOKEN 换成 POST /api/v1/auth/session 返回的 access_token。
curl -sS -X POST http://127.0.0.1:8080/api/v1/admin/backups \
  -H "Authorization: Bearer $TOKEN"
curl -sS http://127.0.0.1:8080/api/v1/admin/backups \
  -H "Authorization: Bearer $TOKEN"
```

备份目录在宿主机的 `$DATA_DIR/backups/<id>/`，里面有 `manifest.json`（应用版本、迁移版本、时间）和 `database.sqlite`。不要把这些文件提交到 git。

恢复到一个新文件，确认无误后再替换正式库：

```bash
# 先停止 Compose 或本地 uvicorn，避免恢复过程中继续写入。
docker compose --env-file .env -f deploy/compose.yaml stop

cd backend
python -m app.cli.restore \
  --backup ../data/backups/<id> \
  --database ../data/restore-drill.db

# 核对迁移版本后，把演练库换上正式文件名前先留一份当前库。
# 目标已存在时，CLI 默认拒绝。确认后才使用 --force，它会把现有文件改名而不是直接删除。
python -m app.cli.restore \
  --backup ../data/backups/<id> \
  --database ../data/ai_novel_writer.db \
  --force

docker compose --env-file .env -f deploy/compose.yaml start
```

演练时核对：作品列表、章节正文、章节版本、设定实体、模型配置名称都能读到。模型配置接口仍然不返回 API Key 明文。自动化覆盖见 T-017。

## 11. 手工局域网步骤

自动化测试不代替另一台设备上的浏览器：

1. 按第 8 节启动，确认 `docker compose ps` 里 api 为 healthy。
2. 在另一台接入同一局域网的设备上打开 `http://<服务器局域网地址>:8080`。
3. 未登录时作品库不会出现；输入口令后可以打开作品。
4. 在该设备上做一次备份，再在服务器上按第 10 节恢复到新文件并抽查作品。

这一步依赖现场网络，不放进 `./scripts/check.sh`。
