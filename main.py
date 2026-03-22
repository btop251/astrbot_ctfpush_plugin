"""
CTF Pusher 插件主入口。

该文件作为 AstrBot 插件唯一注册入口。
"""

import os
import sys
import asyncio
import re
import random
import aiohttp
import json

from astrbot.api import logger
from astrbot.api.event import filter, AstrMessageEvent
from astrbot.api.star import Context, Star, register

plugin_dir = os.path.dirname(__file__)
if plugin_dir not in sys.path:
    # Append instead of prepend to avoid affecting global import resolution
    # for other plugins.
    sys.path.append(plugin_dir)

from ctf_plugin.config_manager import ConfigManager
from ctf_plugin.data_sources import CTFTimeSource, EventQueryService
from ctf_plugin.db.sqlite import SQLiteManager
from ctf_plugin.db.repository import CTFRepository
from ctf_plugin.services.subscription import SubscriptionService
from ctf_plugin.utils import (
    build_event_text,
    extract_command_arg,
    extract_sender,
    match_tag,
    source_mark,
    to_bj_text,
)


@register("ctf_pusher", "YourName", "CTFTime 赛事检索与订阅提醒插件", "3.2.0")
class CTFPusherPlugin(Star):
    """路由层：仅负责指令接收、业务编排与响应拼装。"""

    def __init__(self, context: Context):
        super().__init__(context)
        base_dir = os.path.dirname(__file__)

        self.config_manager = ConfigManager(base_dir)
        self.config = self.config_manager.load()

        self.ctftime_source = CTFTimeSource(self.config)
        self.query_service = EventQueryService(self.ctftime_source)

        db_path = os.path.join(base_dir, "data", "data.db")
        self.sql_manager = SQLiteManager(db_path)
        self.sql_manager.init_db()
        self.repository = CTFRepository(self.sql_manager)
        
        self.scheduler_manager = SubscriptionService(
            context=self.context,
            repository=self.repository,
            scan_interval_minutes=int(self.config.get("subscription", {}).get("scan_interval_minutes", 10)),
            remind_windows=self.config.get("subscription", {}).get("remind_windows_minutes", [120, 15]),
        )
        # 缓存每个会话最近一次查询展示的赛事，用于按序号订阅
        self._last_query_events: dict[str, list[dict]] = {}

    @staticmethod
    def _subscriber_key(subscriber: dict[str, str]) -> str:
        return f"{subscriber.get('type', '')}:{subscriber.get('target_id', '')}:{subscriber.get('at_user_id', '')}"

    def _save_last_query_events(self, subscriber: dict[str, str], events: list[dict], limit: int = 6):
        key = self._subscriber_key(subscriber)
        self._last_query_events[key] = events[:limit]

    def _resolve_subscribe_target(self, subscriber: dict[str, str], raw_arg: str) -> tuple[str, str]:
        """
        解析订阅参数：支持赛事ID或最近一次查询结果中的序号。

        Returns:
            (event_id, mode)
            mode 为 "index" 或 "id"
        """
        arg = str(raw_arg).strip()
        if not arg:
            return "", "id"

        if arg.isdigit():
            key = self._subscriber_key(subscriber)
            cached = self._last_query_events.get(key, [])
            idx = int(arg)
            if 1 <= idx <= len(cached):
                hit = cached[idx - 1]
                return str(hit.get("id", "")).strip(), "index"

        return arg, "id"

    @staticmethod
    def _normalize_subscribe_arg(raw_arg: str, command_name: str = "ctf订阅") -> str:
        """对订阅参数做最后归一化，避免把命令前缀误当作赛事ID。"""
        text = str(raw_arg or "").replace("\u3000", " ").strip()
        if not text:
            return ""

        escaped = re.escape(command_name)
        text = re.sub(rf"^/?{escaped}\s+", "", text, flags=re.IGNORECASE).strip()
        return text

    @staticmethod
    def _fallback_extract_command_arg(event: AstrMessageEvent, command_name: str) -> str:
        """
        在框架已剥离命令前缀时兜底提取参数。
        """
        cmd_with_slash = f"/{command_name}".strip().lower()
        cmd_without_slash = str(command_name).strip().lower()
        candidates = []
        for attr in ("message_str", "raw_message", "message"):
            val = getattr(event, attr, None)
            if isinstance(val, str):
                candidates.append(val)

        message_obj = getattr(event, "message_obj", None)
        message_obj_text = getattr(message_obj, "text", None)
        if isinstance(message_obj_text, str):
            candidates.append(message_obj_text)

        for text in candidates:
            normalized = text.replace("\u3000", " ").strip()
            if not normalized:
                continue

            lower = normalized.lower()
            if lower.startswith(cmd_with_slash):
                return normalized[len(cmd_with_slash):].strip()

            if lower.startswith(cmd_without_slash):
                return normalized[len(cmd_without_slash):].strip()

            if not normalized.startswith("/"):
                return normalized

        return ""

    async def initialize(self):
        await self.scheduler_manager.start()
        logger.info("[CTF Pusher] 插件架构升级版已加载 (v3.2)。")

    # -----------------------------------------------------------
    # NSSCTF 刷题指令 /ctf
    # -----------------------------------------------------------
    
    @filter.command("ctf")
    async def cmd_nssctf(self, event: AstrMessageEvent, arg_tag: str = ""):
        """NSSCTF 随机刷题：/ctf [tag]"""
        # 1. 优先使用 AstrBot 原生参数注入
        tag = arg_tag.strip()

        # 2. 如果原生注入为空，尝试使用工具函数
        if not tag:
            tag = extract_command_arg(event, "ctf").strip()

        # 3. 终极兜底方案，使用本类内置的方法
        if not tag:
            tag = self._fallback_extract_command_arg(event, "ctf").strip()
            
        # 提示用户
        hint = f"「{tag}」" if tag else ""
        yield event.plain_result(f"🔍 正在从 NSSCTF 题库中挖掘{hint}题目，请稍候...")
        
        problem = await self.fetch_nssctf_problem(tag)
        
        if not problem:
            yield event.plain_result("😵‍💫 糟糕，题目捞取失败！可能是 NSSCTF 接口波动或没有找到该类型的题目。")
            return
            
        msg = self.build_nssctf_msg(problem)
        yield event.plain_result(msg)

    async def fetch_nssctf_problem(self, tag: str = "") -> dict | None:
        """
        异步从 NSSCTF 获取题目。
        """
        # =========================================================================
        # ⚠️ 注意：此处 URL 为示例占位符。
        # 如果真实 API 路径不同，请替换为抓包获取的真实 URL。
        # 例如：https://www.nssctf.cn/api/v1/problems/random
        # =========================================================================
        api_url = "https://www.nssctf.cn/api/v1/problems/random_mock" 
        
        # 模拟请求参数，具体根据真实 API 调整
        params = {}
        if tag:
            params["tags"] = tag
            
        # 模拟 HTTP 请求
        # 由于我们没有真实的 NSSCTF 公开 API 文档，这里模拟一个请求过程，需配合真实接口修改。
        
        try:
            # 真实场景下应取消下方注释并使用真实 URL
            # async with aiohttp.ClientSession() as session:
            #     async with session.get(api_url, params=params, timeout=10) as resp:
            #         if resp.status == 200:
            #             data = await resp.json()
            #             # 根据真实返回结构解析...
            #             return data.get("data")
            #         else:
            #             logger.error(f"[NSSCTF] Request failed: {resp.status}")
            #             return None
            
            # --- 模拟网络延迟 ---
            await asyncio.sleep(1.5)
            
            # --- 模拟返回数据 (Mock) ---
            # 随机生成一些示例题目数据用于展示
            mock_tags = ["Web", "Pwn", "Misc", "Crypto", "Reverse"]
            chosen_tag = tag if tag else random.choice(mock_tags)
            
            return {
                "title": f"NSSRound#{random.randint(10, 99)} {chosen_tag}_Challenge",
                "tag": chosen_tag,
                "difficulty": random.choice(["入门", "简单", "中等", "困难", "噩梦"]),
                "score": random.randint(100, 500),
                "solved": random.randint(5, 200),
                "link": f"https://www.nssctf.cn/problem/{random.randint(1000, 9999)}"
            }
                
        except Exception as e:
            logger.error(f"[NSSCTF] Error fetching problem: {e}")
            return None

    def build_nssctf_msg(self, problem: dict) -> str:
        """构建 NSSCTF 题目展示消息"""
        title = problem.get("title", "未知题目")
        tag = problem.get("tag", "General")
        difficulty = problem.get("difficulty", "未知")
        link = problem.get("link", "https://www.nssctf.cn/problem_list")
        
        # 尝试获取分数或解出人数
        score_info = f"{difficulty}" 
        if "score" in problem:
            score_info += f" ({problem['score']} pts)"
            
        return (
            "🎯 【NSSCTF 随机跳题】\n"
            "━━━━━━━━━━━━━━\n"
            f"🏷️ 方向: {tag}\n"
            f"📌 题目: {title}\n"
            f"🌟 难度: {score_info}\n"
            f"🔗 链接: {link}\n"
            "━━━━━━━━━━━━━━\n"
            "💡 快去开启动态靶机尝试拿下 flag 吧！"
        )

    # -----------------------------------------------------------
    # 原有 CTFTime 赛事指令 (仅保留 /ctftime)
    # -----------------------------------------------------------

    @filter.command("ctftime")
    async def cmd_ctftime(self, event: AstrMessageEvent):
        """精准定向查询：/ctftime"""
        subscriber = extract_sender(event)
        yield event.plain_result("🌐 正在拉取 CTFTime 高质量国际赛事...")
        events = await self.query_service.fetch_ctftime_only(days_ahead=14)

        if not events:
            yield event.plain_result("📭 CTFTime 近期暂无符合阈值的赛事，或网络暂不可用。")
            return

        events = sorted(events, key=lambda x: str(x.get("start_time", "")))
        self._save_last_query_events(subscriber, events, limit=6)

        yield event.plain_result(f"🌐 CTFTime 命中 {len(events)} 场，展示前 6 场（可用 /ctf订阅 序号 订阅）：")
        for idx, item in enumerate(events[:6], 1):
            msg = f"【序号 {idx}】\n" + build_event_text(item) + f"\n📊 Weight: {item.get('weight', 0)}"
            yield event.plain_result(msg)
            if idx < min(5, len(events) - 1):
                await asyncio.sleep(0.6)

    # -----------------------------------------------------------
    # 订阅管理指令 (逻辑保持不变)
    # -----------------------------------------------------------

    @filter.command("ctf订阅")
    async def cmd_subscribe(self, event: AstrMessageEvent):
        """赛事订阅：/ctf订阅 [赛事ID或序号]"""
        subscriber = extract_sender(event)
        raw_arg = extract_command_arg(event, "ctf订阅").strip()
        if not raw_arg:
            raw_arg = self._fallback_extract_command_arg(event, "ctf订阅")
        raw_arg = self._normalize_subscribe_arg(raw_arg, "ctf订阅")
        event_id, mode = self._resolve_subscribe_target(subscriber, raw_arg)
        if not event_id:
            yield event.plain_result("❗ 用法: /ctf订阅 [赛事ID或序号]\n提示: 先执行 /ctftime 再按序号订阅")
            return

        if mode == "index":
            yield event.plain_result(f"🧭 已按序号 {raw_arg} 解析到赛事ID={event_id}，正在查找...")
        else:
            yield event.plain_result(f"🧭 正在查找赛事ID={event_id} ...")
        hit = await self.query_service.find_event_by_id(event_id, days_ahead=45)
        if not hit:
            yield event.plain_result("❌ 未找到该赛事ID（可能已过期、被过滤或来源暂不可达）。")
            return

        ok, msg = await self.scheduler_manager.subscribe(hit, subscriber)
        if not ok:
            yield event.plain_result(f"❌ 订阅失败: {msg}")
            return

        yield event.plain_result(
            "✅ 订阅成功\n"
            f"赛事: {hit.get('title')}\n"
            f"来源: {source_mark(str(hit.get('source', '')))}\n"
            f"开赛时间(UTC+8): {to_bj_text(str(hit.get('start_time', '')))}\n"
            "将在开赛前 2 小时和 15 分钟提醒你。"
        )

    @filter.command("ctf退订")
    async def cmd_unsubscribe(self, event: AstrMessageEvent):
        """取消订阅：/ctf退订 [赛事ID]"""
        event_id = extract_command_arg(event, "ctf退订").strip()
        if not event_id:
            event_id = self._fallback_extract_command_arg(event, "ctf退订")
        event_id = self._normalize_subscribe_arg(event_id, "ctf退订")

        if not event_id:
            yield event.plain_result("❗ 用法: /ctf退订 [赛事ID]")
            return

        ok, msg = await self.scheduler_manager.unsubscribe_by_event_id(event_id, extract_sender(event))
        if not ok:
            yield event.plain_result(f"❌ 退订失败: {msg}")
            return

        yield event.plain_result(f"✅ 退订成功: {msg}")

    @filter.command("ctf订阅列表")
    async def cmd_subscription_list(self, event: AstrMessageEvent):
        """查看当前会话订阅：/ctf订阅列表"""
        items = await self.scheduler_manager.list_subscriptions(extract_sender(event))
        if not items:
            yield event.plain_result("📭 当前没有订阅记录。")
            return

        lines = [f"📌 当前共 {len(items)} 条订阅："]
        for idx, item in enumerate(items[:20], 1):
            lines.append(
                f"{idx}. [{item.get('event_id', 'N/A')}] {item.get('title', '未知赛事')}"
                f" | {to_bj_text(str(item.get('start_time', '')))}"
            )

        if len(items) > 20:
            lines.append(f"... 其余 {len(items) - 20} 条未展示")

        yield event.plain_result("\n".join(lines))

    async def terminate(self):
        await self.scheduler_manager.shutdown()

__all__ = ["CTFPusherPlugin"]