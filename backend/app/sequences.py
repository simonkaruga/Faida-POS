"""Human-friendly numbers (bill #0142, slip 57...), separate from the hidden unique IDs."""

import uuid

from sqlalchemy import ForeignKey, Integer, String
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Mapped, Session, mapped_column

from app.db import Base


class Sequence(Base):
    __tablename__ = "sequences"

    business_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("businesses.id"), primary_key=True)
    name: Mapped[str] = mapped_column(String(30), primary_key=True)
    value: Mapped[int] = mapped_column(Integer)


def next_number(db: Session, business_id: uuid.UUID, name: str) -> int:
    """Atomically take the next number. Part of the caller's transaction, so a rolled
    back sale doesn't use up a number."""
    stmt = (
        insert(Sequence)
        .values(business_id=business_id, name=name, value=1)
        .on_conflict_do_update(
            index_elements=[Sequence.business_id, Sequence.name],
            set_={"value": Sequence.value + 1},
        )
        .returning(Sequence.value)
    )
    return db.execute(stmt).scalar_one()
