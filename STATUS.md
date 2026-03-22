# CTF Pusher 架构状态报告

## 1. 核心路由 (Routing)
插件基于 `AstrBot` 星系事件总线，采用 `Start/Filter` 机制分发指令：
- **`cmd_ctftime` (`/ctftime`)**: 
  - 职责：获取全球高质量 CTF 赛事。
  - 实现：异步调用 `EventQueryService` -> `CTFTimeSource`。
- **`cmd_nssctf` (`/ctf [tag]`)**: 
  - 职责：NSSCTF 题库随机刷题。
  - 实现：直接请求 NSSCTF API (Mock/Real)，支持 Tag 过滤与参数注入。
- **订阅系统 (`/ctf订阅*`)**: 
  - 职责：管理群组/私聊的赛事提醒。
  - 实现：`SubscriptionService` 调度器。

## 2. 数据层 (Data Layer)
- **数据源**:
  - **CTFTime**: 实时 RSS/API 抓取，内存级缓存。
  - **NSSCTF**: 实时 REST API 请求。
- **持久化 (Persistence)**:
  - **Database**: SQLite (`data/data.db`)。
  - **ORM**: SQLAlchemy (Sync) 用于定义模型 (`SubscriptionModel`)。
  - **Schema**: 存储 `watcher_id`, `event_id`, `remind_status` 等订阅关系。

## 3. 定时任务 (Scheduling)
- **引擎**: `APScheduler` (AsyncIOScheduler)。
- **策略**: 
  - 每 10 分钟 (`scan_interval_minutes`) 扫描一次数据库中已订阅的赛事。
  - 在赛前 `120分钟` 和 `15分钟` 自动推送提醒消息。

## 4. 待办事项 (TODO)
- [ ] 接入真实的 NSSCTF 鉴权 API (目前为模拟)。
- [ ] 支持更多 CTF 平台 (如 Buuoj)。
- [ ] 增加图片渲染模式 (T2I)。
