import os
from typing import List, Tuple

import pytest

from common.config_loader import Loader
from tests.helper.fixture import chromadb_endpoint
from wizard.config import Config, ENV_PREFIX
from wizard.grimoire.entity.chunk import Chunk, ChunkType
from wizard.grimoire.retriever.vector_db import VectorDB

namespace = "pytest"


@pytest.fixture(scope="function")
async def db(chromadb_endpoint: str) -> VectorDB:
    from dotenv import load_dotenv
    load_dotenv()
    host, port = chromadb_endpoint.split(":")
    os.environ[f"{ENV_PREFIX}_VECTOR_HOST"] = host
    os.environ[f"{ENV_PREFIX}_VECTOR_PORT"] = port
    loader = Loader(Config, env_prefix=ENV_PREFIX)
    config: Config = loader.load()
    db: VectorDB = await VectorDB.from_config(config.vector)
    chunk_list = [
        Chunk(element_id="a", text="apple", title="apple", chunk_type=ChunkType.keyword, namespace=namespace),
        Chunk(element_id="a", text="car", title="apple", chunk_type=ChunkType.keyword, namespace=namespace),
        Chunk(element_id="b", text="snake", title="snake", chunk_type=ChunkType.keyword, namespace=namespace)
    ]
    await db.insert(chunk_list)
    yield db


@pytest.mark.parametrize("query, k, rank, expected_text, expected_element_id", [
    ("banana", 3, 0, "apple", "a"),
    ("bike", 3, 0, "car", "a"),
    ("chunk_type", 3, 0, "snake", "b")
])
async def test_db_query(db: VectorDB, query: str, k: int, rank: int, expected_text: str, expected_element_id: str):
    assert await db.collection.count() > 0
    result_list: List[Tuple[Chunk, float]] = await db.query(namespace, query, k)
    assert len(result_list) == k
    assert result_list[rank][0].text == expected_text
    assert result_list[rank][0].element_id == expected_element_id


@pytest.mark.parametrize("element_id, expected_count", [("a", 1), ("b", 2)])
async def test_db_remove(db: VectorDB, element_id: str, expected_count: int):
    assert await db.collection.count() == 3
    await db.remove(namespace, element_id)
    assert await db.collection.count() == expected_count
