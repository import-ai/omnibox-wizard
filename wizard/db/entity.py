from datetime import datetime

import shortuuid
from sqlalchemy import DateTime, JSON, Text, String, Index, ForeignKey
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    pass


class NamespaceConfig(Base):
    __tablename__ = "adm_config_namespace"

    namespace_id: Mapped[str] = mapped_column(String(length=22), primary_key=True, index=True)
    max_concurrency: Mapped[int] = mapped_column(default=1)


class Task(Base):
    __tablename__ = "adm_task"

    task_id: Mapped[str] = mapped_column(String(length=22), primary_key=True, index=True, default=shortuuid.uuid)
    priority: Mapped[int] = mapped_column(default=0, doc="Bigger with higher priority")

    namespace_id: Mapped[str] = mapped_column(String(length=22), ForeignKey("adm_config_namespace.namespace_id"))

    function: Mapped[str] = mapped_column(Text, nullable=False)
    input: Mapped[dict] = mapped_column(JSON, nullable=False)
    create_time: Mapped[datetime] = mapped_column(DateTime, default=datetime.now)

    output: Mapped[dict] = mapped_column(JSON, nullable=True)
    exception: Mapped[dict] = mapped_column(JSON, nullable=True)
    start_time: Mapped[datetime] = mapped_column(DateTime, nullable=True)
    end_time: Mapped[datetime] = mapped_column(DateTime, nullable=True)
    cancel_time: Mapped[datetime] = mapped_column(DateTime, nullable=True)

    __table_args__ = (
        Index("idx_task_ns_pri_s_e_c_time", "namespace_id", "priority", "start_time", "end_time", "cancel_time"),
    )
