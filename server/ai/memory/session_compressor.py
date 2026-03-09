"""
会话压缩器 - 参考实现

从对话历史中提取长期记忆，包括：
- 用户偏好
- 实体/项目状态
- 事件/决策记录
- 模式/经验

设计原则：
1. 记忆粒度：每个记忆代表一个独立概念
2. 三层结构：L0(摘要), L1(概述), L2(详细)
3. 自动去重：向量相似度 + LLM 决策
4. 热度评分：结合频率和新鲜度
"""

import json
import math
from dataclasses import dataclass, field
from datetime import datetime
from typing import List, Dict, Any, Optional, Tuple
from loguru import logger


# ============================================================================
# Memory Category Types
# ============================================================================


class MemoryCategory(str):
    """记忆分类（参考 OpenViking）"""

    # 用户侧记忆
    PROFILE = "profile"  # 用户画像（合并到 profile.md）
    PREFERENCE = "preference"  # 偏好设置（按 facet 独立更新）
    ENTITY = "entity"  # 实体状态（项目/人物/概念）
    EVENT = "event"  # 事件记录（决策/里程碑）

    # Agent 侧记忆
    CASE = "case"  # 案例（问题-解决方案）
    PATTERN = "pattern"  # 模式（可复用流程）
    TOOL = "tool"  # 工具使用统计
    SKILL = "skill"  # 技能执行工作流


# ============================================================================
# Memory Level Types
# ============================================================================


class MemoryLevel(str):
    """记忆层级（参考 OpenViking）"""

    L0 = "l0"  # 抽象：单句摘要用于索引
    L1 = "l1"  # 概览：结构化 Markdown 摘要
    L2 = "l2"  # 内容：自由 Markdown 详细叙述


# ============================================================================
# Memory Extraction Result
# ============================================================================


@dataclass
class ExtractedMemory:
    """提取的记忆"""

    category: str  # MemoryCategory 值
    level: str  # MemoryLevel 值
    summary: str  # L0: 单句摘要
    overview: str  # L1: 结构化概述
    content: str  # L2: 详细内容
    tags: List[str] = field(default_factory=list)
    importance: int = 50  # 0-100
    entities: List[str] = field(default_factory=list)  # 提取的实体


@dataclass
class MemoryExtractionResult:
    """记忆提取结果"""

    memories: List[ExtractedMemory]
    session_summary: str  # 会话整体摘要
    topic: str  # 对话主题
    sentiment: str  # 情感倾向
    participants: List[str] = field(default_factory=list)


# ============================================================================
# Session Compressor
# ============================================================================


