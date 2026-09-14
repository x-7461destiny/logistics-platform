# P0-1 消息消费与通知修复

## 消息契约

KafkaService 在收到原始 value 后执行 UTF-8 解码与 JSON 解析，校验结果为
dict，再调用并等待 handler(data)。业务 handler 不接收 ConsumerRecord，也不
重复调用 json.loads。解码放在重试范围内，因此损坏的 JSON 不会绕过失败处理。

每个消费者使用独立实例；服务保存任务与实例集合。启动失败会关闭实例并重连。
应用保存后台任务，退出时取消、等待任务，再关闭 producer 和数据库引擎。
移除了 tracking 包导入时隐式启动、未被使用的批处理任务。

## 消费进度与失败

关闭自动提交，按消费顺序等待处理成功，再只提交该消息所在分区的 offset + 1。
失败采用退避重试，最大间隔 30 秒；日志包含 topic、partition、offset。
永久错误会阻塞该消费者，不跳过消息，需要修正数据或处理器后恢复。

这是至少一次处理：业务成功而提交 offset 失败时仍可能重放。没有实现事务
Outbox、业务幂等、死信队列或离线通知存储；这些属于后续可靠性工作。
此前已经提交的失败消息不会自动重放，本次不重置已有消费组 offset。

## 派单通知

booking processing service → driver_assignments → assignment consumer
→ 共享 Socket.IO server / Redis 原生通知频道 → 在线司机连接。

Socket.IO 使用 AsyncRedisManager；接入与发送统一使用 driver_{id} 房间。
原生 WebSocket 保存连接对象，以 send_json 发送，后台订阅 Redis 频道实现
跨进程转发。原生推送格式为 {"event": "assignment", "data": 原始通知}。
移除订单状态消费者中重复生成派单事件的逻辑。
静态 /ws/drivers 等路由先于 /ws/{driver_id} 注册，避免被动态路由截获。

实时推送不等于司机确认收到：司机离线、网络断开、Redis Pub/Sub 消息丢失时，
仍需后续接单确认、超时重派和离线恢复机制。集成测试验证单后端两种在线连接；
跨实例路由采用 Redis，但尚未做多后端故障注入测试。

## 验证

单元测试（无需启动基础设施）：

```bash
.venv/bin/python -m pytest -q tests/test_p0_messaging.py tests/test_driver_assignment.py
```

集成测试使用真实 PostgreSQL、Kafka、Redis，在容器内启动临时 API，
mock 认证查询为测试司机，验证消息进入缓存、两种连接接收派单和优雅关闭。
不是完整的注册登录或真实订单端到端测试。
运行前停止其他应用消费者，避免旧代码争抢相同消费组的测试消息：

```bash
docker compose stop backend booking_consumer demand_consumer location_consumer
docker compose run --rm --no-deps -v "$PWD:/app" backend python tests/p0_messaging_smoke.py
docker compose up -d --build backend booking_consumer demand_consumer location_consumer
```

测试使用唯一标记，不创建司机或订单数据库记录。测试 Redis 键会清理，
测试 Kafka 事件按 broker 保留策略过期；测试会推进消费组进度，
仅应在开发环境运行。

原有 tests/test_booking_auth.py 的 mock 缺少 commit() 且断言旧响应字段；
其他部分旧测试仍导入不存在的接口。它们不包含在本次通过的测试集合中。
