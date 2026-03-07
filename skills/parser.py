"""
技能清单解析器
解析 SKILL.md 文件中的技能定义
"""

import re
from pathlib import Path
from typing import Optional, List, Dict, Any

from loguru import logger

from .protocol import (
    SkillManifest,
    SkillCategory,
    OperationType,
    Dependency,
    FileOperation,
    Migration,
    SkillError,
)


class SkillParser:
    """技能清单解析器"""

    # 解析模式的正则表达式
    FRONTMATTER_PATTERN = re.compile(r"^---\n(.*?)\n---\n", re.MULTILINE | re.DOTALL)
    KEY_VALUE_PATTERN = re.compile(r"^([A-Za-z_]+):\s*(.*)$", re.MULTILINE)
    ARRAY_PATTERN = re.compile(r"^[ \t]*-\s*(.*)$", re.MULTILINE)
    MULTILINE_ARRAY_PATTERN = re.compile(r"^([A-Za-z_]+):\s*$", re.MULTILINE)
    DEPENDENCY_PATTERN = re.compile(r"([^=<>~\s]+)([=<>~]{0,2}[^\s]*)?")

    def __init__(self):
        self._cache: Dict[str, SkillManifest] = {}

    def parse_file(self, skill_path: Path) -> Optional[SkillManifest]:
        """
        解析技能目录中的 SKILL.md 文件

        Args:
            skill_path: 技能目录路径

        Returns:
            技能清单对象，如果失败则返回 None
        """
        skill_file = skill_path / "SKILL.md"

        if not skill_file.exists():
            logger.warning(f"SKILL.md not found in {skill_path}")
            return None

        # 检查缓存
        cache_key = f"{skill_path}:{skill_file.stat().st_mtime}"
        if cache_key in self._cache:
            return self._cache[cache_key]

        try:
            content = skill_file.read_text(encoding="utf-8")
            manifest = self._parse_content(content, skill_path.name)
            self._cache[cache_key] = manifest
            return manifest

        except Exception as e:
            logger.error(f"Failed to parse skill {skill_path}: {e}")
            return None

    def _parse_content(self, content: str, skill_name: str) -> SkillManifest:
        """解析清单内容"""
        # 提取 frontmatter
        match = self.FRONTMATTER_PATTERN.search(content)
        if not match:
            raise SkillError(f"No frontmatter found in {skill_name}")

        frontmatter = match.group(1)

        # 解析键值对
        data = self._parse_frontmatter(frontmatter)

        # 提取基本字段
        name = data.get("name", skill_name)
        display_name = data.get("display_name", name)
        description = data.get("description", "")
        version = data.get("version", "0.0.1")
        author = data.get("author", "Unknown")
        license_val = data.get("license", "MIT")

        # 解析分类
        category_str = data.get("category", "utility")
        try:
            category = SkillCategory(category_str.lower())
        except ValueError:
            category = SkillCategory.UTILITY
            logger.warning(f"Invalid category '{category_str}', using 'utility'")

        # 解析标签
        tags = self._parse_array(data.get("tags", ""))

        # 解析依赖项
        dependencies = self._parse_dependencies(data.get("dependencies", []))
        optional_dependencies = self._parse_dependencies(
            data.get("optional_dependencies", [])
        )

        # 解析文件操作
        files = self._parse_files(data.get("files", []))

        # 解析迁移
        migrations = self._parse_migrations(data.get("migrations", []))

        # 解析命令
        commands = data.get("commands", {})

        # 解析环境变量
        environment = data.get("environment", {})

        # 其他字段
        notes = data.get("notes", "")
        warnings = self._parse_array(data.get("warnings", []))

        return SkillManifest(
            name=name,
            display_name=display_name,
            description=description,
            version=version,
            author=author,
            license=license_val,
            category=category,
            tags=tags,
            xbot_version=data.get("xbot_version"),
            python_version=data.get("python_version", "3.10+"),
            dependencies=dependencies,
            optional_dependencies=optional_dependencies,
            files=files,
            config_changes=data.get("config_changes", {}),
            migrations=migrations,
            commands=commands,
            environment=environment,
            post_install=data.get("post_install"),
            post_uninstall=data.get("post_uninstall"),
            notes=notes,
            warnings=warnings,
        )

    def _parse_frontmatter(self, frontmatter: str) -> Dict[str, Any]:
        """解析 frontmatter 内容"""
        result = {}

        lines = frontmatter.split("\n")
        current_key = None
        current_array: List[str] = []
        in_multiline = False

        for line in lines:
            stripped = line.strip()

            # 检查是否为数组项
            if stripped.startswith("- "):
                value = stripped[2:].strip()
                if current_key:
                    if current_array:
                        # 多行数组
                        current_array.append(value)
                    else:
                        # 单行数组
                        result[current_key] = current_array = [value]
                continue

            # 检查键值对
            match = self.KEY_VALUE_PATTERN.match(line)
            if match:
                key = match.group(1).lower().replace("-", "_")

                # 保存前一个多行数组
                if in_multiline and current_key:
                    result[current_key] = current_array
                    in_multiline = False
                    current_array = []

                value = match.group(2).strip()

                # 检查是否为多行数组开始
                if value == "" and line.endswith(":"):
                    current_key = key
                    in_multiline = True
                    current_array = []
                else:
                    result[key] = value
                    current_key = None

        # 保存最后一个多行数组
        if in_multiline and current_key:
            result[current_key] = current_array

        return result

    def _parse_array(self, value: Any) -> List[str]:
        """解析数组值"""
        if isinstance(value, list):
            return [str(v) for v in value]
        if isinstance(value, str):
            items = [item.strip() for item in value.split(",")]
            return [item for item in items if item]
        return []

    def _parse_dependencies(self, deps_data: Any) -> List[Dependency]:
        """解析依赖项列表"""
        if not deps_data:
            return []

        if isinstance(deps_data, list):
            return [self._parse_dependency(dep) for dep in deps_data]

        return []

    def _parse_dependency(self, dep_spec: Any) -> Dependency:
        """解析单个依赖项"""
        if isinstance(dep_spec, str):
            # 格式: "package[extra]>=1.0.0"
            return self._parse_dependency_string(dep_spec)

        if isinstance(dep_spec, dict):
            # 对象格式
            name = dep_spec.get("name", "")
            version = dep_spec.get("version")
            channel = dep_spec.get("channel", "pypi")
            optional = dep_spec.get("optional", False)
            install_cmd = dep_spec.get("install_command")

            return Dependency(
                name=name,
                version=version,
                channel=channel,
                optional=optional,
                install_command=install_cmd,
            )

        return Dependency(name=str(dep_spec))

    def _parse_dependency_string(self, dep_str: str) -> Dependency:
        """解析依赖项字符串"""
        match = self.DEPENDENCY_PATTERN.match(dep_str.strip())
        if match:
            name = match.group(1)
            version_spec = match.group(2)
            version = version_spec.strip("=~<>") if version_spec else None
            return Dependency(name=name, version=version)
        return Dependency(name=dep_str.strip())

    def _parse_files(self, files_data: Any) -> List[FileOperation]:
        """解析文件操作列表"""
        if not files_data:
            return []

        if isinstance(files_data, list):
            return [self._parse_file(file_spec) for file_spec in files_data]

        return []

    def _parse_file(self, file_spec: Any) -> FileOperation:
        """解析单个文件操作"""
        if isinstance(file_spec, str):
            # 简单格式: "write:path:content"
            parts = file_spec.split(":")
            if len(parts) >= 2:
                op_type = OperationType(parts[0])
                path = parts[1]
                content = ":".join(parts[2:]) if len(parts) > 2 else None
                return FileOperation(type=op_type, path=path, content=content)
            return FileOperation(type=OperationType.WRITE, path=file_spec.strip())

        if isinstance(file_spec, dict):
            return FileOperation(
                type=OperationType(file_spec.get("type", "write")),
                path=file_spec.get("path", ""),
                content=file_spec.get("content"),
                old_content=file_spec.get("old_content"),
                pattern=file_spec.get("pattern"),
                backup=file_spec.get("backup", True),
            )

        return FileOperation(type=OperationType.WRITE, path=str(file_spec))

    def _parse_migrations(self, migrations_data: Any) -> List[Migration]:
        """解析迁移列表"""
        if not migrations_data:
            return []

        if isinstance(migrations_data, list):
            return [self._parse_migration(mig_spec) for mig_spec in migrations_data]

        return []

    def _parse_migration(self, mig_spec: Any) -> Migration:
        """解析单个迁移"""
        if isinstance(mig_spec, dict):
            return Migration(
                version=mig_spec.get("version", ""),
                name=mig_spec.get("name", ""),
                up_sql=mig_spec.get("up_sql", ""),
                down_sql=mig_spec.get("down_sql", ""),
                depends_on=mig_spec.get("depends_on"),
            )
        return Migration(version="", name="", up_sql="", down_sql="")

    def clear_cache(self) -> None:
        """清除解析缓存"""
        self._cache.clear()
