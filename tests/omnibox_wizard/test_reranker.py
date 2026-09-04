from unittest.mock import MagicMock, patch

from wizard_common.config import OpenAIConfig
from wizard_common.grimoire.config import RerankerConfig
from wizard_common.grimoire.retriever.reranker import Reranker


async def test_rerank_skips_empty_query() -> None:
    retrieval = MagicMock()
    reranker = Reranker(
        RerankerConfig(
            openai=OpenAIConfig(
                base_url="http://reranker.test",
                api_key="test-key",
                model="test-model",
            )
        )
    )

    with patch("wizard_common.grimoire.retriever.reranker.httpx.AsyncClient") as client:
        result = await reranker.rerank("  ", [retrieval])

    assert result == [retrieval]
    client.assert_not_called()
