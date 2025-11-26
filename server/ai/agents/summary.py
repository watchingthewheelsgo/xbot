from typing import Dict, Optional

from server.ai.agents.base import ToolCallAgent
from server.ai.schema import AgentState, Memory
from server.ai.tools.base import BaseTool
from server.ai.tools.websearch import WebFetcher


class SummaryAgent(ToolCallAgent):
    def __init__(self, llm=None, tools: Optional[Dict[str, BaseTool]] = None, **kwargs):
        super().__init__(**kwargs)
        self.memory = Memory()
        self.llm = llm
        self.tools = tools or {}
        self.web_fetcher = WebFetcher()
        self.state = AgentState.IDLE

    async def summarize(self, urls: list[str]) -> dict:
        """Main method to summarize URLs

        Args:
            urls: List of URLs to summarize

        Returns:
            Dictionary mapping URLs to their summaries: {url: summary_markdown}
        """
        try:
            self.state = AgentState.RUNNING

            content_map = await self._fetch_content(urls)

            summaries = {}
            for url in urls:
                if url in content_map and "error" not in content_map[url]:
                    content = content_map[url].get("content", "")
                    summary = await self._generate_summary(url, content)
                    summaries[url] = summary
                else:
                    error = content_map.get(url, {}).get("error", "Unknown error")
                    summaries[url] = f"Failed to fetch content: {error}"

            self.state = AgentState.FINISHED
            return summaries

        except Exception as e:
            self.state = AgentState.ERROR
            return {url: f"Error: {str(e)}" for url in urls}

    async def _fetch_content(self, urls: list[str]) -> dict:
        """Call WebFetcher to get content from URLs

        Args:
            urls: List of URLs to fetch

        Returns:
            Dictionary mapping URLs to their content: {url: {content: str or error: str}}
        """
        content_map = await self.web_fetcher.execute(urls)
        return content_map

    async def _generate_summary(self, url: str, content: str) -> str:
        """Generate Markdown summary for single URL using LLM

        Args:
            url: The source URL
            content: The webpage content to summarize

        Returns:
            Markdown formatted summary
        """
        if not self.llm:
            return self._generate_default_summary(url, content)

        prompt = self._build_summary_prompt(url, content)
        summary = await self.llm.ask(prompt)

        return summary

    def _build_summary_prompt(self, url: str, content: str) -> str:
        """Build a prompt for LLM to generate summary

        Args:
            url: The source URL
            content: The webpage content

        Returns:
            Formatted prompt string
        """
        limited_content = content[:2000]
        template = f"""Generate a Markdown summary of the following webpage content.

URL: {url}
Content:
{limited_content}

Return the summary in Markdown format (only return Markdown, no explanations):
# Summary - [Page Title]

**Source**: [{url}]({url})

## Main Content
[1-3 paragraphs of key content]

## Key Points
- Point 1
- Point 2
- Point 3
"""
        return template

    def _generate_default_summary(self, url: str, content: str) -> str:
        """Generate a basic summary when LLM is not available

        Args:
            url: The source URL
            content: The webpage content

        Returns:
            Basic Markdown formatted summary
        """
        lines = content.split("\n")
        main_content = "\n".join(lines[:5])

        summary = f"""# Summary - [Web Content]

**Source**: [{url}]({url})

## Main Content
{main_content if main_content.strip() else "Unable to extract main content"}

## Key Points
- Content fetched from {url}
- LLM not available for full summarization
- Please provide LLM instance for better summaries
"""
        return summary
