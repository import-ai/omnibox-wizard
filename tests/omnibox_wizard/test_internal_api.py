import pytest
from unittest.mock import AsyncMock, patch
from fastapi.testclient import TestClient
from fastapi import FastAPI

from omnibox_wizard.wizard.api.internal import internal_router
from omnibox_wizard.wizard.api.entity import CommonAITextRequest, TitleResponse, TagsResponse


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
    with patch('omnibox_wizard.wizard.api.internal.common_ai') as mock:
        yield mock


class TestTitleAPI:
    """Test cases for /title endpoint with lang parameter"""

    @pytest.mark.parametrize("text,lang,expected_title", [
        ("What is AI?", "English", "Understanding Artificial Intelligence"),
    ])
    async def test_title_with_lang_parameter(self, client, mock_common_ai, text, lang, expected_title):
        """Test title generation with different language parameters"""
        # Mock the CommonAI title method
        mock_common_ai.title.return_value = expected_title
        
        # Make request
        response = client.post("/internal/api/v1/wizard/title", json={
            "text": text,
            "lang": lang
        })
        
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
        response = client.post("/internal/api/v1/wizard/title", json={
            "text": "测试文本"
        })
        
        assert response.status_code == 200
        response_data = response.json()
        assert response_data["title"] == expected_title
        
        # Verify default lang was used
        call_args = mock_common_ai.title.call_args
        assert call_args[1]["lang"] == "简体中文"

    async def test_title_invalid_lang(self, client, mock_common_ai):
        """Test title generation with invalid language parameter"""
        # Should return validation error for invalid lang
        response = client.post("/internal/api/v1/wizard/title", json={
            "text": "测试文本",
            "lang": "InvalidLanguage"
        })
        
        assert response.status_code == 422  # Validation error

    async def test_title_missing_text(self, client, mock_common_ai):
        """Test title generation without text parameter"""
        response = client.post("/internal/api/v1/wizard/title", json={
            "lang": "English"
        })
        
        assert response.status_code == 422  # Validation error

    async def test_title_response_format(self, client, mock_common_ai):
        """Test that title response follows correct format"""
        expected_title = "Test Title"
        mock_common_ai.title.return_value = expected_title
        
        response = client.post("/internal/api/v1/wizard/title", json={
            "text": "Test text",
            "lang": "English"
        })
        
        assert response.status_code == 200
        response_data = response.json()
        
        # Verify response structure
        assert "title" in response_data
        assert isinstance(response_data["title"], str)
        assert response_data["title"] == expected_title


class TestTagsAPI:
    """Test cases for /tags endpoint with lang parameter"""

    @pytest.mark.parametrize("text,lang,expected_tags", [
        ("Machine Learning and AI", "English", ["machine-learning", "artificial-intelligence", "technology"])
    ])
    async def test_tags_with_lang_parameter(self, client, mock_common_ai, text, lang, expected_tags):
        """Test tags generation with different language parameters"""
        # Mock the CommonAI tags method
        mock_common_ai.tags.return_value = expected_tags
        
        # Make request
        response = client.post("/internal/api/v1/wizard/tags", json={
            "text": text,
            "lang": lang
        })
        
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
        response = client.post("/internal/api/v1/wizard/tags", json={
            "text": "测试文本"
        })
        
        assert response.status_code == 200
        response_data = response.json()
        assert response_data["tags"] == expected_tags
        
        # Verify default lang was used
        call_args = mock_common_ai.tags.call_args
        assert call_args[1]["lang"] == "简体中文"

    async def test_tags_invalid_lang(self, client, mock_common_ai):
        """Test tags generation with invalid language parameter"""
        response = client.post("/internal/api/v1/wizard/tags", json={
            "text": "测试文本",
            "lang": "InvalidLanguage"
        })
        
        assert response.status_code == 422  # Validation error

    async def test_tags_missing_text(self, client, mock_common_ai):
        """Test tags generation without text parameter"""
        response = client.post("/internal/api/v1/wizard/tags", json={
            "lang": "English"
        })
        
        assert response.status_code == 422  # Validation error

    async def test_tags_response_format(self, client, mock_common_ai):
        """Test that tags response follows correct format"""
        expected_tags = ["tag1", "tag2", "tag3"]
        mock_common_ai.tags.return_value = expected_tags
        
        response = client.post("/internal/api/v1/wizard/tags", json={
            "text": "Test text",
            "lang": "English"
        })
        
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
        
        response = client.post("/internal/api/v1/wizard/tags", json={
            "text": "No tags text",
            "lang": "English"
        })
        
        assert response.status_code == 200
        response_data = response.json()
        assert response_data["tags"] == []


class TestLanguageConsistency:
    """Test language consistency across both endpoints"""

    @pytest.mark.parametrize("text,lang", [
        ("Artificial Intelligence Development", "English"),
    ])
    async def test_consistent_lang_usage(self, client, mock_common_ai, text, lang):
        """Test that both endpoints use the same lang parameter consistently"""
        mock_common_ai.title.return_value = "Test Title"
        mock_common_ai.tags.return_value = ["tag1", "tag2"]
        
        # Test title endpoint
        title_response = client.post("/internal/api/v1/wizard/title", json={
            "text": text,
            "lang": lang
        })
        
        # Test tags endpoint
        tags_response = client.post("/internal/api/v1/wizard/tags", json={
            "text": text,
            "lang": lang
        })
        
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
        client.post("/internal/api/v1/wizard/title", json={
            "text": "test",
            "lang": "English"
        })
        
        client.post("/internal/api/v1/wizard/tags", json={
            "text": "test", 
            "lang": "English"
        })
        
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