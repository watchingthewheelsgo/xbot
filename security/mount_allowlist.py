"""
挂载安全验证模块
借鉴 NanoClaw 的白名单设计，防止容器内访问敏感路径
"""

import json
import os
from pathlib import Path
from typing import List, Optional, Dict, Tuple, Any
from loguru import logger


# 白名单配置路径
ALLOWLIST_PATH = Path.home() / ".config" / "xbot" / "mount_allowlist.json"


# 默认阻止模式
DEFAULT_BLOCKED_PATTERNS = [
    ".ssh",
    ".gnupg",
    ".gpg",
    ".aws",
    ".azure",
    ".gcloud",
    ".kube",
    ".docker",
    "credentials",
    ".env",
    ".netrc",
    ".npmrc",
    ".pypirc",
    "id_rsa",
    "id_ed25519",
    "private_key",
    ".secret",
    "credentials.json",
    "key.json",
    "token",
    "password",
]


class MountAllowlist:
    """挂载白名单配置"""

    def __init__(
        self,
        allowed_roots: List[Dict[str, Any]],
        blocked_patterns: List[str],
        non_main_readonly: bool = True,
    ):
        self.allowed_roots = allowed_roots
        self.blocked_patterns = blocked_patterns + DEFAULT_BLOCKED_PATTERNS
        self.non_main_readonly = non_main_readonly


class MountSecurity:
    """
    挂载安全验证器

    功能：
    1. 路径验证（阻止模式检查）
    2. 白名单验证
    3. 只读权限控制
    4. 路径遍历保护（防止 ..）
    """

    def __init__(self):
        self._allowlist: Optional[MountAllowlist] = None
        self._allowlist_loaded = False

    def _load_allowlist(self) -> None:
        """从外部位置加载白名单"""
        if self._allowlist_loaded:
            return

        try:
            if not ALLOWLIST_PATH.exists():
                logger.warning(
                    f"Allowlist not found at {ALLOWLIST_PATH}, "
                    f"all additional mounts will be BLOCKED. "
                    f"Create file to enable additional mounts."
                )
                self._allowlist = MountAllowlist(
                    allowed_roots=[],
                    blocked_patterns=[],
                    non_main_readonly=False,
                )
                return

            with open(ALLOWLIST_PATH, "r", encoding="utf-8") as f:
                data = json.load(f)

            # 验证结构
            if not isinstance(data, dict):
                raise ValueError("Invalid allowlist format: must be a dict")

            if "allowed_roots" not in data:
                raise ValueError("Invalid allowlist: missing 'allowed_roots'")

            if not isinstance(data["allowed_roots"], list):
                raise ValueError("Invalid allowlist: 'allowed_roots' must be a list")

            # 合并默认阻止模式
            blocked_patterns = data.get("blocked_patterns", [])
            if not isinstance(blocked_patterns, list):
                raise ValueError("Invalid allowlist: 'blocked_patterns' must be a list")

            merged_blocked = DEFAULT_BLOCKED_PATTERNS + blocked_patterns

            self._allowlist = MountAllowlist(
                allowed_roots=data["allowed_roots"],
                blocked_patterns=list(set(merged_blocked)),  # 去重
                non_main_readonly=data.get("non_main_readonly", True),
            )

            self._allowlist_loaded = True
            logger.info(
                f"Allowlist loaded successfully from {ALLOWLIST_PATH}, "
                f"roots={len(self._allowlist.allowed_roots)}, "
                f"blocked={len(self._allowlist.blocked_patterns)}"
            )

        except json.JSONDecodeError as e:
            logger.error(f"Failed to parse allowlist: {e}")
            self._allowlist = None
        except Exception as e:
            logger.error(f"Failed to load allowlist: {e}")
            self._allowlist = None

    def get_allowlist(self) -> Optional[MountAllowlist]:
        """获取白名单配置"""
        if not self._allowlist_loaded:
            self._load_allowlist()
        return self._allowlist

    def expand_path(self, path_str: str) -> str:
        """展开 ~ 为家目录"""
        if path_str.startswith("~"):
            home_dir = os.path.expanduser(path_str[:2])  # ~/
            return os.path.join(home_dir, path_str[2:])
        elif path_str == "~":
            return os.path.expanduser("~")
        return path_str

    def get_real_path(self, path_str: str) -> Optional[str]:
        """获取真实路径（解析符号链接）"""
        expanded = self.expand_path(path_str)
        try:
            return os.path.realpath(expanded)
        except (OSError, RuntimeError):
            return None

    def matches_blocked_pattern(
        self, real_path: str, blocked_patterns: List[str]
    ) -> Optional[str]:
        """
        检查路径是否匹配阻止模式

        Returns:
            匹配的模式名，如果未匹配则返回 None
        """
        path_lower = real_path.lower()
        path_parts = Path(real_path).parts

        for pattern in blocked_patterns:
            # 检查路径的任何部分是否匹配
            if pattern in path_lower:
                return pattern
            # 检查路径组件
            for part in path_parts:
                if part.lower() == pattern:
                    return pattern

        return None

    def is_under_allowed_root(
        self, real_path: str, root: Dict[str, Any]
    ) -> Tuple[bool, Optional[Dict[str, Any]]]:
        """
        检查路径是否在允许的根目录下

        Returns:
            (is_allowed, root_config)
        """
        root_path = self.expand_path(root["path"])
        if not root_path:
            return False, None

        try:
            root_real = os.path.realpath(root_path)
        except (OSError, RuntimeError):
            return False, None

        # 检查路径是否在 root 之下
        relative = os.path.relpath(root_real, real_path)
        if relative.startswith("..") or os.path.isabs(relative):
            return False, None

        return True, root

    def validate_container_path(self, container_path: str) -> Tuple[bool, str]:
        """
        验证容器路径（防止路径遍历）

        Returns:
            (is_valid, error_message)
        """
        if not container_path or container_path.strip() == "":
            return False, "Container path cannot be empty"

        # 防止路径遍历
        if ".." in container_path:
            return False, "Container path cannot contain '..'"

        # 防止绝对路径（会逃离 /workspace）
        if container_path.startswith("/"):
            return False, "Container path must be relative"

        return True, ""


