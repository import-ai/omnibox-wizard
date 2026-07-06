import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from fastapi.testclient import TestClient
from fastapi import FastAPI
from wizard_common.grimoire.entity.chunk import Chunk

from omnibox_wizard.wizard.api.internal import internal_router
from omnibox_wizard.wizard.api.entity import (
    CommonAITextRequest,
    TitleResponse,
    TagsResponse,
)


@pytest.fixture
def app():
    """Create FastAPI app with internal router for testing"""
    app = FastAPI()
    app.include_router(internal_router)
    return app


@pytest.fixture
def client(app):
    """Create test client"""
    return TestClient(app)


@pytest.fixture
def mock_common_ai():
    """Mock CommonAI instance"""
    with patch("omnibox_wizard.wizard.api.internal.common_ai") as mock:
        yield mock


@pytest.fixture
def mock_weaviate_vector_db():
    with patch("omnibox_wizard.wizard.api.internal.weaviate_vector_db") as mock:
        yield mock


class TestTitleAPI:
    """Test cases for /title endpoint with lang parameter"""

    @pytest.mark.parametrize(
        "text,lang,expected_title",
        [
            ("What is AI?", "English", "Understanding Artificial Intelligence"),
        ],
    )
    async def test_title_with_lang_parameter(
        self, client, mock_common_ai, text, lang, expected_title
    ):
        """Test title generation with different language parameters"""
        # Mock the CommonAI title method
        mock_common_ai.title.return_value = expected_title

        # Make request
        response = client.post(
            "/internal/api/v1/wizard/title", json={"text": text, "lang": lang}
        )

        # Assertions
        assert response.status_code == 200
        response_data = response.json()
        assert response_data["title"] == expected_title

        # Verify CommonAI was called with correct parameters
        mock_common_ai.title.assert_called_once()
        call_args = mock_common_ai.title.call_args
        assert call_args[0][0] == text  # First positional argument
        assert call_args[1]["lang"] == lang  # Keyword argument

    async def test_title_default_lang(self, client, mock_common_ai):
        """Test title generation with default language"""
        expected_title = "默认语言标题"
        mock_common_ai.title.return_value = expected_title

        # Request without specifying lang (should use default)
        response = client.post(
            "/internal/api/v1/wizard/title", json={"text": "测试文本"}
        )

        assert response.status_code == 200
        response_data = response.json()
        assert response_data["title"] == expected_title

        # Verify default lang was used
        call_args = mock_common_ai.title.call_args
        assert call_args[1]["lang"] == "简体中文"

    async def test_title_invalid_lang(self, client, mock_common_ai):
        """Test title generation with invalid language parameter"""
        # Should return validation error for invalid lang
        response = client.post(
            "/internal/api/v1/wizard/title",
            json={"text": "测试文本", "lang": "InvalidLanguage"},
        )

        assert response.status_code == 422  # Validation error

    async def test_title_missing_text(self, client, mock_common_ai):
        """Test title generation without text parameter"""
        response = client.post(
            "/internal/api/v1/wizard/title", json={"lang": "English"}
        )

        assert response.status_code == 422  # Validation error

    async def test_title_response_format(self, client, mock_common_ai):
        """Test that title response follows correct format"""
        expected_title = "Test Title"
        mock_common_ai.title.return_value = expected_title

        response = client.post(
            "/internal/api/v1/wizard/title",
            json={"text": "Test text", "lang": "English"},
        )

        assert response.status_code == 200
        response_data = response.json()

        # Verify response structure
        assert "title" in response_data
        assert isinstance(response_data["title"], str)
        assert response_data["title"] == expected_title


