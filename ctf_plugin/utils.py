"""
工具函数模块
包含时间解析、消息格式化等纯函数工具
"""

import re
from datetime import datetime, timedelta, timezone
from typing import Any, Optional


def parse_dt(value: str) -> Optional[datetime]:
    """
    安全解析时间字符串为 UTC 时区的 datetime 对象
    
    支持格式:
      - ISO 8601: "2026-03-21T10:30:00Z" 或 "2026-03-21T10:30:00+00:00"
      - 其他可被 fromisoformat 解析的格式
    
    Args:
        value: 时间字符串
    
    Returns:
        解析好的 UTC 时区 datetime；若失败则返回 None
    """
    if not value:
        return None
    
    try:
        # 替换 Z 为 +00:00，使其能被 fromisoformat 解析
        normalized = str(value).replace("Z", "+00:00")
        
        # 尝试用 fromisoformat 解析
        dt = datetime.fromisoformat(normalized)
        
        # 确保转换到 UTC 时区
        if dt.tzinfo is None:
            # 如果没有时区信息，假设为 UTC
            dt = dt.replace(tzinfo=timezone.utc)
        else:
            # 如果有时区信息，转换到 UTC
            dt = dt.astimezone(timezone.utc)
        
        return dt
    except (ValueError, TypeError) as e:
        # 解析失败，返回 None（不抛异常）
        return None


def to_bj_text(value: str) -> str:
    """
    将时间字符串转换为北京时间的格式化文本 "YYYY-MM-DD HH:MM"
    
    Args:
        value: ISO8601 时间字符串
    
    Returns:
        北京时间格式的字符串；若解析失败则返回 "未知"
    """
    dt = parse_dt(value)
    if dt is None:
        return "未知"
    
    # 转换到北京时间 (UTC+8)
    bj_tz = timezone(timedelta(hours=8))
    bj_dt = dt.astimezone(bj_tz)
    
    return bj_dt.strftime("%Y-%m-%d %H:%M")


def source_mark(source: str) -> str:
    """
    根据数据源返回对应的标记
    
    Args:
        source: 数据源标识
    
    Returns:
        带 emoji 的源标记字符串
    """
    source_lower = str(source).lower()
    if source_lower == "ctftime":
        return "🌐 国际赛事(CTFTime)"
    else:
        return "未知来源"


def normalize_tag_text(value: str) -> list[str]:
    """
    将标签文本按逗号、空格等分隔符分割并标准化
    
    Args:
        value: 原始标签字符串
    
    Returns:
        标准化的标签列表 (小写，去空格)
    """
    if not value:
        return []
    
    # 按常见分隔符分割
    tags = re.split(r"[,，/\s]+", str(value))
    
    # 过滤空标签并转小写
    return [tag.strip().lower() for tag in tags if tag.strip()]


def match_tag(title: str, tags: list[str], filter_tag: str) -> bool:
    """
    判断赛事是否匹配指定的标签过滤条件
    
    Args:
        title: 赛事标题
        tags: 赛事标签列表
        filter_tag: 要匹配的过滤标签
    
    Returns:
        如果 filter_tag 为空返回 True；否则检查标题或标签是否包含该过滤标签
    """
    if not filter_tag:
        return True
    
    filter_tag = str(filter_tag).strip().lower()
    title_lower = str(title or "").lower()
    tags_lower = [str(t).lower() for t in (tags or [])]
    
    # 检查标题中是否包含过滤标签
    if filter_tag in title_lower:
        return True
    
    # 检查标签中是否包含过滤标签
    for tag in tags_lower:
        if filter_tag in tag:
            return True
    
    return False


def extract_command_arg(event: Any, command_name: str) -> str:
    """
    从事件对象中提取命令的参数部分
    
    兼容多种 AstrBot 事件字段，支持格式:
      - /ctf xxx
      - /ctf订阅 123456
    
    Args:
        event: AstrMessageEvent 事件对象
        command_name: 命令名 (如 "ctf", "ctf订阅")
    
    Returns:
        命令参数部分；若无参数或格式不匹配则返回空字符串
    """
    # 尝试从多个可能的事件字段中获取原始消息
    raw = ""
    for attr in ("message_str", "raw_message", "message"):
        val = getattr(event, attr, None)
        if isinstance(val, str) and val.strip():
            raw = val
            break
    
    if not raw:
        return ""
    
    # 统一全角空格，避免输入法引入空白导致参数识别异常
    raw = raw.replace("\u3000", " ").strip()

    # 构造正则表达式，匹配消息中出现的 /命令名 及其参数
    # 支持日志前缀或平台注入前缀文本，例如 "昵称/ID: /ctf订阅 3131 "
    escaped_cmd = re.escape(command_name)
    pattern = rf"(?:^|\s)/{escaped_cmd}(?:\s+(.*?))?\s*$"

    match = re.search(pattern, raw, flags=re.IGNORECASE)
    if match:
        return (match.group(1) or "").strip()
    
    return ""


