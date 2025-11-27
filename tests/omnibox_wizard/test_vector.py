import asyncio
from typing import List, Tuple

import pytest

from common.config_loader import Loader
from omnibox_wizard.wizard.config import Config, ENV_PREFIX
from omnibox_wizard.wizard.grimoire.entity.chunk import Chunk, ChunkType
from omnibox_wizard.wizard.grimoire.entity.tools import Condition
from omnibox_wizard.wizard.grimoire.retriever.meili_vector_db import MeiliVectorDB

namespace_id = "pytest"


@pytest.fixture(scope="function")
async def db(meilisearch_endpoint: str) -> MeiliVectorDB:
    from dotenv import load_dotenv

    load_dotenv()
    loader = Loader(Config, env_prefix=ENV_PREFIX)
    config: Config = loader.load()
    db: MeiliVectorDB = MeiliVectorDB(config.vector)
    common_params = {
        "chunk_type": ChunkType.keyword,
        "namespace_id": namespace_id,
        "user_id": "test",
        "parent_id": "test",
    }

    chunk_list = [
        Chunk(resource_id="a", text="apple", title="apple", **common_params),
        Chunk(resource_id="a", text="car", title="apple", **common_params),
        Chunk(resource_id="b", text="snake", title="snake", **common_params),
    ]
    await db.insert_chunks(namespace_id, chunk_list)
    yield db


@pytest.mark.parametrize(
    "query, k, rank, expected_text, expected_resource_id",
    [
        ("banana", 3, 0, "apple", "a"),
        ("bike", 3, 0, "car", "a"),
        ("chunk_type", 3, 0, "snake", "b"),
    ],
)
async def test_db_query(
    db: MeiliVectorDB,
    query: str,
    k: int,
    rank: int,
    expected_text: str,
    expected_resource_id: str,
):
    result_list: List[Tuple[Chunk, float]] = await db.query_chunks(
        namespace_id, query, k, Condition(namespace_id=namespace_id).to_meili_where()
    )
    assert len(result_list) == k
    assert result_list[rank][0].text == expected_text
    assert result_list[rank][0].resource_id == expected_resource_id


@pytest.mark.parametrize("resource_id, expected_count", [("a", 1), ("b", 2)])
async def test_db_remove(db: MeiliVectorDB, resource_id: str, expected_count: int):
    await db.remove_chunks(namespace_id, resource_id)
    index = db.meili.index(db.index_uid)
    await asyncio.sleep(1)  # Wait for MeiliSearch to update the index
    stats = await index.get_stats()
    assert stats.number_of_documents == expected_count