class SessionCompressor:
    """
    会话压缩器

    从对话历史中提取长期记忆：
    1. 分析对话内容
    2. 识别重要信息
    3. 分类为不同记忆类型
    4. 生成三层结构
    5. 返回提取结果
    """

    # 最小消息数触发记忆提取
    MIN_MESSAGES_FOR_EXTRACTION = 5

    # 每类记忆的最大提取数量
    MAX_MEMORIES_PER_CATEGORY = 5

    def __init__(self, llm_client=None):
        self.llm_client = llm_client

    async def compress_session(
        self,
        messages: List[Dict[str, Any]],
        chat_id: str,
        namespace: str = "chat",
    ) -> MemoryExtractionResult:
        """
        压缩会话，提取记忆

        Args:
            messages: 对话消息列表
            chat_id: 聊天 ID
            namespace: 命名空间

        Returns:
            MemoryExtractionResult: 提取结果
        """
        # 消息数量不足时不提取
        if len(messages) < self.MIN_MESSAGES_FOR_EXTRACTION:
            logger.debug(
                f"Not enough messages for extraction: {len(messages)} < {self.MIN_MESSAGES_FOR_EXTRACTION}"
            )
            return MemoryExtractionResult(
                memories=[], session_summary="", topic="", sentiment="", participants=[]
            )

        # 构建对话文本
        dialogue_text = self._build_dialogue_text(messages)

        try:
            # 使用 LLM 提取记忆
            if self.llm_client:
                return await self._extract_with_llm(dialogue_text, chat_id, namespace)
            else:
                # Fallback: 简单规则提取
                return await self._extract_with_rules(dialogue_text, chat_id, namespace)

        except Exception as e:
            logger.error(f"Failed to extract memories: {e}")
            # 返回空结果
            return MemoryExtractionResult(
                memories=[], session_summary="", topic="", sentiment="", participants=[]
            )

    def _build_dialogue_text(self, messages: List[Dict[str, Any]]) -> str:
        """构建对话文本"""
        lines = []
        for msg in messages:
            role = msg.get("role", "unknown")
            content = msg.get("content", "")

            if not content:
                continue

            if role == "user":
                lines.append(f"用户: {content}")
            elif role == "assistant":
                lines.append(f"助手: {content}")
            elif role == "tool":
                tool_name = msg.get("tool_calls", [{}])[0].get("tool_name", "")
                result = msg.get("content", "")
                lines.append(f"[工具: {tool_name}] {result}")
            else:
                lines.append(f"{role}: {content}")

        return "\n".join(lines)

    async def _extract_with_llm(
        self, dialogue: str, chat_id: str, namespace: str
    ) -> MemoryExtractionResult:
        """使用 LLM 提取记忆"""
        prompt = self._get_extraction_prompt(dialogue)

        try:
            if self.llm_client is None:
                logger.warning("LLM client not available, using fallback")
                return self._extraction_fallback(chat_id, namespace)

            response = await self.llm_client.ask(
                messages=[{"role": "user", "content": prompt}],
                stream=False,
            )

            # 解析 LLM 响应
            return self._parse_extraction_response(response, chat_id, namespace)

        except Exception as e:
            logger.error(f"LLM extraction failed: {e}")
            return self._extraction_fallback(chat_id, namespace)

    def _get_extraction_prompt(self, dialogue: str) -> str:
        """获取记忆提取提示词"""
        return f"""分析以下对话，提取重要信息。

对话内容：
{dialogue}

请按以下格式返回 JSON：
{{
    "session_summary": "会话的整体摘要（1-2 句话）",
    "topic": "对话主题（简短）",
    "sentiment": "情感倾向 (positive/neutral/negative)",
    "participants": ["参与者列表"],
    "memories": [
        {{
            "category": "preference|entity|event|case|pattern",
            "summary": "L0: 单句摘要",
            "overview": "L1: 结构化概述",
            "content": "L2: 详细内容",
            "tags": ["tag1", "tag2"],
            "importance": 50,
            "entities": ["相关实体"]
        }}
    ]
}}

注意事项：
1. 只提取重要且可能对后续对话有帮助的信息
2. 每条记忆应该是独立、可重用的概念
3. category 说明：
   - preference: 用户偏好设置
   - entity: 项目/人物/概念的状态
   - event: 重要的决策或事件
   - case: 问题-解决方案案例
   - pattern: 可复用的流程或模式
4. importance 范围 0-100，越重要分数越高
5. 如果没有值得记录的信息，返回空 memories 数组

只返回 JSON，不要有其他文字。"""

    def _parse_extraction_response(
        self, response: str, chat_id: str, namespace: str
    ) -> MemoryExtractionResult:
        """解析 LLM 响应"""
        try:
            # 尝试提取 JSON
            json_start = response.find("{")
            json_end = response.rfind("}") + 1

            if json_start >= 0 and json_end > json_start:
                json_str = response[json_start:json_end]
                data = json.loads(json_str)

                # 转换为提取结果
                memories = []
                for mem_data in data.get("memories", []):
                    mem = ExtractedMemory(
                        category=mem_data["category"],
                        level="l2",  # 默认使用 L2
                        summary=mem_data["summary"],
                        overview=mem_data["overview"],
                        content=mem_data["content"],
                        tags=mem_data.get("tags", []),
                        importance=mem_data.get("importance", 50),
                        entities=mem_data.get("entities", []),
                    )
                    memories.append(mem)

                return MemoryExtractionResult(
                    memories=memories,
                    session_summary=data.get("session_summary", ""),
                    topic=data.get("topic", ""),
                    sentiment=data.get("sentiment", "neutral"),
                    participants=data.get("participants", []),
                )

        except (json.JSONDecodeError, KeyError, ValueError) as e:
            logger.warning(f"Failed to parse extraction response: {e}")

        # Fallback
        return self._extraction_fallback(chat_id, namespace)

    def _extraction_fallback(
        self, chat_id: str, namespace: str
    ) -> MemoryExtractionResult:
        """提取失败时的回退"""
        return MemoryExtractionResult(
            memories=[],
            session_summary="",
            topic="",
            sentiment="neutral",
            participants=[],
        )

    async def _extract_with_rules(
        self, dialogue: str, chat_id: str, namespace: str
    ) -> MemoryExtractionResult:
        """基于规则提取记忆（回退方案）"""
        # 简单规则提取
        memories = []

        # 提取偏好模式
        if "不要" in dialogue or "希望" in dialogue or "喜欢" in dialogue:
            memories.append(
                ExtractedMemory(
                    category=MemoryCategory.PREFERENCE,
                    level="l1",
                    summary="用户偏好记录",
                    overview="用户表达了偏好设置",
                    content=dialogue[:200] + "...",
                    importance=60,
                    tags=["preference"],
                )
            )

        # 提取工具使用
        if "新闻" in dialogue or "market" in dialogue or "crypto" in dialogue:
            memories.append(
                ExtractedMemory(
                    category=MemoryCategory.TOOL,
                    level="l1",
                    summary="工具使用记录",
                    overview="用户使用了数据查询工具",
                    content="用户查询了新闻或市场数据",
                    importance=40,
                    tags=["tool", "query"],
                )
            )

        return MemoryExtractionResult(
            memories=memories,
            session_summary="对话已记录",
            topic="general",
            sentiment="neutral",
            participants=[],
        )


