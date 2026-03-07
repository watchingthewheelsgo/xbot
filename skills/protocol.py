"""
技能系统协议
定义技能清单格式和应用流程
"""

from dataclasses import dataclass, field
from typing import List, Optional, Dict, Any
from enum import Enum


class SkillCategory(str, Enum):
    """技能分类"""

    INTEGRATION = "integration"  # 集成第三方服务
    COMMAND = "command"  # 新命令
    ANALYSIS = "analysis"  # 分析能力
    AUTOMATION = "automation"  # 自动化任务
    NOTIFICATION = "notification"  # 通知渠道
    UTILITY = "utility"  # 工具类
    SECURITY = "security"  # 安全相关
    DEBUGGING = "debugging"  # 调试工具


class OperationType(str, Enum):
    """操作类型"""

    # 文件操作
    WRITE = "write"  # 写入文件
    REPLACE = "replace"  # 替换内容
    DELETE = "delete"  # 删除文件
    RENAME = "rename"  # 重命名

    # 目录操作
    CREATE_DIR = "create_dir"
    DELETE_DIR = "delete_dir"
    MOVE = "move"

    # 配置操作
    ADD_CONFIG = "add_config"
    MODIFY_CONFIG = "modify_config"
    REMOVE_CONFIG = "remove_config"

    # 数据库操作
    MIGRATE = "migrate"  # 数据库迁移
    SEED = "seed"  # 数据库种子

    # 其他
    RUN_SCRIPT = "run_script"
    EXECUTE = "execute"


@dataclass
class FileOperation:
    """文件操作"""

    type: OperationType
    path: str  # 相对于项目根的路径
    content: Optional[str] = None  # 新文件内容
    old_content: Optional[str] = None  # 替换的旧内容
    pattern: Optional[str] = None  # 替换模式（正则或字符串）
    backup: bool = True  # 是否创建备份

    def to_dict(self) -> Dict[str, Any]:
        return {
            "type": self.type.value,
            "path": self.path,
            "content": self.content,
            "old_content": self.old_content,
            "pattern": self.pattern,
            "backup": self.backup,
        }


@dataclass
class Migration:
    """数据库迁移"""

    version: str  # 格式: YYYYMMDD_HHMMSS
    name: str
    up_sql: str
    down_sql: str
    depends_on: Optional[List[str]] = None


@dataclass
class Dependency:
    """依赖项"""

    name: str  # 包名
    version: Optional[str] = None  # 版本要求
    channel: str = "pypi"  # 包管理器
    optional: bool = False
    install_command: Optional[str] = None  # 自定义安装命令

    def to_pip_str(self) -> str:
        """转换为 pip 安装字符串"""
        if self.version:
            return f"{self.name}~={self.version}"
        return self.name


@dataclass
class SkillManifest:
    """
    技能清单

    技能目录中的 SKILL.md 文件内容
    """

    # 基本信息
    name: str  # 技能名称（与目录名一致）
    display_name: str  # 显示名称
    description: str  # 描述
    version: str  # 版本号 (SemVer)
    author: str  # 作者
    license: str = "MIT"

    # 分类信息
    category: SkillCategory = SkillCategory.UTILITY
    tags: List[str] = field(default_factory=list)

    # 兼容性
    xbot_version: Optional[str] = None  # 兼容的 XBot 版本
    python_version: str = "3.10+"  # Python 版本要求

    # 依赖项
    dependencies: List[Dependency] = field(default_factory=list)
    optional_dependencies: List[Dependency] = field(default_factory=list)

    # 文件操作
    files: List[FileOperation] = field(default_factory=list)

    # 配置变更
    config_changes: Dict[str, Any] = field(default_factory=dict)

    # 数据库迁移
    migrations: List[Migration] = field(default_factory=list)

    # 命令
    commands: Dict[str, str] = field(default_factory=dict)  # 命令名到描述的映射

    # 环境
    environment: Dict[str, str] = field(default_factory=dict)  # 需要设置的环境变量

    # 后置操作
    post_install: Optional[str] = None  # 安装后执行的脚本
    post_uninstall: Optional[str] = None  # 卸载后执行的脚本

    # 其他
    notes: str = ""  # 额外说明
    warnings: List[str] = field(default_factory=list)  # 警告信息

    def to_dict(self) -> Dict[str, Any]:
        """转换为字典"""
        return {
            "name": self.name,
            "display_name": self.display_name,
            "description": self.description,
            "version": self.version,
            "author": self.author,
            "license": self.license,
            "category": self.category.value,
            "tags": self.tags,
            "xbot_version": self.xbot_version,
            "python_version": self.python_version,
            "dependencies": [d.to_pip_str() for d in self.dependencies],
            "optional_dependencies": [
                d.to_pip_str() for d in self.optional_dependencies
            ],
            "files": [f.to_dict() for f in self.files],
            "config_changes": self.config_changes,
            "commands": self.commands,
            "environment": self.environment,
            "post_install": self.post_install,
            "notes": self.notes,
            "warnings": self.warnings,
        }


class SkillError(Exception):
    """技能操作错误"""

    pass


class SkillApplyResult:
    """技能应用结果"""

    def __init__(
        self,
        success: bool,
        skill_name: str = "",
        changes_made: Optional[List[str]] = None,
        errors: Optional[List[str]] = None,
        warnings: Optional[List[str]] = None,
    ):
        self.success = success
        self.skill_name = skill_name
        self.changes_made = changes_made or []
        self.errors = errors or []
        self.warnings = warnings or []
        self.backup_path: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "success": self.success,
            "skill_name": self.skill_name,
            "changes_made": self.changes_made,
            "errors": self.errors,
            "warnings": self.warnings,
            "backup_path": self.backup_path,
        }
