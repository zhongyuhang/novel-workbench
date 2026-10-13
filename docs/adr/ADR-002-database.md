# ADR-002：数据库选型

## 状态
已采纳（M0）

## 决策
MVP 使用 **SQLite**（单写入者），SQLAlchemy 2.x + Alembic。

## 迁移触发条件
多用户写入、多后端实例、复杂权限或网络共享盘需求出现时，评估 PostgreSQL。
