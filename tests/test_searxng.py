import os

from dotenv import load_dotenv

from wizard.grimoire.retriever.searxng import SearXNG

load_dotenv()


async def test_searxng() -> None:
    searxng = SearXNG(os.environ["OBW_SEARXNG_BASE_URL"])
    result = await searxng.search("太阳的直径")
    result_with_updated_at = list(filter(lambda x: x.to_citation().updated_at is not None, result))
    print(result)
    print(result_with_updated_at)
