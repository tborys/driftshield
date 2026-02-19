"""Seed the database with sample transcripts on first startup."""

import uuid
from datetime import datetime, timezone
from pathlib import Path

from sqlalchemy.orm import Session as DBSession

from driftshield.cli.parsers import get_parser
from driftshield.core.analysis.session import analyze_session
from driftshield.core.models import Session as DomainSession, SessionStatus
from driftshield.db.engine import get_engine
from driftshield.db.persistence import PersistenceService

SEED_DIR = Path(__file__).parent / "fixtures"


def seed(db: DBSession) -> int:
    """Ingest all .jsonl fixtures. Returns number of sessions seeded."""
    if not SEED_DIR.exists():
        return 0

    count = 0
    parser = get_parser("claude_code")

    for fixture in sorted(SEED_DIR.glob("*.jsonl")):
        content = fixture.read_text()
        events = parser.parse(content)
        if not events:
            continue

        result = analyze_session(events)
        session_id = uuid.uuid4()
        domain_session = DomainSession(
            id=session_id,
            agent_id=events[0].agent_id or "unknown",
            started_at=events[0].timestamp or datetime.now(timezone.utc),
            status=SessionStatus.COMPLETED,
        )

        service = PersistenceService(db)
        service.save(domain_session, result)
        count += 1
        print(f"  Seeded: {fixture.name} ({result.total_events} events, "
              f"{'inflection' if result.inflection_node else 'clean'})")

    return count


def main():
    from sqlalchemy.orm import sessionmaker
    engine = get_engine()
    SessionLocal = sessionmaker(bind=engine)
    db = SessionLocal()
    try:
        count = seed(db)
        if count:
            print(f"Seeded {count} session(s).")
        else:
            print("No seed fixtures found.")
    finally:
        db.close()


if __name__ == "__main__":
    main()