class TestTagsAPI:
    """Test cases for /tags endpoint with lang parameter"""

    @pytest.mark.parametrize(
        "text,lang,expected_tags",
        [
            (
                "Machine Learning and AI",
                "English",
                ["machine-learning", "artificial-intelligence", "technology"],
            )
        ],
    )
    async def test_tags_with_lang_parameter(
        self, client, mock_common_ai, text, lang, expected_tags
    ):
        """Test tags generation with different language parameters"""
        # Mock the CommonAI tags method
        mock_common_ai.tags.return_value = expected_tags

        # Make request
        response = client.post(
            "/internal/api/v1/wizard/tags", json={"text": text, "lang": lang}
        )

        # Assertions
        assert response.status_code == 200
        response_data = response.json()
        assert response_data["tags"] == expected_tags

        # Verify CommonAI was called with correct parameters
        mock_common_ai.tags.assert_called_once()
        call_args = mock_common_ai.tags.call_args
        assert call_args[0][0] == text  # First positional argument
        assert call_args[1]["lang"] == lang  # Keyword argument

    async def test_tags_default_lang(self, client, mock_common_ai):
        """Test tags generation with default language"""
        expected_tags = ["默认", "标签", "测试"]
        mock_common_ai.tags.return_value = expected_tags

        # Request without specifying lang (should use default)
        response = client.post(
            "/internal/api/v1/wizard/tags", json={"text": "测试文本"}
        )

        assert response.status_code == 200
        response_data = response.json()
        assert response_data["tags"] == expected_tags

        # Verify default lang was used
        call_args = mock_common_ai.tags.call_args
        assert call_args[1]["lang"] == "简体中文"

    async def test_tags_invalid_lang(self, client, mock_common_ai):
        """Test tags generation with invalid language parameter"""
        response = client.post(
            "/internal/api/v1/wizard/tags",
            json={"text": "测试文本", "lang": "InvalidLanguage"},
        )

        assert response.status_code == 422  # Validation error

    async def test_tags_missing_text(self, client, mock_common_ai):
        """Test tags generation without text parameter"""
        response = client.post("/internal/api/v1/wizard/tags", json={"lang": "English"})

        assert response.status_code == 422  # Validation error

    async def test_tags_response_format(self, client, mock_common_ai):
        """Test that tags response follows correct format"""
        expected_tags = ["tag1", "tag2", "tag3"]
        mock_common_ai.tags.return_value = expected_tags

        response = client.post(
            "/internal/api/v1/wizard/tags",
            json={"text": "Test text", "lang": "English"},
        )

        assert response.status_code == 200
        response_data = response.json()

        # Verify response structure
        assert "tags" in response_data
        assert isinstance(response_data["tags"], list)
        assert all(isinstance(tag, str) for tag in response_data["tags"])
        assert response_data["tags"] == expected_tags

    async def test_tags_empty_response(self, client, mock_common_ai):
        """Test tags generation when no tags are returned"""
        mock_common_ai.tags.return_value = []

        response = client.post(
            "/internal/api/v1/wizard/tags",
            json={"text": "No tags text", "lang": "English"},
        )

        assert response.status_code == 200
        response_data = response.json()
        assert response_data["tags"] == []


class TestLanguageConsistency:
    """Test language consistency across both endpoints"""

    @pytest.mark.parametrize(
        "text,lang",
        [
            ("Artificial Intelligence Development", "English"),
        ],
    )
    async def test_consistent_lang_usage(self, client, mock_common_ai, text, lang):
        """Test that both endpoints use the same lang parameter consistently"""
        mock_common_ai.title.return_value = "Test Title"
        mock_common_ai.tags.return_value = ["tag1", "tag2"]

        # Test title endpoint
        title_response = client.post(
            "/internal/api/v1/wizard/title", json={"text": text, "lang": lang}
        )

        # Test tags endpoint
        tags_response = client.post(
            "/internal/api/v1/wizard/tags", json={"text": text, "lang": lang}
        )

        # Both should succeed
        assert title_response.status_code == 200
        assert tags_response.status_code == 200

        # Verify both were called with the same lang parameter
        title_call_args = mock_common_ai.title.call_args
        tags_call_args = mock_common_ai.tags.call_args

        assert title_call_args[1]["lang"] == lang
        assert tags_call_args[1]["lang"] == lang

    async def test_trace_info_propagation(self, client, mock_common_ai):
        """Test that trace_info is properly propagated to CommonAI methods"""
        mock_common_ai.title.return_value = "Test Title"
        mock_common_ai.tags.return_value = ["tag1"]

        # Make requests
        client.post(
            "/internal/api/v1/wizard/title", json={"text": "test", "lang": "English"}
        )

        client.post(
            "/internal/api/v1/wizard/tags", json={"text": "test", "lang": "English"}
        )

        # Verify trace_info was passed (should be in kwargs)
        title_call_args = mock_common_ai.title.call_args
        tags_call_args = mock_common_ai.tags.call_args

        assert "trace_info" in title_call_args[1]
        assert "trace_info" in tags_call_args[1]


