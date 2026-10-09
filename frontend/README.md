# 物流联调工作台

独立的 React + TypeScript + Vite 前端，使用真实后端账号和数据。

## 启动

```bash
# 仓库根目录。项目的 .env 使用 postgres、redis、kafka 等 Docker 服务名，
# 因此后端也应在 Compose 网络内启动。
docker compose up --build backend

# 另一个终端
cd frontend
npm ci
npm run dev
```

访问 Vite 输出的地址（默认 http://localhost:5173）。必须启动 `app.main:app_asgi`，才能使用 `/socket.io`；单独启动 `app.main:app` 仅提供 HTTP 和原生 WebSocket 路由。

如果要直接在宿主机运行 `.venv/bin/uvicorn`，需要先安装依赖，并把 `.env` 中的数据库、Redis 和 Kafka 地址改为宿主机可访问的地址；当前 Compose 配置默认不暴露 PostgreSQL 端口，因此推荐使用上面的 Compose 命令。

默认代理 `/api` 和 `/socket.io` 到 `http://127.0.0.1:8000`。需要修改时，将 `.env.example` 复制为 `.env.local` 并设置 `BACKEND_URL`，重启 Vite。构建后部署需要反向代理这两个路径（含 WebSocket Upgrade）；`vite preview` 仅用于静态预览。

```bash
npm run build
npm test
```

## 功能与联调顺序

1. 可在登录页进入注册页，创建普通用户或司机账号（司机需选车型），成功后返回登录并预填邮箱。管理员不支持自助注册，需使用已有管理员账号。管理员走 `/auth/token`，由 `/auth/me` 校验真实角色。司机走 `/auth/driver-token`。
2. 司机上线并上报当前位置；定位按钮只填写坐标，点击「上报位置」后才发送。浏览器定位需要安全上下文及定位授权，localhost 可用，也可手动输入。
3. 用户创建即时或预约订单。预约输入按北京时间（UTC+8）发送。列表展示自己创建的订单；司机查看分配订单；管理员查看全部订单。每页 20 条，自动同步间隔 15 秒。
4. 选择订单或按 ID 查询详情，根据角色执行取消、出发、取货、送达、完成；已分配但待确认时也可确认。状态更新携带 `expected_version`；409 冲突时重新读取订单后再操作。
5. 查看调试面板的 JWT claims、HTTP 错误与 Socket.IO 收发消息（保留最近 200 条）。JWT 原始令牌不显示，当前标签页通过 sessionStorage 恢复登录，退出即清除。

推荐用户与司机在不同浏览器窗口/独立标签页登录。司机上下线表示数据库中的可接单状态，不等同于 WebSocket 是否连接。有进行中订单时不能主动上线抢新单；取消或完成订单后，现有后端逻辑会恢复司机可接单状态。

## 补齐的后端契约

- `GET /api/v1/bookings?offset=0&limit=20&active_only=false`：按认证身份过滤订单，返回与详情一致的结构。
- `PATCH /api/v1/drivers/me/availability`：司机修改自己的 `is_available`，数据库行锁保护，有未结束订单时禁止上线。
- Socket.IO `auth: { token }`：浏览器通过连接认证载荷传递 JWT；继续兼容 Authorization 请求头。
- Socket.IO `update_location`：校验坐标和本人司机 ID，读取最新接单状态，上报成功返回 `location_updated`。

订单详情以 HTTP 持久化状态为准。现有后端未向浏览器推送每一种状态变更，所以页面同时使用轮询；Socket.IO 断开不阻止 HTTP 操作。页面不提供地图、支付或管理 CRUD。
