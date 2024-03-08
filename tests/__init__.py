from typing import Generator
import pytest
import sqlmodel


@pytest.fixture(name="session")
def get_test_session() -> Generator[sqlmodel.Session, None, None]:
    """get a session"""
    engine = sqlmodel.create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=sqlmodel.StaticPool,
    )
    sqlmodel.SQLModel.metadata.create_all(engine)
    with sqlmodel.Session(engine) as session:
        yield session
