import os
os.environ["APP_ENV"] = "test"
os.environ["DATABASE_URL"] = "sqlite:///./test_consumer_kg.db"
os.environ["NEO4J_ENABLED"] = "false"
import pytest
from fastapi.testclient import TestClient
from app.main import app
from app.db import Base, engine

@pytest.fixture()
def client():
    Base.metadata.drop_all(engine)
    Base.metadata.create_all(engine)
    with TestClient(app) as c:
        yield c
    Base.metadata.drop_all(engine)