# ============================================================================
# Memory Deduplicator
# ============================================================================


class MemoryDeduplicator:
    """
    记忆去重器

    使用向量相似度和 LLM 判断来决定记忆操作：
    - SKIP: 跳过现有记忆
    - CREATE: 创建新记忆
    - MERGE: 合并到现有记忆
    - DELETE: 删除现有记忆
    """

    # 相似度阈值
    SIMILARITY_THRESHOLD = 0.85

    # 支持合并的类别
    MERGEABLE_CATEGORIES = {
        MemoryCategory.PROFILE,
        MemoryCategory.PREFERENCE,
        MemoryCategory.ENTITY,
        MemoryCategory.PATTERN,
    }

    async def deduplicate(
        self,
        new_memory: ExtractedMemory,
        existing_memories: List[Any],
        llm_client=None,
    ) -> Tuple[str, Optional[str]]:
        """
        去重决策

        Args:
            new_memory: 新提取的记忆
            existing_memories: 现有记忆列表
            llm_client: LLM 客户端（用于智能决策）

        Returns:
            Tuple[action, memory_id]:
                action: "SKIP" | "CREATE" | "MERGE" | "DELETE"
                memory_id: 现有记忆的 ID（用于 MERGE/DELETE）
        """
        # 如果没有现有记忆，直接创建
        if not existing_memories:
            return "CREATE", None

        # 对于 profile，总是合并
        if new_memory.category == MemoryCategory.PROFILE:
            return "MERGE", self._find_profile_id(existing_memories)

        # 简单去重：检查相似度
        for existing in existing_memories:
            if self._is_similar(new_memory, existing):
                if new_memory.category in self.MERGEABLE_CATEGORIES:
                    return "MERGE", existing.id
                else:
                    return "SKIP", None

        # 如果有 LLM，使用智能决策
        if llm_client:
            return await self._llm_deduplicate_decision(
                new_memory, existing_memories, llm_client
            )

        # 默认创建
        return "CREATE", None

    def _find_profile_id(self, memories: List[Any]) -> Optional[str]:
        """查找 profile 记忆 ID"""
        for mem in memories:
            if mem.type.value == "reference" and mem.key == "profile":
                return mem.id
        return None

    def _is_similar(self, new_memory: ExtractedMemory, existing_memory: Any) -> bool:
        """检查记忆是否相似（简单基于内容）"""
        new_content = new_memory.summary.lower()
        existing_content = existing_memory.value.lower()

        # 简单字符串包含检查
        if new_content in existing_content or existing_content in new_content:
            return True

        # 检查关键实体
        for entity in new_memory.entities:
            if entity.lower() in existing_content:
                return True

        return False

    async def _llm_deduplicate_decision(
        self,
        new_memory: ExtractedMemory,
        existing_memories: List[Any],
        llm_client,
    ) -> Tuple[str, Optional[str]]:
        """使用 LLM 做出去重决策"""
        # 构建现有记忆摘要
        existing_summaries = []
        for mem in existing_memories[:10]:  # 限制数量避免超长
            existing_summaries.append(f"[{mem.id}] {mem.type.value}: {mem.value[:100]}")

        new_summary = f"新记忆: {new_memory.category} - {new_memory.summary}"

        prompt = f"""比较新记忆和现有记忆，决定操作。

新记忆：
{new_summary}

现有记忆：
{chr(10).join(existing_summaries)}

请返回 JSON 格式的决策：
{{
    "action": "SKIP|CREATE|MERGE|DELETE",
    "memory_id": "现有记忆 ID (用于 MERGE/DELETE)",
    "reason": "决策原因"
}}

决策规则：
1. 如果新记忆与现有记忆相同/非常相似 → SKIP
2. 如果新记忆可以补充现有记忆 → MERGE
3. 如果新记忆与现有记忆冲突 → DELETE
4. 否则 → CREATE

只返回 JSON，不要有其他文字。"""

        try:
            if llm_client is None:
                logger.warning("LLM client not available, using fallback")
                return "CREATE", None

            response = await llm_client.ask(
                messages=[{"role": "user", "content": prompt}],
                stream=False,
            )

            # 解析响应
            json_start = response.find("{")
            json_end = response.rfind("}") + 1

            if json_start >= 0 and json_end > json_start:
                json_str = response[json_start:json_end]
                data = json.loads(json_str)

                return data["action"], data.get("memory_id")

        except Exception as e:
            logger.warning(f"LLM deduplication failed: {e}")

        # Fallback
        return "CREATE", None


