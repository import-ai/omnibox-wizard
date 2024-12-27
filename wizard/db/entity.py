from datetime import datetime

import shortuuid
from sqlalchemy import DateTime, JSON, Text, String, Index
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=datetime.now)
    updated_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=datetime.now)
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)

    def delete(self):
        self.deleted_at = datetime.now()


class Task(Base):
    __tablename__ = "adm_task"

    task_id: Mapped[str] = mapped_column(String(length=22), primary_key=True, index=True, default=shortuuid.uuid)
    priority: Mapped[int] = mapped_column(default=0, doc="Bigger with higher priority")

    namespace_id: Mapped[str] = mapped_column(String(length=22))
    user_id: Mapped[str] = mapped_column(String(length=22))

    function: Mapped[str] = mapped_column(Text, nullable=False)
    input: Mapped[dict] = mapped_column(JSON, nullable=False)

    output: Mapped[dict] = mapped_column(JSON, nullable=True)
    exception: Mapped[dict] = mapped_column(JSON, nullable=True)

    started_at: Mapped[datetime] = mapped_column(DateTime, nullable=True)
    ended_at: Mapped[datetime] = mapped_column(DateTime, nullable=True)
    canceled_at: Mapped[datetime] = mapped_column(DateTime, nullable=True)

    concurrency_threshold: Mapped[int] = mapped_column(default=1, doc="Skip the task when concurrency bigger that it")

    __table_args__ = (
        Index("idx_task_ns_pri_s_e_c_time", "namespace_id", "priority", "started_at", "ended_at", "canceled_at"),
    )
