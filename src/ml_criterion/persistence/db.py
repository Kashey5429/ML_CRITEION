from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker


def create_sessions(url: str):
    engine = create_engine(
        url,
        pool_pre_ping=True,
        connect_args={
            "connect_timeout": 5,
            "options": "-cstatement_timeout=5000 -clock_timeout=2000 -ctimezone=UTC",
            "keepalives": 1,
            "keepalives_idle": 5,
            "keepalives_interval": 2,
            "keepalives_count": 2,
        },
    )
    return engine, sessionmaker(engine, expire_on_commit=False)