# ============================================================================
# Hotness Calculator
# ============================================================================


class HotnessCalculator:
    """
    热度计算器

    计算记忆的热度分数 (0.0-1.0)：
    - 结合访问频率
    - 考虑时间衰减
    - 使用 sigmoid 函数平滑
    """

    @classmethod
    def calculate_hotness(
        cls,
        access_count: int,
        updated_at: datetime,
        created_at: Optional[datetime] = None,
        now: Optional[datetime] = None,
    ) -> float:
        """
        计算热度分数

        Args:
            access_count: 访问次数
            updated_at: 最后更新时间
            created_at: 创建时间（可选）
            now: 当前时间（可选，默认使用 datetime.now()）

        Returns:
            float: 热度分数 0.0-1.0
        """
        if now is None:
            now = datetime.now()

        # 访问分数：使用 sigmoid 平滑
        active_score = cls._sigmoid(math.log1p(access_count))

        # 时间衰减：指数衰减
        if created_at:
            age = (now - created_at).total_seconds() / 86400  # 天数
            time_decay = math.exp(-age / 30)  # 30 天半衰期
        else:
            age = (now - updated_at).total_seconds() / 86400
            time_decay = math.exp(-age / 30)

        # 综合分数：访问热度 × 时间新鲜度
        hotness = active_score * time_decay

        return max(0.0, min(1.0, hotness))

    @staticmethod
    def _sigmoid(x: float) -> float:
        """Sigmoid 函数"""
        return 1 / (1 + math.exp(-x))


# ============================================================================
# Context Builder
# ============================================================================


class ContextBuilder:
    """
    上下文构建器

    为对话构建上下文，包括：
    1. 会话历史（最近消息）
    2. 相关记忆（从长期记忆检索）
    3. 用户偏好
    4. 热度排序
    """

    def __init__(
        self,
        memory_store=None,
        llm_client=None,
    ):
        self.memory_store = memory_store
        self.llm_client = llm_client

    async def build_context(
        self,
        chat_id: str,
        namespace: str = "chat",
        max_recent_messages: int = 10,
        max_memories: int = 5,
    ) -> Dict[str, Any]:
        """
        构建对话上下文

        Args:
            chat_id: 聊天 ID
            namespace: 命名空间
            max_recent_messages: 最多包含多少条最近消息
            max_memories: 最多包含多少条相关记忆

        Returns:
            Dict with:
                - recent_messages: 最近消息列表
                - relevant_memories: 相关记忆列表（带热度）
                - user_profile: 用户画像
                - preferences: 用户偏好
                - context_summary: 上下文摘要
        """
        now = datetime.now()

        # 1. 获取用户偏好记忆
        preferences = []
        profile = None

        if self.memory_store:
            # 获取偏好
            prefs = await self.memory_store.search_by_tags(
                tags=["preference"],
                limit=max_memories,
            )
            preferences = prefs

            # 获取 profile
            profile = await self.memory_store.get_by_key(
                "profile", scope="global", namespace=namespace
            )

        # 2. 计算热度并排序
        memories_with_hotness = []
        for mem in preferences:
            hotness = HotnessCalculator.calculate_hotness(
                access_count=mem.access_count,
                updated_at=mem.updated_at,
                now=now,
            )
            memories_with_hotness.append(
                {
                    "memory": mem,
                    "hotness": hotness,
                }
            )

        # 按热度排序
        memories_with_hotness.sort(key=lambda x: x["hotness"], reverse=True)

        # 取前 N 条
        relevant_memories = memories_with_hotness[:max_memories]

        return {
            "recent_messages": [],  # 由调用者填充
            "relevant_memories": relevant_memories,
            "user_profile": profile,
            "preferences": preferences,
            "context_summary": self._generate_context_summary(
                relevant_memories, profile
            ),
        }

    def _generate_context_summary(
        self, memories_with_hotness: List[Dict], profile
    ) -> str:
        """生成上下文摘要"""
        lines = ["用户上下文：", ""]

        # 添加偏好
        hot_mems = [m for m in memories_with_hotness if m["hotness"] > 0.3]
        if hot_mems:
            lines.append("相关偏好:")
            for item in hot_mems[:3]:
                mem = item["memory"]
                lines.append(f"- {mem.value[:100]}")

        # 添加 profile 摘要
        if profile:
            lines.append(f"用户画像: {profile.value[:200]}")

        return "\n".join(lines)
