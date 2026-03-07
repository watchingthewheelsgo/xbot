"""
Hook 管理器
管理所有已注册的 Hook，提供统一的调用接口
"""

from typing import Dict, List, Optional, Any
from datetime import datetime
from loguru import logger

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
)


class HookManager:
    """
    Hook 管理器

    Hook 类型：
    - pre_tool_use: 工具使用前
    - pre_compact: 会话压缩前
    - pre_send_message: 发送消息前
    - post_send_message: 发送消息后
    - task_start: 任务开始前
    - task_complete: 任务完成后
    - data_fetch: 数据获取
    """

    # Hook 点枚举
    HOOK_PRE_TOOL_USE = "pre_tool_use"
    HOOK_PRE_COMPACT = "pre_compact"
    HOOK_PRE_SEND_MESSAGE = "pre_send_message"
    HOOK_POST_SEND_MESSAGE = "post_send_message"
    HOOK_TASK_START = "task_start"
    HOOK_TASK_COMPLETE = "task_complete"
    HOOK_DATA_FETCH = "data_fetch"

    def __init__(self):
        # Hook 注册表：{hook_point: [hooks]}
        self._hooks: Dict[str, List[Hook]] = {
            self.HOOK_PRE_TOOL_USE: [],
            self.HOOK_PRE_COMPACT: [],
            self.HOOK_PRE_SEND_MESSAGE: [],
            self.HOOK_POST_SEND_MESSAGE: [],
            self.HOOK_TASK_START: [],
            self.HOOK_TASK_COMPLETE: [],
            self.HOOK_DATA_FETCH: [],
        }

        # Hook 执行统计
        self._stats = {
            "total_executions": 0,
            "total_success": 0,
            "total_skipped": 0,
            "total_failed": 0,
            "execution_times": [],
        }

        # Hook 配置
        self._enabled = True
        self._fail_fast = False  # 快速失败模式（单个 Hook 失败后停止该点所有 Hook）
        self._hook_enabled_states: Dict[str, bool] = {}  # 跟踪每个 Hook 的启用状态

    def register(self, hook: Hook, hook_point: Optional[str] = None) -> None:
        """
        注册 Hook

        Args:
            hook: Hook 实例
            hook_point: Hook 点类型，如果未指定则使用 hook.name
        """
        point = hook_point or hook.name
        if point not in self._hooks:
            logger.warning(f"Unknown hook point: {point}")
            return

        self._hooks[point].append(hook)
        logger.info(f"Registered hook '{hook.name}' at point '{point}'")

    def unregister(self, hook: Hook, hook_point: Optional[str] = None) -> None:
        """
        注销 Hook

        Args:
            hook: Hook 实例
            hook_point: Hook 点类型
        """
        point = hook_point or hook.name
        if point in self._hooks:
            try:
                self._hooks[point].remove(hook)
                logger.info(f"Unregistered hook '{hook.name}' from point '{point}'")
            except ValueError:
                pass

    def get_hooks(self, hook_point: str) -> List[Hook]:
        """获取指定 Hook 点的所有 Hook"""
        return self._hooks.get(hook_point, []).copy()

    def enable_hook(self, hook_name: str, enabled: bool) -> None:
        """启用或禁用指定 Hook"""
        for hooks in self._hooks.values():
            for hook in hooks:
                if hook.name == hook_name:
                    self._hook_enabled_states[hook_name] = enabled
                    logger.debug(
                        f"Hook '{hook_name}' {'enabled' if enabled else 'disabled'}"
                    )
                    return
        logger.warning(f"Hook '{hook_name}' not found")

    def is_hook_enabled(self, hook: Hook) -> bool:
        """检查 Hook 是否启用"""
        return self._hook_enabled_states.get(hook.name, hook.enabled)

    def enable_all(self, enabled: bool) -> None:
        """启用或禁用所有 Hook"""
        self._enabled = enabled
        for hooks in self._hooks.values():
            for hook in hooks:
                self._hook_enabled_states[hook.name] = enabled
        logger.info(f"All hooks {'enabled' if enabled else 'disabled'}")

    def set_fail_fast(self, fail_fast: bool) -> None:
        """设置快速失败模式"""
        self._fail_fast = fail_fast
        logger.debug(f"Fail-fast mode: {'enabled' if fail_fast else 'disabled'}")

    def get_stats(self) -> Dict[str, Any]:
        """获取 Hook 执行统计"""
        self._stats["registered_hooks"] = sum(len(h) for h in self._hooks.values())
        return self._stats.copy()

    def _record_execution(self, hook: Hook, success: bool, duration_ms: int) -> None:
        """记录 Hook 执行"""
        self._stats["total_executions"] += 1
        if success:
            self._stats["total_success"] += 1
        else:
            self._stats["total_failed"] += 1

        self._stats["execution_times"].append(
            {
                "hook": hook.name,
                "duration_ms": duration_ms,
                "success": success,
            }
        )

    async def execute_hooks(self, hook_point: str, input_data: Any) -> HookResult:
        """
        执行指定 Hook 点的所有 Hook

        Args:
            hook_point: Hook 点类型
            input_data: Hook 输入数据

        Returns:
            HookResult（最后一个 Hook 的结果）
        """
        if not self._enabled:
            return HookResult(success=True)

        hooks = self.get_hooks(hook_point)
        if not hooks:
            logger.debug(f"No hooks registered for point: {hook_point}")
            return HookResult(success=True)

        last_modified = input_data
        should_skip = False

        for hook in hooks:
            if not hook.enabled:
                logger.debug(f"Hook '{hook.name}' is disabled, skipping")
                continue

            start_time = datetime.now()

            try:
                result = await hook.execute(input_data)

                # 处理返回结果
                if isinstance(result, HookResult):
                    if result.should_skip:
                        should_skip = True
                        logger.debug(f"Hook '{hook.name}' requested skip")
                    elif result.modified_data is not None:
                        last_modified = result.modified_data
                        logger.debug(f"Hook '{hook.name}' modified data")

                    success = result.success and not result.should_skip

                elif isinstance(result, bool):
                    success = result
                    # 对于简单 Hook，False 表示跳过
                    if not success:
                        should_skip = True

                elif result is None:
                    success = True

                else:
                    # 其他类型，视为成功
                    success = True

                # 更新统计
                duration_ms = int((datetime.now() - start_time).total_seconds() * 1000)
                self._record_execution(hook, success, duration_ms)

                # 快速失败模式
                if not success and self._fail_fast:
                    logger.warning(
                        f"Hook '{hook.name}' failed, "
                        f"stopping remaining hooks for point {hook_point} "
                        f"(fail-fast mode)"
                    )
                    break

            except Exception as e:
                logger.error(f"Hook '{hook.name}' execution failed: {e}", exc_info=True)
                duration_ms = int((datetime.now() - start_time).total_seconds() * 1000)
                self._record_execution(hook, False, duration_ms)

                if self._fail_fast:
                    break

        return HookResult(
            success=not should_skip and self._enabled,
            modified_data=last_modified if last_modified != input_data else None,
            should_skip=should_skip,
        )

    async def execute_pre_tool_use(
        self, input_data: PreToolUseHookInput
    ) -> PreToolUseHookOutput:
        """执行工具使用前 Hook"""
        result = await self.execute_hooks(self.HOOK_PRE_TOOL_USE, input_data)

        output = PreToolUseHookOutput(
            modified_input=result.modified_data
            if isinstance(result.modified_data, dict)
            else None,
            should_skip=result.should_skip,
        )

        # 检查是否有 Hook 返回了环境变量
        if isinstance(result.modified_data, dict):
            env_vars = result.modified_data.get("environment_vars")
            if env_vars:
                output.environment_vars = env_vars

        return output

    async def execute_pre_compact(
        self, input_data: PreCompactHookInput
    ) -> PreCompactHookOutput:
        """执行会话压缩前 Hook"""
        result = await self.execute_hooks(self.HOOK_PRE_COMPACT, input_data)

        return PreCompactHookOutput(
            should_archive=result.success and not result.should_skip,
            archive_path=result.modified_data
            if isinstance(result.modified_data, str)
            else None,
            custom_summary=result.modified_data
            if isinstance(result.modified_data, str)
            else None,
        )

    async def execute_pre_send_message(
        self, input_data: PreSendMessageHookInput
    ) -> PreSendMessageHookOutput:
        """执行发送消息前 Hook"""
        result = await self.execute_hooks(self.HOOK_PRE_SEND_MESSAGE, input_data)

        return PreSendMessageHookOutput(
            modified_content=result.modified_data
            if isinstance(result.modified_data, str)
            else None,
            should_skip=result.should_skip,
            alternative_channel=result.modified_data
            if isinstance(result.modified_data, str)
            else None,
        )

    async def execute_post_send_message(
        self, input_data: PostSendMessageHookInput
    ) -> HookResult:
        """执行发送消息后 Hook"""
        result = await self.execute_hooks(self.HOOK_POST_SEND_MESSAGE, input_data)
        return result

    async def execute_task_start(self, input_data: TaskStartHookInput) -> HookResult:
        """执行任务开始 Hook"""
        return await self.execute_hooks(self.HOOK_TASK_START, input_data)

    async def execute_task_complete(
        self, input_data: TaskCompleteHookInput
    ) -> HookResult:
        """执行任务完成 Hook"""
        return await self.execute_hooks(self.HOOK_TASK_COMPLETE, input_data)

    async def execute_data_fetch(self, input_data: DataFetchHookInput) -> HookResult:
        """执行数据获取 Hook"""
        return await self.execute_hooks(self.HOOK_DATA_FETCH, input_data)


# 全局 Hook 管理器实例
_global_hook_manager: Optional[HookManager] = None


def get_hook_manager() -> HookManager:
    """获取或创建全局 Hook 管理器实例"""
    global _global_hook_manager
    if _global_hook_manager is None:
        _global_hook_manager = HookManager()
    return _global_hook_manager
