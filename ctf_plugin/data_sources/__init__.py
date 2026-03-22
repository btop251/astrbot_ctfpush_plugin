from .aggregator import EventQueryService
from .base import EventModel
from .ctftime import CTFTimeSource

# Backward compatibility alias
EventAggregator = EventQueryService

__all__ = [
    "EventModel",
    "CTFTimeSource",
    "EventQueryService",
    "EventAggregator",
]
