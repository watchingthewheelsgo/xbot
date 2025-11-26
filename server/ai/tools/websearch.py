import asyncio
from socket import AddressFamily

import aiohttp

from server.ai.tools.base import BaseTool


class WebFetcher(BaseTool):
    def __init__(self, timeout: int = 30):
        self.timeout = aiohttp.ClientTimeout(total=timeout)

    async def execute(self, urls: list[str]) -> dict:
        """
        并发获取多个URL的内容

        Args:
            urls: URL列表

        Returns:
            字典，格式为 {url: {"content": str} 或 {"error": str}}
        """
        # 创建连接器，配置DNS和SSL
        connector = aiohttp.TCPConnector(
            family=AddressFamily.AF_INET,  # 支持IPv4和IPv6
            ssl=False,  # 如果需要验证SSL，设置为True
        )

        async with aiohttp.ClientSession(
            connector=connector, timeout=self.timeout
        ) as session:
            # 创建任务
            tasks = [self._fetch_single(session, url) for url in urls]
            responses = await asyncio.gather(*tasks, return_exceptions=True)

            # 处理结果
            results = {}
            for url, resp in zip(urls, responses):
                if isinstance(resp, BaseException):
                    results[url] = {"error": str(resp)}
                else:
                    results[url] = resp

        return results

    async def _fetch_single(self, session: aiohttp.ClientSession, url: str) -> dict:
        """
        获取单个URL的内容

        Args:
            session: aiohttp ClientSession
            url: 要获取的URL

        Returns:
            {"content": str} 或 {"error": str}
        """
        try:
            async with session.get(url) as resp:
                resp.raise_for_status()
                text = await resp.text()
                return {"content": text}
        except aiohttp.ClientError as e:
            return {"error": f"Client error: {str(e)}"}
        except asyncio.TimeoutError:
            return {"error": "Request timeout"}
        except Exception as e:
            return {"error": f"Unexpected error: {str(e)}"}
