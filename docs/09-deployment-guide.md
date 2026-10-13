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