class TestEntityValidation:
    """Test request/response entity validation"""

    def test_common_ai_text_request_validation(self):
        """Test CommonAITextRequest validation"""
        # Valid request
        valid_request = CommonAITextRequest(text="test", lang="English")
        assert valid_request.text == "test"
        assert valid_request.lang == "English"

        # Default lang
        default_request = CommonAITextRequest(text="test")
        assert default_request.lang == "简体中文"

        # Invalid lang should raise validation error
        with pytest.raises(ValueError):
            CommonAITextRequest(text="test", lang="InvalidLang")

    def test_title_response_validation(self):
        """Test TitleResponse validation"""
        response = TitleResponse(title="Test Title")
        assert response.title == "Test Title"

    def test_tags_response_validation(self):
        """Test TagsResponse validation"""
        response = TagsResponse(tags=["tag1", "tag2", "tag3"])
        assert response.tags == ["tag1", "tag2", "tag3"]

        # Empty tags should be valid
        empty_response = TagsResponse(tags=[])
        assert empty_response.tags == []


class TestWeaviateUpsertAPI:
    async def test_upsert_weaviate_resource(self, client, mock_weaviate_vector_db):
        payload = {
            "namespace_id": "ns_1",
            "title": "Doc",
            "content": "hello world",
            "resource_id": "resource_1",
            "parent_id": "parent_1",
            "resource_tag_ids": ["tag_1", "tag_2"],
            "resource_tag_names": ["alpha", "beta"],
        }
        response = client.post(
            "/internal/api/v1/wizard/upsert_weaviate/resource", json=payload
        )
        assert response.status_code == 200
        assert response.json() == {"success": True}
        mock_weaviate_vector_db.remove_chunks.assert_called_once_with(
            "ns_1", "resource_1"
        )
        mock_weaviate_vector_db.insert_chunks.assert_called_once()
        chunks = mock_weaviate_vector_db.insert_chunks.call_args.args[1]
        assert len(chunks) == 1
        assert isinstance(chunks[0], Chunk)
        assert chunks[0].resource_tag_ids == ["tag_1", "tag_2"]
        assert chunks[0].resource_tag_names == ["alpha", "beta"]

    async def test_upsert_weaviate_message(self, client, mock_weaviate_vector_db):
        payload = {
            "namespace_id": "ns_1",
            "user_id": "user_1",
            "message": {
                "conversation_id": "conversation_1",
                "message_id": "message_1",
                "message": {"role": "user", "content": "hello"},
            },
        }
        response = client.post(
            "/internal/api/v1/wizard/upsert_weaviate/message", json=payload
        )
        assert response.status_code == 200
        assert response.json() == {"success": True}
        mock_weaviate_vector_db.upsert_message.assert_called_once()


