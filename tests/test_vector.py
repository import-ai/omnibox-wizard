from typing import List, Tuple

import pytest

from common.config_loader import Loader
from tests.helper.fixture import chromadb_endpoint
from wizard.config import Config, ENV_PREFIX
from wizard.grimoire.entity.chunk import Chunk, ChunkType
from wizard.grimoire.retriever.vector_db import VectorDB

namespace_id = "pytest"


@pytest.fixture(scope="function")
async def db(chromadb_endpoint: str) -> VectorDB:
    from dotenv import load_dotenv
    load_dotenv()
    loader = Loader(Config, env_prefix=ENV_PREFIX)
    config: Config = loader.load()
    db: VectorDB = VectorDB(config.vector)
    common_params = {
        "chunk_type": ChunkType.keyword,
        "namespace_id": namespace_id,
        "user_id": "test",
        "parent_id": "test"
    }

    chunk_list = [
        Chunk(resource_id="a", text="apple", title="apple", **common_params),
        Chunk(resource_id="a", text="car", title="apple", **common_params),
        Chunk(resource_id="b", text="snake", title="snake", **common_params)
    ]
    await db.insert(namespace_id, chunk_list)
    assert await (await db.get_collection(namespace_id)).count() > 0
    yield db


@pytest.mark.parametrize("query, k, rank, expected_text, expected_resource_id", [
    ("banana", 3, 0, "apple", "a"),
    ("bike", 3, 0, "car", "a"),
    ("chunk_type", 3, 0, "snake", "b")
])
async def test_db_query(db: VectorDB, query: str, k: int, rank: int, expected_text: str,
                        expected_resource_id: str):
    assert await (await db.get_collection(namespace_id)).count() > 0
    result_list: List[Tuple[Chunk, float]] = await db.query(query, k, condition={"namespace_id": namespace_id})
    assert len(result_list) == k
    assert result_list[rank][0].text == expected_text
    assert result_list[rank][0].resource_id == expected_resource_id


@pytest.mark.parametrize("resource_id, expected_count", [("a", 1), ("b", 2)])
async def test_db_remove(db: VectorDB, resource_id: str, expected_count: int):
    assert await (await db.get_collection(namespace_id)).count() == 3
    await db.remove(namespace_id, resource_id)
    assert await (await db.get_collection(namespace_id)).count() == expected_count
