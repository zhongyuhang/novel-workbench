"""Process-local handles shared by the API and the background worker."""

import threading
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field

from sqlalchemy.orm import Session, sessionmaker

from app.ai.broker import TaskBroker


@dataclass
class AiRuntime:
    session_factory: sessionmaker[Session]
    broker: TaskBroker
    executor: ThreadPoolExecutor
    cancel_events: dict[str, threading.Event] = field(default_factory=dict)
    lock: threading.Lock = field(default_factory=threading.Lock)
