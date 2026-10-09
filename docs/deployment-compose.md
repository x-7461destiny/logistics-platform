# 单机 Compose 部署准备

生产配置使用 `compose.production.yaml`，镜像由 CI 构建验证。服务器使用宿主机上的 HTTPS 代理将公网 80/443 转发到 `127.0.0.1:8080`。该端口只监听回环地址；数据库、Redis、Kafka 不发布宿主机端口。

## 首次启动

1. 从 `env.production.example` 复制为 `.env.production`，填写随机数据库密码、JWT 密钥、镜像所有者和完整 Git SHA。`DATABASE_URL` 中的密码必须与 `POSTGRES_PASSWORD` 一致。生产密钥只保留在服务器。
2. 使用具有 `read:packages` 权限的凭证在服务器执行 `docker login ghcr.io`，或使用公开可读取的镜像。
3. 启动依赖服务：

   ```bash
   docker compose --env-file .env.production -f compose.production.yaml up -d postgres redis zookeeper kafka
   ```

4. 创建数据库结构：

   ```bash
   docker compose --env-file .env.production -f compose.production.yaml run --rm --no-deps backend python -m alembic upgrade head
   ```

5. 启动应用：

   ```bash
   docker compose --env-file .env.production -f compose.production.yaml up -d
   curl --fail http://127.0.0.1:8080/health/ready
   bash scripts/smoke.sh http://127.0.0.1:8080
   ```

也可以检查容器自身的健康状态：

```bash
docker compose --env-file .env.production -f compose.production.yaml ps
```

## 已有数据库

如果数据库此前由应用启动时 `create_all` 建立，先备份并核对实际表、字段、索引与 `20261009_0001` 迁移完全一致。只有核对后才执行 `alembic stamp 20261009_0001`；未经核对不能直接 stamp，也不能在已有表上直接执行初始 `upgrade`。

## 发布和回滚

每次发布更新 `.env.production` 的 `IMAGE_TAG` 为通过 CI 的 Git SHA，先备份数据库，再执行迁移和 `docker compose pull && docker compose up -d`。应用镜像可以改回上一 Git SHA；数据库迁移需按兼容性策略设计，不能假设镜像回滚会还原数据结构。首次上生产前应实际演练备份恢复和回滚。

## 测试范围

`pytest.ini` 隔离了 8 个引用旧接口或旧车型的测试文件。现有订单、派单、鉴权、前端 API、Kafka 生命周期、用户和健康检查测试仍参与 CI。隔离列表应在重写对应测试后逐项移除。

生产环境通过 `AUTO_CREATE_TABLES=0` 禁止应用启动时自动建表，数据库结构只由 Alembic 管理。开发环境维持原有自动建表行为。