class TestRecommendQuestionsAPI:
    """Test cases for /recommend_questions endpoint"""

    @pytest.fixture
    def mock_question_recommender(self, monkeypatch):
        from omnibox_wizard.wizard.api import internal
        from omnibox_wizard.worker.agent.question_recommender import (
            QuestionRecommendOutput,
            RecommendedQuestion,
        )

        mock_agent = MagicMock()
        mock_agent.ainvoke = AsyncMock(
            return_value=QuestionRecommendOutput(
                questions=[
                    RecommendedQuestion(
                        question="帮我把 AI 知识库相关资源都打上 AI 知识库标签",
                        intent="tag_operation",
                        reason="用户近期有多个 AI 知识库相关资源",
                    ),
                ]
            )
        )
        # The module-level global is annotation-only before init() runs.
        monkeypatch.setattr(internal, "question_recommender", mock_agent, raising=False)
        return mock_agent

    async def test_recommend_questions(self, client, mock_question_recommender):
        response = client.post(
            "/internal/api/v1/wizard/recommend_questions",
            json={
                "namespace_id": "ns_1",
                "user_id": "user_1",
                "context": {
                    "recent_resources": [
                        {
                            "name": "AI 知识库搭建方案",
                            "resource_type": "doc",
                            "metadata": {"source": "web"},
                            "tags": ["技术"],
                            "content": "本文介绍如何从零搭建团队 AI 知识库……",
                            "created_at": "2026-07-01T00:00:00.000Z",
                            "updated_at": "2026-07-05T12:00:00.000Z",
                        }
                    ],
                    "recent_tags": ["技术"],
                    "recent_questions": [],
                },
                "max_questions": 3,
            },
        )

        assert response.status_code == 200
        data = response.json()
        assert len(data["questions"]) == 1
        assert (
            data["questions"][0]["question"]
            == "帮我把 AI 知识库相关资源都打上 AI 知识库标签"
        )
        assert data["questions"][0]["intent"] == "tag_operation"
        assert data["questions"][0]["reason"] == "用户近期有多个 AI 知识库相关资源"
        mock_question_recommender.ainvoke.assert_awaited_once()
        input_arg = mock_question_recommender.ainvoke.call_args.args[0]
        assert len(input_arg.recent_resources) == 1
        resource = input_arg.recent_resources[0]
        assert resource.name == "AI 知识库搭建方案"
        assert resource.resource_type == "doc"
        assert resource.metadata == {"source": "web"}
        assert resource.tags == ["技术"]
        assert resource.content == "本文介绍如何从零搭建团队 AI 知识库……"
        assert resource.created_at == "2026-07-01T00:00:00.000Z"
        assert resource.updated_at == "2026-07-05T12:00:00.000Z"
        assert input_arg.recent_tags == ["技术"]
        assert input_arg.recent_questions == []
        assert input_arg.max_questions == 3

    async def test_recommend_questions_missing_required_fields(
        self, client, mock_question_recommender
    ):
        response = client.post(
            "/internal/api/v1/wizard/recommend_questions",
            json={"context": {"recent_resources": []}},
        )
        assert response.status_code == 422

    async def test_recommend_questions_defaults(
        self, client, mock_question_recommender
    ):
        response = client.post(
            "/internal/api/v1/wizard/recommend_questions",
            json={"namespace_id": "ns_1", "user_id": "user_1"},
        )

        assert response.status_code == 200
        input_arg = mock_question_recommender.ainvoke.call_args.args[0]
        assert input_arg.recent_resources == []
        assert input_arg.recent_tags == []
        assert input_arg.recent_questions == []
        assert input_arg.max_questions == 3

    async def test_recommend_questions_truncates_to_max(
        self, client, mock_question_recommender
    ):
        from omnibox_wizard.worker.agent.question_recommender import (
            QuestionRecommendOutput,
            RecommendedQuestion,
        )

        mock_question_recommender.ainvoke = AsyncMock(
            return_value=QuestionRecommendOutput(
                questions=[
                    RecommendedQuestion(
                        question=f"question {i}", intent="qa", reason=f"reason {i}"
                    )
                    for i in range(5)
                ]
            )
        )

        response = client.post(
            "/internal/api/v1/wizard/recommend_questions",
            json={"namespace_id": "ns_1", "user_id": "user_1", "max_questions": 2},
        )

        assert response.status_code == 200
        data = response.json()
        assert len(data["questions"]) == 2
