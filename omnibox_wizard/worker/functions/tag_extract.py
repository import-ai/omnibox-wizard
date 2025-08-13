from omnibox_wizard.common.trace_info import TraceInfo
from omnibox_wizard.worker.config import WorkerConfig
from omnibox_wizard.worker.entity import Task
from omnibox_wizard.worker.functions.base_function import BaseFunction
from omnibox_wizard.wizard.grimoire.common_ai import CommonAI


class TagExtractFunction(BaseFunction):
    """Extract relevant tags from resource content using AI analysis."""
    
    def __init__(self, config: WorkerConfig):
        self.config = config
        self.ai = CommonAI(config=config.grimoire)

    async def run(self, task: Task, trace_info: TraceInfo) -> dict:
        """
        Extract tags from resource content.
        
        Expected task.input:
        - content: The markdown/text content to analyze
        - title: Resource title for context
        - resource_type: Type of resource (doc, link, file, folder)
        
        Returns:
        - tags: List of suggested tag strings
        """
        trace_info.info({"message": "Starting tag extraction"})
        
        content = task.input.get("content", "")
        title = task.input.get("title", "")
        resource_type = task.input.get("resource_type", "")
        
        if not content and not title:
            trace_info.warning({"message": "No content or title provided for tag extraction"})
            return {"tags": []}
        
        # Prepare the prompt for tag extraction
        prompt = self._build_tag_extraction_prompt(content, title, resource_type)
        
        try:
            # Use the AI to extract tags
            response = await self.ai.chat_completion(
                messages=[{"role": "user", "content": prompt}],
                model="gpt-4o-mini",  # Use a fast, cost-effective model for tag extraction
                temperature=0.3  # Lower temperature for more consistent tag extraction
            )
            
            # Parse the response to extract tags
            tags = self._parse_tags_response(response)
            
            trace_info.info({
                "message": "Tag extraction completed", 
                "tags_count": len(tags),
                "tags": tags
            })
            
            return {"tags": tags}
            
        except Exception as e:
            trace_info.error({
                "message": "Error during tag extraction",
                "error": str(e)
            })
            # Return empty tags on error rather than failing the task
            return {"tags": []}
    
    def _build_tag_extraction_prompt(self, content: str, title: str, resource_type: str) -> str:
        """Build the prompt for tag extraction."""
        prompt = f"""Analyze the following content and extract relevant tags that would help categorize and find this resource.

Resource Type: {resource_type}
Title: {title}

Content:
{content[:2000]}  # Limit content to first 2000 chars to avoid token limits

Instructions:
1. Extract 3-8 relevant tags that best describe the content
2. Focus on topics, technologies, concepts, and categories mentioned
3. Use lowercase, single words or short phrases (2-3 words max)
4. Avoid overly generic tags like "document" or "text"
5. Return only the tags as a comma-separated list, nothing else

Example format: artificial intelligence, machine learning, python, data science, neural networks"""
        
        return prompt
    
    def _parse_tags_response(self, response: str) -> list[str]:
        """Parse the AI response to extract clean tag list."""
        if not response or not response.strip():
            return []
        
        # Clean the response and split by comma
        tags = [tag.strip().lower() for tag in response.strip().split(",")]
        
        # Filter out empty tags and limit length
        tags = [tag for tag in tags if tag and len(tag) <= 50]
        
        # Limit to maximum 10 tags
        return tags[:10]