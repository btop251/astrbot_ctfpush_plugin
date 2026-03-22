from typing import Any, List, Tuple
from sqlalchemy.orm import Session
from datetime import datetime, timezone

from .models import CTFEvent, Subscription

class CTFRepository:
    """SQLAlchemy Repository for CTF Events and Subscriptions"""
    
    def __init__(self, db_manager):
        self.db = db_manager

    def find_event(self, unique_id: str) -> dict | None:
        with self.db.session_scope() as session:
            evt = session.query(CTFEvent).filter(CTFEvent.unique_id == unique_id).first()
            if not evt:
                return None
            return {
                "event_unique_id": evt.unique_id,
                "org_id": evt.org_id,
                "title": evt.title,
                "start_time": evt.start_time,
                "source": evt.source,
                "url": evt.url,
            }

    def get_subscriptions(self, subscriber_key: str) -> List[dict]:
        with self.db.session_scope() as session:
            results = session.query(Subscription, CTFEvent)\
                .join(CTFEvent)\
                .filter(Subscription.subscriber_key == subscriber_key)\
                .all()
            
            data = []
            for sub, evt in results:
                data.append({
                    "event_unique_id": evt.unique_id,
                    "org_id": evt.org_id,
                    "title": evt.title,
                    "start_time": evt.start_time,
                    "source": evt.source,
                    "url": evt.url,
                    "reminded_status": sub.reminded_status,
                })
            return data

    def add_subscription(
        self, 
        subscriber_key: str, 
        event_dict: dict, 
        initial_reminder_status: dict
    ) -> Tuple[bool, str]:
        """
        Add a subscription.
        Must check uniqueness.
        """
        with self.db.session_scope() as session:
            unique_id = f"{event_dict.get('source', '')}:{event_dict.get('id', '')}"
            
            # Check if subscription already exists
            existing = session.query(Subscription).filter_by(
                subscriber_key=subscriber_key,
                event_id=unique_id
            ).first()
            
            if existing:
                return False, "Already subscribed"
            
            # Check or Create Event
            event = session.query(CTFEvent).filter_by(unique_id=unique_id).first()
            if not event:
                event = CTFEvent(
                    unique_id=unique_id,
                    org_id=str(event_dict.get("id", "")),
                    source=event_dict.get("source", ""),
                    title=event_dict.get("title", ""),
                    url=event_dict.get("url", ""),
                    start_time=event_dict.get("start_time"), # Make sure this is a datetime object or parse it
                    weight=event_dict.get("weight", 0.0)
                )
                session.add(event)
            
            subscription = Subscription(
                subscriber_key=subscriber_key,
                event=event,
                reminded_status=initial_reminder_status
            )
            session.add(subscription)
            
            return True, "Subscribed successfully"

    def remove_subscription(self, subscriber_key: str, event_id: str) -> int:
        with self.db.session_scope() as session:
            # Note: We match against the unique_id of the event
            # event_id passed here is likely the short 'id' from command line
            # But the user might provide just '123' if source is implied or full unique_id
            
            # Try to match unique_id ending with event_id if no source provided
            # Or assume subscriber knows exact ID.
            # For simplicity, let's assume we search by fuzzy match or strict.
            
            # Strict match for now, assuming logic handles resolution
            deleted = session.query(Subscription)\
                .filter(Subscription.subscriber_key == subscriber_key)\
                .filter(Subscription.event_id.like(f"%{event_id}"))\
                .delete(synchronize_session=False)

            return deleted

    def get_all_active_subscriptions(self) -> List[dict]:
        """Used for scanning jobs"""
        with self.db.session_scope() as session:
            # Eager load event
            results = session.query(Subscription).join(CTFEvent).all()
            
            data = []
            for sub in results:
                evt = sub.event
                if not evt: continue
                data.append({
                    "subscriber_key": sub.subscriber_key,
                    "reminded_status": sub.reminded_status,
                    "event_unique_id": evt.unique_id,
                    "org_id": evt.org_id,
                    "title": evt.title,
                    "start_time": evt.start_time,
                    "source": evt.source,
                })
            return data
            
    def update_reminder_status(self, subscriber_key: str, unique_id: str, new_status: dict):
        with self.db.session_scope() as session:
            sub = session.query(Subscription).filter_by(
                subscriber_key=subscriber_key, event_id=unique_id
            ).first()
            if sub:
                sub.reminded_status = new_status
                session.add(sub) # Mark dirty

