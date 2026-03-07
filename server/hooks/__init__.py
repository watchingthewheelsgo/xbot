"""
Hook 系统模块
提供统一的 Hook 接口和管理器
"""

from .base import (
    Hook,
    HookResult,
    PreToolUseHookInput,
    PreToolUseHookOutput,
    PreCompactHookInput,
    PreCompactHookOutput,
    PreSendMessageHookInput,
    PreSendMessageHookOutput,
    PostSendMessageHookInput,
    TaskStartHookInput,
    TaskCompleteHookInput,
    DataFetchHookInput,
    DataFetchHookOutput,
)
from .manager import (
    HookManager,
    get_hook_manager,
)

__all__ = [
    "Hook",
    "HookResult",
    "PreToolUseHookInput",
    "PreToolUseHookOutput",
    "PreCompactHookInput",
    "PreCompactHookOutput",
    "PreSendMessageHookInput",
    "PreSendMessageHookOutput",
    "PostSendMessageHookInput",
    "TaskStartHookInput",
    "TaskCompleteHookInput",
    "DataFetchHookInput",
    "DataFetchHookOutput",
    "HookManager",
    "get_hook_manager",
]