class MountValidationResult:
    """挂载验证结果"""

    def __init__(
        self,
        allowed: bool = False,
        reason: str = "",
        real_host_path: str = "",
        resolved_container_path: str = "",
        effective_readonly: bool = True,
    ):
        self.allowed = allowed
        self.reason = reason
        self.real_host_path = real_host_path
        self.resolved_container_path = resolved_container_path
        self.effective_readonly = effective_readonly

    def to_dict(self) -> Dict[str, Any]:
        return {
            "allowed": self.allowed,
            "reason": self.reason,
            "real_host_path": self.real_host_path,
            "resolved_container_path": self.resolved_container_path,
            "effective_readonly": self.effective_readonly,
        }


def validate_mount(
    host_path: str,
    container_path: Optional[str] = None,
    is_main: bool = False,
    allowlist: Optional[MountAllowlist] = None,
) -> MountValidationResult:
    """
    验证单个挂载请求

    Args:
        host_path: 主机路径
        container_path: 容器内路径（可选）
        is_main: 是否为主组
        allowlist: 白名单配置（可选）

    Returns:
        MountValidationResult
    """
    # 如果没有提供白名单，尝试加载
    if allowlist is None:
        # 延迟加载，允许配置动态更新
        pass  # 在实际使用中加载

    # 1. 解析和验证主机路径
    if not host_path:
        return MountValidationResult(allowed=False, reason="Host path cannot be empty")

    real_path = None
    try:
        real_path = MountSecurity().get_real_path(host_path)
        if real_path is None:
            return MountValidationResult(
                allowed=False, reason=f"Invalid path: {host_path}"
            )
    except Exception as e:
        return MountValidationResult(
            allowed=False, reason=f"Failed to resolve path: {e}"
        )

    # 2. 获取白名单
    allowlist = allowlist or MountSecurity().get_allowlist()
    if not allowlist:
        return MountValidationResult(allowed=False, reason="No allowlist configured")

    # 3. 检查默认阻止模式
    blocked_pattern = MountSecurity().matches_blocked_pattern(
        real_path, allowlist.blocked_patterns
    )
    if blocked_pattern:
        return MountValidationResult(
            allowed=False,
            real_host_path=real_path,
            reason=f"Path matches blocked pattern: {blocked_pattern}",
        )

    # 4. 检查是否在允许的根目录下
    found_root = None
    for root in allowlist.allowed_roots:
        is_allowed, root_config = MountSecurity().is_under_allowed_root(real_path, root)
        if is_allowed:
            found_root = root_config
            break
        else:
            continue

    if not found_root:
        return MountValidationResult(
            allowed=False,
            real_host_path=real_path,
            reason=f"Path not under any allowed root. "
            f"Roots: {', '.join(r['path'] for r in allowlist.allowed_roots)}",
        )

    # 5. 确定有效的只读状态
    effective_readonly = True
    if not found_root["allow_readwrite"]:
        effective_readonly = True

    # 6. 验证容器路径
    if container_path is not None:
        is_valid, error_msg = MountSecurity().validate_container_path(container_path)
        if not is_valid:
            return MountValidationResult(
                allowed=False, reason=f"Invalid container path: {error_msg}"
            )

        resolved_container_path = container_path
    else:
        # 如果没有提供容器路径，使用主机路径的基名
        resolved_container_path = Path(real_path).name

    return MountValidationResult(
        allowed=True,
        reason=f"Allowed under root '{found_root['path']}'",
        real_host_path=real_path,
        resolved_container_path=resolved_container_path,
        effective_readonly=effective_readonly,
    )