def extract_sender(event: Any) -> dict[str, str]:
    """
    从事件对象中抽取发送者的身份信息（用于订阅提醒时定位目标）
    
    Args:
        event: AstrMessageEvent 事件对象
    
    Returns:
        包含 type, target_id, at_user_id 的字典
        {
            "type": "group" | "user",
            "target_id": "群号或用户ID",
            "at_user_id": "如果是群消息，则为用户ID，私聊则为用户ID"
        }
    """
    
    def pick(*names: str) -> str:
        """从多个可能的字段中选取第一个非空值"""
        for name in names:
            val = getattr(event, name, None)
            
            # 如果是可调用对象，尝试调用（处理某些 API 设计）
            if callable(val):
                try:
                    val = val()
                except Exception:
                    continue
            
            # 检查值是否有效
            if val is not None and str(val) != "":
                return str(val)
        
        return ""
    
    # 优先获取群号；如果没有则为私聊
    group_id = pick("group_id", "groupId", "channel_id", "room_id")
    user_id = pick("user_id", "sender_id", "qq", "uid", "author_id", "get_sender_id", "get_self_id")
    
    # 尝试从 message_obj 获取（AstrBot 核心对象）
    if not user_id:
        msg_obj = getattr(event, "message_obj", None)
        if msg_obj:
            user_id = str(getattr(msg_obj, "sender_id", "") or "")
            if not group_id:
                group_id = str(getattr(msg_obj, "group_id", "") or "")
    
    # 尝试从 unified_msg_origin 获取（AstrBot v3.0+）
    if not user_id:
         origin = getattr(event, "unified_msg_origin", None)
         # 这是一个 UnifiedMessageOrigin 对象，不是字典
         if origin:
             # 尝试直接访问属性
             user_id = str(getattr(origin, "sender_id", "") or "")
             if not group_id:
                 group_id = str(getattr(origin, "group_id", "") or "")

    # 尝试从 session 获取 (AstrBot v3.1+)
    # 注意：session 的优先级应当提高，特别是当 message_obj 不含数据时
    if not user_id:
        session = getattr(event, "session", None)
        if session:
            sess_id = str(getattr(session, "session_id", "") or "")
            if sess_id:
                msg_type = str(getattr(session, "message_type", "")).lower()
                
                if "group" in msg_type:
                    # 群聊场景
                    if not group_id:
                        group_id = sess_id
                    # 群聊里如果没有取到 sender_id，暂无法精准定位个人
                else:
                    # 私聊场景
                    user_id = sess_id

    # 终极兜底：有些框架环境 session_id 就是唯一标识

    
    # 终极兜底：有些框架环境 session_id 就是唯一标识
    if not group_id and not user_id:
        return {
             "type": "unknown",
             "target_id": "",
             "at_user_id": ""
        }

    # 特殊修补：对于私聊场景，session_id 确实是 user_id，但 group_id 应该为空
    # 上面的逻辑可能会因为 pick 失败导致 group_id 依然为空，此时就是私聊
    
    if group_id:
        return {
            "type": "group",
            "target_id": group_id,
            "at_user_id": user_id,
        }
    
    return {
        "type": "user",
        "target_id": user_id,
        "at_user_id": user_id,
    }


def format_message(events: list[dict[str, Any]]) -> str:
    """
    将赛事列表格式化为美观的 QQ 文本消息排版
    
    Args:
        events: CTFEvent 字典列表
    
    Returns:
        格式化后的文本（包含 emoji 和换行符）
    """
    if not events:
        return "📭 暂无赛事信息"
    
    lines = []
    for idx, event in enumerate(events, 1):
        title = event.get("title", "未知赛事")
        source = source_mark(event.get("source", ""))
        event_id = event.get("id", "N/A")
        start_time = to_bj_text(event.get("start_time", ""))
        end_time = to_bj_text(event.get("end_time", ""))
        url = event.get("url", "")
        tags = event.get("tags", [])
        tags_str = ", ".join(tags[:6]) if tags else "无"
        restrictions = event.get("restrictions", "")
        restrictions_str = f"[限制] {restrictions}\n" if restrictions else ""
        
        # 格式化每个赛事
        event_text = (
            f"『{idx}』 {title}\n"
            f"{source}\n"
            f"🆔 赛事ID: {event_id}\n"
            f"🏷️ 标签: {tags_str}\n"
            f"⏰ 开赛: {start_time} | 结束: {end_time}\n"
            f"{restrictions_str}"
            f"🔗 链接: {url}"
        )
        lines.append(event_text)
    
    # 多个赛事用分隔符连接
    return "\n" + "─" * 30 + "\n".join(["\n" + line for line in lines])


def build_event_text(event: dict[str, Any]) -> str:
    """
    为单个赛事构建详细的展示文本（较 format_message 更简洁）
    
    Args:
        event: CTFEvent 字典
    
    Returns:
        单个赛事的格式化文本
    """
    return (
        f"📌 {event.get('title', '未知赛事')}\n"
        f"{source_mark(event.get('source', ''))}\n"
        f"🆔 赛事ID: {event.get('id', 'N/A')}\n"
        f"⏰ 开赛时间(UTC+8): {to_bj_text(event.get('start_time', ''))}\n"
        f"🏷️ 标签: {', '.join(event.get('tags', [])[:6]) or '无'}\n"
        f"🔗 链接: {event.get('url', '')}"
    )
