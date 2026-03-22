from sqlalchemy import Column, String, Integer, Float, DateTime, ForeignKey, JSON
from sqlalchemy.orm import declarative_base, relationship
from sqlalchemy.sql import func

Base = declarative_base()

class CTFEvent(Base):
    """
    CTF 赛事条目表
    对应 BangumiSubject
    """
    __tablename__ = "ctf_events"

    # 唯一标识符，例如 "ctftime:256"
    unique_id = Column(String, primary_key=True)
    
    # 原始数据
    org_id = Column(String)  # 原始平台ID
    source = Column(String)  # 来源平台
    title = Column(String)
    url = Column(String)
    start_time = Column(DateTime)
    weight = Column(Float, default=0.0)
    
    # 关联订阅
    subscriptions = relationship("Subscription", back_populates="event", cascade="all, delete-orphan")
    
    updated_at = Column(DateTime, default=func.now(), onupdate=func.now())

class Subscription(Base):
    """
    订阅关系表
    对应 Subscription
    """
    __tablename__ = "subscriptions"

    # 复合主键: 订阅者标识 + 赛事ID
    # subscriber_key 格式: "type:target_id:at_user_id"
    subscriber_key = Column(String, primary_key=True)
    event_id = Column(String, ForeignKey("ctf_events.unique_id"), primary_key=True)
    
    # 提醒状态，存储已触发的窗口 (e.g. {"120": true, "15": false})
    reminded_status = Column(JSON, default=dict)
    
    created_at = Column(DateTime, default=func.now())
    
    event = relationship("CTFEvent", back_populates="subscriptions")
