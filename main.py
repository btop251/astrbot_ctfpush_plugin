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
    extract_command_arg,
    extract_sender,
    match_tag,
    source_mark,
    to_bj_text,
)


@register("ctf_pusher", "YourName", "CTFTime 赛事检索与订阅提醒插件", "3.2.0")
class CTFPusherPlugin(Star):
    """路由层：仅负责指令接收、业务编排与响应拼装。"""

    NSSCTF_BASE_URL = "https://www.nssctf.cn"
    NSSCTF_PROBLEM_DETAIL_API = NSSCTF_BASE_URL + "/api/problem/v2/{pid}/"

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

        # 仅推送“活题”：通过详情接口返回 code/data 判活。
        # 若命中死题或标签不匹配，则继续捞取直到命中为止。
        problem = None
        while True:
            candidate = await self.fetch_nssctf_problem(tag)
            if not candidate:
                await asyncio.sleep(0.2)
                continue

            alive, merged = await self._verify_and_enrich_nssctf_problem(candidate)
            if not alive:
                await asyncio.sleep(0.2)
                continue

            # 用户指定方向时，要求真实题目标签匹配。
            if tag and not self._is_problem_tag_match(merged, tag):
                await asyncio.sleep(0.2)
                continue

            problem = merged
            break
            
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
                "link": f"https://www.nssctf.cn/problem/{random.randint(1000, 9999)}",
                "description": random.choice(
                    [
                        "给定登录接口，请分析参数可控点并绕过鉴权。",
                        "从混淆脚本中还原关键逻辑并拿到 flag。",
                        "附件含流量包，请定位异常协议字段并复原密文。",
                    ]
                ),
            }
                
        except Exception as e:
            logger.error(f"[NSSCTF] Error fetching problem: {e}")
            return None

    @staticmethod
    def _extract_problem_id(problem: dict) -> str:
        """从题目对象中提取 pid，兼容多种字段。"""
        for key in ("pid", "id", "problem_id"):
            value = str(problem.get(key, "") or "").strip()
            if value.isdigit():
                return value

        link = str(problem.get("link", "") or "")
        m = re.search(r"/problem/(\d+)", link)
        if m:
            return m.group(1)

        return ""

    @staticmethod
    def _extract_nssctf_description(problem: dict) -> str:
        """兼容不同字段名提取题目描述。"""
        for key in ("description", "desc", "content", "problem_description"):
            value = str(problem.get(key, "") or "").strip()
            if value:
                return value
        return ""

    async def _verify_and_enrich_nssctf_problem(self, problem: dict) -> tuple[bool, dict]:
        """
        通过 /api/problem/v2/{pid}/ 判活并回填详情。

        判活规则：HTTP 200 且 JSON 中 code == 200 且 data 非空对象。
        """
        pid = self._extract_problem_id(problem)
        if not pid:
            return False, problem

        api_url = self.NSSCTF_PROBLEM_DETAIL_API.format(pid=pid)
        headers = {
            "User-Agent": "AstrBot/CTFPlugin",
            "Accept": "application/json",
            "Referer": self.NSSCTF_BASE_URL,
        }

        try:
            timeout = aiohttp.ClientTimeout(total=8)
            async with aiohttp.ClientSession(timeout=timeout) as session:
                async with session.get(api_url, headers=headers) as resp:
                    if resp.status != 200:
                        return False, problem
                    payload = await resp.json(content_type=None)
        except Exception as e:
            logger.warning(f"[NSSCTF] verify failed pid={pid}: {e}")
            return False, problem

        code = int(payload.get("code", -1)) if isinstance(payload, dict) else -1
        data = payload.get("data", {}) if isinstance(payload, dict) else {}
        if code != 200 or not isinstance(data, dict) or not data:
            return False, problem

        merged = dict(problem)
        merged["pid"] = data.get("pid", pid)
        merged["title"] = data.get("title") or merged.get("title")
        merged["score"] = data.get("point", merged.get("score"))
        merged["difficulty"] = data.get("level", merged.get("difficulty"))

        primary_tag = self._infer_primary_tag(data)
        merged["tag"] = primary_tag if primary_tag else merged.get("tag", "General")

        # 保存完整标签列表，供用户 tag 过滤匹配。
        raw_tags = data.get("tag", [])
        detail_tags: list[str] = []
        if isinstance(raw_tags, list):
            for item in raw_tags:
                if isinstance(item, (list, tuple)) and item:
                    detail_tags.append(str(item[0]))
                elif isinstance(item, str):
                    detail_tags.append(item)
        merged["tags"] = detail_tags

        merged["link"] = f"{self.NSSCTF_BASE_URL}/problem/{merged.get('pid', pid)}"

        # 详情接口返回 desc 时优先使用；为空则给出可读占位，避免空文案。
        desc = str(data.get("desc", "") or "").strip()
        if not desc:
            desc = "题目详情可访问（该题暂无公开描述）"
        merged["description"] = desc

        return True, merged

    @staticmethod
    def _infer_primary_tag(detail_data: dict) -> str:
        tags = detail_data.get("tag", [])
        if isinstance(tags, list) and tags:
            first = tags[0]
            if isinstance(first, (list, tuple)) and first:
                return str(first[0])
            if isinstance(first, str):
                return first
        return "General"

    @staticmethod
    def _extract_problem_tags(problem: dict) -> list[str]:
        """统一提取题目标签为小写列表。"""
        tags_out: list[str] = []

        raw_tags = problem.get("tags")
        if isinstance(raw_tags, list):
            for item in raw_tags:
                text = str(item).strip().lower()
                if text:
                    tags_out.append(text)

        primary = str(problem.get("tag", "") or "").strip().lower()
        if primary:
            tags_out.append(primary)

        # 去重并保序
        unique: list[str] = []
        for t in tags_out:
            if t not in unique:
                unique.append(t)
        return unique

    def _is_problem_tag_match(self, problem: dict, user_tag: str) -> bool:
        user = str(user_tag or "").strip().lower()
        if not user:
            return True

        tags = self._extract_problem_tags(problem)
        if not tags:
            return False

        for t in tags:
            if user in t or t in user:
                return True
        return False

    def build_nssctf_msg(self, problem: dict) -> str:
        """构建 NSSCTF 题目展示消息"""
        pid = problem.get("pid", problem.get("id", "N/A"))
        title = problem.get("title", "未知题目")
        tag = problem.get("tag", "General")
        difficulty = problem.get("difficulty", "未知")
        link = problem.get("link", "https://www.nssctf.cn/problem_list")
        description = self._extract_nssctf_description(problem)
        
        # 尝试获取分数或解出人数
        score_info = f"{difficulty}" 
        if "score" in problem:
            score_info += f" ({problem['score']} pts)"

        if len(description) > 120:
            description = description[:117] + "..."
            
        return (
            "🎯 【NSSCTF 随机跳题】\n"
            "━━━━━━━━━━━━━━\n"
            f"🆔 题号: {pid}\n"
            f"🏷️ 方向: {tag}\n"
            f"📌 题目: {title}\n"
            f"🌟 难度: {score_info}\n"
            f"📝 描述: {description or '暂无描述'}\n"
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
        events = await self.query_service.fetch_ctftime_only(days_ahead=14)

        if not events:
            yield event.plain_result("📭 CTFTime 近期暂无符合阈值的赛事，或网络暂不可用。")
            return

        events = sorted(events, key=lambda x: str(x.get("start_time", "")))
        self._save_last_query_events(subscriber, events, limit=6)

        shown = events[:6]
        lines = [
            f"🌐 CTFTime 命中 {len(events)} 场，展示前 {len(shown)} 场（可用 /ctf订阅 序号 订阅）"
        ]
        for idx, item in enumerate(shown, 1):
            tags = ", ".join(item.get("tags", [])[:3]) or "无"
            lines.append(
                f"{idx}. {item.get('title', '未知赛事')}\n"
                f"ID: {item.get('id', 'N/A')} | 开赛(UTC+8): {to_bj_text(str(item.get('start_time', '')))} | Weight: {item.get('weight', 0)}\n"
                f"标签: {tags}\n"
                f"链接: {item.get('url', '')}"
            )

        yield event.plain_result("\n\n".join(lines))

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