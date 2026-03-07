"""
IPC 管理器
管理主进程与工作进程/容器之间的通信
"""

import asyncio
import json
from pathlib import Path
from typing import Dict, Callable, Optional, Any
from datetime import datetime

from .protocol import (
    IPCMessage,
    IPCResponse,
    IPCEndpoint,
)

from loguru import logger


class IPCManager:
    """
    IPC 管理器

    特性：
    1. 基于文件系统的 IPC（适合容器内外通信）
    2. 按命名空间隔离
    3. 支持请求-响应模式
    4. 自动清理过期文件
    5. 支持消息广播
    """

    # IPC 目录
    IPC_BASE_DIR = Path("/tmp/xbot_ipc")
    POLL_INTERVAL = 0.5  # 秒

    def __init__(self, base_dir: Optional[Path] = None):
        self._base_dir = base_dir or self.IPC_BASE_DIR
        self._input_dir = self._base_dir / "input"
        self._output_dir = self._base_dir / "output"
        self._tasks_dir = self._base_dir / "tasks"
        self._control_dir = self._base_dir / "control"

        # 消息处理器注册
        self._message_handlers: Dict[str, Callable] = {}
        self._response_handlers: Dict[str, Dict[str, Callable]] = {}

        # 运行标志
        self._running = False
        self._cleanup_interval = 300  # 5分钟清理一次

        # 创建目录
        for dir_path in [
            self._input_dir,
            self._output_dir,
            self._tasks_dir,
            self._control_dir,
        ]:
            dir_path.mkdir(exist_ok=True, parents=True)

        logger.info(f"IPC Manager initialized with base_dir: {self._base_dir}")

    def register_message_handler(
        self, message_type: str, handler: Callable[[IPCMessage], Any]
    ) -> None:
        """
        注册 IPC 消息处理器

        Args:
            message_type: 消息类型
            handler: 处理函数
        """
        self._message_handlers[message_type] = handler
        logger.debug(f"Registered IPC message handler: {message_type}")

    def register_response_handler(
        self,
        message_type: str,
        correlation_id: str,
        handler: Callable[[IPCMessage], IPCResponse],
    ) -> None:
        """
        注册 IPC 响应处理器（用于请求-响应模式）

        Args:
            message_type: 消息类型
            correlation_id: 关联 ID
            handler: 处理函数
        """
        if correlation_id not in self._response_handlers:
            self._response_handlers[correlation_id] = {}
        self._response_handlers[correlation_id][message_type] = handler
        logger.debug(
            f"Registered IPC response handler: {message_type}:{correlation_id}"
        )

    def unregister_message_handler(self, message_type: str) -> None:
        """注销消息处理器"""
        if message_type in self._message_handlers:
            del self._message_handlers[message_type]
            logger.debug(f"Unregistered IPC message handler: {message_type}")

    def unregister_response_handler(
        self, message_type: str, correlation_id: str
    ) -> None:
        """注销响应处理器"""
        if correlation_id in self._response_handlers:
            if message_type in self._response_handlers[correlation_id]:
                del self._response_handlers[correlation_id][message_type]
            logger.debug(
                f"Unregistered IPC response handler: {message_type}:{correlation_id}"
            )

    async def send_message(
        self,
        namespace: str,
        message: IPCMessage,
    ) -> bool:
        """
        发送 IPC 消息

        Args:
            namespace: 目标命名空间
            message: IPC 消息对象

        Returns:
            True 如果成功发送，False 否则
        """
        namespace_dir = self._input_dir / namespace
        namespace_dir.mkdir(exist_ok=True)

        # 检查是否有关闭标记
        close_marker = namespace_dir / IPCEndpoint.CLOSE_FILE
        if close_marker.exists():
            logger.debug(f"IPC namespace {namespace} is closed, dropping message")
            return False

        # 写入消息文件（带时间戳保证唯一性）
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
        filename = f"{message.type}_{timestamp}.json"

        temp_file = namespace_dir / f"{filename}.tmp"
        final_file = namespace_dir / filename

        try:
            temp_file.write_text(json.dumps(message.to_dict()))
            temp_file.replace(final_file)
            logger.debug(f"IPC sent to {namespace}/{filename}: {message.type}")
            return True
        except Exception as e:
            logger.error(f"Failed to send IPC message: {e}")
            return False

    async def send_and_wait(
        self,
        namespace: str,
        message: IPCMessage,
        timeout: float = 30.0,
    ) -> Optional[IPCResponse]:
        """
        发送消息并等待响应（请求-响应模式）

        Args:
            namespace: 目标命名空间
            message: IPC 消息对象
            timeout: 超时时间（秒）

        Returns:
            响应对象，如果超时则返回 None
        """
        # 确保消息有关联 ID
        if not message.correlation_id:
            message.correlation_id = f"{message.type}_{datetime.now().timestamp()}"

        if not await self.send_message(namespace, message):
            return None

        correlation_id = message.correlation_id

        # 等待响应
        try:
            response_file = (
                self._output_dir / namespace / f"response_{message.correlation_id}.json"
            )
            start_time = datetime.now()

            while (datetime.now() - start_time).total_seconds() < timeout:
                if response_file.exists():
                    break
                await asyncio.sleep(0.1)

            if not response_file.exists():
                logger.warning(
                    f"IPC response timeout for {message.type}:{correlation_id}"
                )
                self.unregister_response_handler(message.type, correlation_id)
                return None

            # 读取响应
            response_data = json.loads(response_file.read_text())
            response = IPCResponse(**response_data)

            # 清理响应文件
            try:
                response_file.unlink()
            except Exception:
                pass

            self.unregister_response_handler(message.type, correlation_id)
            return response

        except Exception as e:
            logger.error(f"Error waiting for IPC response: {e}")
            self.unregister_response_handler(message.type, correlation_id)
            return None

    def _handle_response(self, message: IPCMessage, response: IPCResponse) -> None:
        """处理响应消息"""
        handler_key = f"{message.type}:{message.correlation_id}"
        if handler_key not in self._response_handlers:
            return

        handlers = self._response_handlers[handler_key]
        for handler in handlers.values():
            try:
                handler(message, response)
            except Exception as e:
                logger.error(f"IPC response handler error: {handler.__name__}: {e}")

    async def start(self) -> None:
        """启动 IPC 消息处理循环"""
        if self._running:
            logger.warning("IPC Manager already running")
            return

        self._running = True
        logger.info("Starting IPC message watcher")

        while self._running:
            try:
                await self._process_messages()
            except asyncio.CancelledError:
                logger.info("IPC Manager cancelled")
                break
            except Exception as e:
                logger.error(f"IPC Manager error: {e}", exc_info=True)

            await asyncio.sleep(self.POLL_INTERVAL)

    async def _process_messages(self) -> None:
        """处理所有 IPC 消息"""
        for namespace_dir in self._input_dir.iterdir():
            if not namespace_dir.is_dir():
                continue

            namespace = namespace_dir.name

            # 检查是否有关闭标记
            close_marker = namespace_dir / IPCEndpoint.CLOSE_FILE
            if close_marker.exists():
                logger.debug(f"IPC namespace {namespace} is closed")
                continue

            # 处理消息文件
            for msg_file in namespace_dir.glob("*.json"):
                # 跳过正在写入的临时文件
                if msg_file.name.endswith(".tmp"):
                    continue

                try:
                    message_data = json.loads(msg_file.read_text())
                    message = IPCMessage(**message_data)

                    # 调用相应的处理器
                    handler = self._message_handlers.get(message.type)
                    if handler:
                        try:
                            await handler(message)
                        except Exception as e:
                            logger.error(
                                f"IPC message handler error for {message.type}: {e}"
                            )

                    # 处理完成后删除消息文件
                    msg_file.unlink()

                except json.JSONDecodeError as e:
                    logger.error(
                        f"Failed to parse IPC message file: {msg_file.name}: {e}"
                    )
                    # 删除损坏的文件
                    try:
                        msg_file.unlink()
                    except Exception:
                        pass

    async def cleanup(self) -> None:
        """清理过期的 IPC 文件"""
        logger.debug("Running IPC cleanup")
        now = datetime.now()
        max_age = 3600  # 1小时

        for namespace_dir in self._input_dir.iterdir():
            if not namespace_dir.is_dir():
                continue

            for msg_file in namespace_dir.glob("*.json"):
                try:
                    # 获取文件修改时间
                    file_age = (
                        now - datetime.fromtimestamp(msg_file.stat().st_mtime)
                    ).total_seconds()

                    if file_age > max_age:
                        msg_file.unlink()
                        logger.debug(f"Cleaned up expired IPC file: {msg_file.name}")
                except Exception as e:
                    logger.debug(f"Error during IPC cleanup: {e}")

    def shutdown_namespace(self, namespace: str) -> None:
        """关闭指定命名空间的 IPC"""
        namespace_dir = self._input_dir / namespace
        close_marker = namespace_dir / IPCEndpoint.CLOSE_FILE

        try:
            close_marker.touch()
            logger.info(f"IPC namespace {namespace} shutdown")
        except Exception as e:
            logger.error(f"Failed to shutdown IPC namespace {namespace}: {e}")

    async def shutdown(self) -> None:
        """关闭 IPC 管理器"""
        self._running = False

        # 写入所有命名空间的关闭标记
        for namespace_dir in self._input_dir.iterdir():
            if namespace_dir.is_dir():
                try:
                    close_marker = namespace_dir / IPCEndpoint.CLOSE_FILE
                    close_marker.touch()
                except Exception:
                    pass

        logger.info("IPC Manager shutdown complete")

    def get_status(self) -> Dict[str, Any]:
        """获取 IPC 管理器状态"""
        return {
            "running": self._running,
            "base_dir": str(self._base_dir),
            "namespaces": [d.name for d in self._input_dir.iterdir() if d.is_dir()],
        }


# 全局 IPC 管理器实例
_global_ipc_manager: Optional[IPCManager] = None


def get_ipc_manager(base_dir: Optional[Path] = None) -> IPCManager:
    """获取或创建全局 IPC 管理器实例"""
    global _global_ipc_manager
    if _global_ipc_manager is None:
        _global_ipc_manager = IPCManager(base_dir=base_dir)
    return _global_ipc_manager