def validate_additional_mounts(
    mounts: List[Dict[str, Any]],
    is_main: bool = False,
    allowlist: Optional[MountAllowlist] = None,
) -> List[MountValidationResult]:
    """
    验证多个挂载请求

    Args:
        mounts: 挂载请求列表，每个包含 host_path 等
        is_main: 是否为主组
        allowlist: 白名单配置

    Returns:
        验证结果列表
    """
    results = []
    for mount in mounts:
        host_path = mount.get("host_path") or ""
        container_path = mount.get("container_path")
        result = validate_mount(
            host_path=host_path,
            container_path=container_path,
            is_main=is_main,
            allowlist=allowlist,
        )
        results.append(result)

    return results


def generate_allowlist_template() -> str:
    """
    生成白名单配置模板文件内容

    Returns:
        JSON 格式的白名单配置
    """
    template = {
        "allowed_roots": [
            {
                "path": "~/projects",
                "allow_readwrite": True,
                "description": "开发项目目录",
            },
            {"path": "~/repos", "allow_readwrite": True, "description": "代码仓库目录"},
            {
                "path": "~/Documents/work",
                "allow_readwrite": False,
                "description": "工作文档（只读）",
            },
            {
                "path": "~/datasets",
                "allow_readwrite": True,
                "description": "数据集目录",
            },
        ],
        "blocked_patterns": [
            # 添加额外的阻止模式
            "password",
            "secret",
            "token",
            "api_key",
        ],
        "non_main_readonly": True,
    }

    return json.dumps(template, indent=2, ensure_ascii=False)


def create_default_allowlist() -> None:
    """
    创建默认白名单配置文件
    """
    ALLOWLIST_PATH.parent.mkdir(exist_ok=True, parents=True)

    if ALLOWLIST_PATH.exists():
        logger.warning(f"Allowlist already exists at {ALLOWLIST_PATH}")
        return

    content = generate_allowlist_template()

    ALLOWLIST_PATH.write_text(content)
    logger.info(f"Created default allowlist at {ALLOWLIST_PATH}")


# 全局 MountSecurity 实例
_global_security: Optional[MountSecurity] = None


def get_mount_security() -> MountSecurity:
    """获取或创建全局 MountSecurity 实例"""
    global _global_security
    if _global_security is None:
        _global_security = MountSecurity()
    return _global_security
