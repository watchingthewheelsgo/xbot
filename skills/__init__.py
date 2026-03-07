"""
技能系统模块
提供技能发现、应用和管理功能
"""

from .protocol import (
    SkillCategory,
    OperationType,
    Dependency,
    FileOperation,
    Migration,
    SkillManifest,
    SkillError,
    SkillApplyResult,
)
from .parser import SkillParser
from .applier import SkillApplier
from .manager import SkillManager, get_skill_manager

__all__ = [
    # 协议
    "SkillCategory",
    "OperationType",
    "Dependency",
    "FileOperation",
    "Migration",
    "SkillManifest",
    "SkillError",
    "SkillApplyResult",
    # 解析器
    "SkillParser",
    # 应用器
    "SkillApplier",
    # 管理器
    "SkillManager",
    "get_skill_manager",
]
