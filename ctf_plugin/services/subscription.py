import asyncio
from datetime import datetime, timedelta, timezone
from typing import Any, List, Dict

from astrbot.api import logger
from astrbot.api.message_components import Plain, At

from ..db.repository import CTFRepository
from ..utils import parse_dt

try:
    from apscheduler.schedulers.asyncio import AsyncIOScheduler
except Exception:
    AsyncIOScheduler = None


class SubscriptionService:
    """
    Subscription Service using SQLite backend.
    Replaces SchedulerManager.
    """

    def __init__(
        self,
        context: Any,
        repository: CTFRepository,
        scan_interval_minutes: int = 10,
        remind_windows: list[int] | None = None,
    ):
        self.context = context
        self.repo = repository
        self.remind_windows = sorted(set(remind_windows or [120, 15]), reverse=True)
        self.scan_interval_minutes = scan_interval_minutes

        self.scheduler = None
        self.scheduler_enabled = AsyncIOScheduler is not None
        if not self.scheduler_enabled:
            logger.error("[CTF Pusher] Apscheduler not installed. Subscription disabled.")

    async def start(self):
        if not self.scheduler_enabled:
            return
        
        if self.scheduler is None:
            self.scheduler = AsyncIOScheduler()
            self.scheduler.add_job(
                self.subscription_scan_job,
                "interval",
                minutes=self.scan_interval_minutes,
                id="ctf_subscription_scan",
                replace_existing=True,
            )
        
        if not self.scheduler.running:
            self.scheduler.start()
            logger.info("[CTF Pusher] Subscription scheduler started.")

    async def shutdown(self):
        if self.scheduler is None:
            return
        if self.scheduler.running:
            self.scheduler.shutdown(wait=False)
            logger.info("[CTF Pusher] Subscription scheduler stopped.")

    def _get_subscriber_key(self, subscriber: dict[str, str]) -> str:
        return f"{subscriber.get('type')}:{subscriber.get('target_id')}:{subscriber.get('at_user_id')}"

    def _normalize_reminded(self, reminded: Any) -> dict[str, bool]:
        base = reminded if isinstance(reminded, dict) else {}
        out: dict[str, bool] = {}
        for win in self.remind_windows:
            key = str(win)
            out[key] = bool(base.get(key, False))
        return out

    async def subscribe(self, event_data: dict[str, Any], subscriber: dict[str, str]) -> tuple[bool, str]:
        if not self.scheduler_enabled:
            return False, "Scheduler not enabled"

        if not subscriber.get("target_id"):
            return False, "Unknown subscriber target"

        key = self._get_subscriber_key(subscriber)
        
        # Ensure start_time is a datetime object or parseable string handled by repo? 
        # Repo expects datetime object or string format that sqlalchemy accepts.
        # Let's ensure it is parsed here.
        start_time_str = event_data.get("start_time")
        start_dt = parse_dt(start_time_str)
        if not start_dt:
             return False, "Invalid event start time"
        
        # We need to construct event_dict with datetime object for repo
        repo_event_data = event_data.copy()
        repo_event_data['start_time'] = start_dt

        initial_reminded = {str(win): False for win in self.remind_windows}
        
        # Run in executor if db ops are blocking?
        # Since we use scoped_session, these are synchronous DB calls.
        # Should wrap in asyncio.to_thread if we want true async non-blocking.
        # For simplicity/compatibility with this scale, sync call is okay or use to_thread.
        # Bangumi analysis mentions 'storage.subscribe_subject' called from main. 
        # Let's wrapping in to_thread is safer for main loop.
        
        try:
            success, msg = await asyncio.to_thread(
                self.repo.add_subscription, 
                key, 
                repo_event_data, 
                initial_reminded
            )
            return success, msg
        except Exception as e:
            logger.error(f"Subscribe error: {e}")
            return False, f"Database error: {e}"

    async def unsubscribe_by_event_id(self, event_id: str, subscriber: dict[str, str]) -> tuple[bool, str]:
        if not subscriber.get("target_id"):
            return False, "Unknown subscriber target"

        key = self._get_subscriber_key(subscriber)
        try:
            count = await asyncio.to_thread(self.repo.remove_subscription, key, event_id)
            if count > 0:
                return True, f"Unsubscribed {count} events"
            return False, "Subscription not found"
        except Exception as e:
             logger.error(f"Unsubscribe error: {e}")
             return False, f"Database error: {e}"

    async def list_subscriptions(self, subscriber: dict[str, str]) -> List[Dict[str, Any]]:
        key = self._get_subscriber_key(subscriber)
        try:
            results = await asyncio.to_thread(self.repo.get_subscriptions, key)
            # transform back to dicts expected by main.py
            output = []
            for item in results:
                start_time = item.get("start_time")
                start_str = start_time.isoformat() if start_time else ""
                output.append({
                    "event_id": item.get("org_id"),
                    "title": item.get("title"),
                    "start_time": start_str,
                    "source": item.get("source"),
                    # ... other fields if needed
                })
            output.sort(key=lambda x: x.get("start_time", ""))
            return output
        except Exception as e:
            logger.error(f"List error: {e}")
            return []

    async def _send_to_subscriber(self, subscriber_key: str, text: str):
        # Parse subscriber key
        parts = subscriber_key.split(":")
        # Format: type:target_id:at_user_id
        # Note: at_user_id might be 'None' string or empty
        if len(parts) >= 3:
            target_type = parts[0]
            target_id = parts[1]
            at_user_id = parts[2]
            if at_user_id == 'None' or at_user_id == '':
                at_user_id = None
        else:
            return # Invalid key

        provider = self.context.get_platform_manager().get_default_provider()
        target = provider.build_target(target_id, is_group=(target_type == "group"))

        if target_type == "group" and at_user_id:
             # Try sending with At
             # (Copy logic from scheduler_manager)
            if At is not None:
                try:
                    await provider.send_message(target, [At(at_user_id), Plain(" " + text)])
                    return
                except Exception:
                    pass
            await provider.send_message(target, [Plain(f"@{at_user_id} {text}")])
            return

        await provider.send_message(target, [Plain(text)])

    async def subscription_scan_job(self):
        try:
            # Fetch all active subscriptions
            # We fetch list of dicts
            # Run in thread
            subs_events = await asyncio.to_thread(self.repo.get_all_active_subscriptions)
            
            now = datetime.now(timezone.utc)

            for item in subs_events:
                start_time = item.get("start_time")
                if not start_time:
                    continue
                
                # Handle timezone. 
                # If start_time is naive, assume UTC.
                if start_time.tzinfo is None:
                    start_dt = start_time.replace(tzinfo=timezone.utc)
                else:
                    start_dt = start_time
                
                delta_minutes = int((start_dt - now).total_seconds() // 60)
                
                if delta_minutes < -60 * 24: # Passed 1 day
                    continue 

                reminded = self._normalize_reminded(item.get("reminded_status", {}))
                changed = False
                
                for idx, win in enumerate(self.remind_windows):
                    key = str(win)
                    if reminded.get(key, False):
                        continue
                    
                    # Logic: if delta is within window (and greater than next window)
                    lower_bound = self.remind_windows[idx+1] if idx+1 < len(self.remind_windows) else 0
                    
                    # Check window
                    if lower_bound < delta_minutes <= win:
                        title = item.get("title", "")
                        text = f"⏰ 叮！您订阅的赛事 [{title}] 将在约 [{delta_minutes}] 分钟后开始，请准备！"
                        try:
                            subscriber_key = item.get("subscriber_key")
                            if subscriber_key:
                                await self._send_to_subscriber(subscriber_key, text)
                                reminded[key] = True
                                changed = True
                        except Exception as e:
                            logger.error(f"Send reminder failed: {e}")
                            
                        break # One reminder per scan
                
                if changed:
                    await asyncio.to_thread(
                        self.repo.update_reminder_status, 
                        item.get("subscriber_key"), 
                        item.get("event_unique_id"), 
                        reminded
                    )

        except Exception as e:
            logger.error(f"Scan job error: {e}")
