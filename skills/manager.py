"""
技能管理器
协调技能的发现、注册、应用和管理
"""

from datetime import datetime
from pathlib import Path
from typing import List, Optional, Dict, Any

from loguru import logger

from .protocol import (
    SkillManifest,
    SkillCategory,
    SkillApplyResult,
)
from .parser import SkillParser
from .applier import SkillApplier


class SkillManager:
    """
    技能管理器

    特性：
    1. 自动发现技能目录
    2. 解析技能清单
    3. 应用和卸载技能
    4. 查询已安装技能
    5. 生成技能模板
    """

    # 技能搜索路径
    SKILL_PATHS = [
        Path.cwd() / ".claude" / "skills",
        Path.cwd() / "skills",
        Path.home() / ".xbot" / "skills",
    ]

    def __init__(self, project_root: str = "."):
        self.project_root = Path(project_root).resolve()
        self.skills_base_dir = self.project_root / ".claude" / "skills"

        self.parser = SkillParser()
        self.applier = SkillApplier(project_root)

        # 技能清单缓存
        self._manifests: Dict[str, SkillManifest] = {}

    def discover_skills(self) -> Dict[str, Path]:
        """
        发现所有可用的技能

        Returns:
            技能名称到路径的映射
        """
        discovered = {}

        for base_path in self.SKILL_PATHS:
            if not base_path.exists():
                continue

            for skill_dir in base_path.iterdir():
                if not skill_dir.is_dir():
                    continue

                # 检查是否为技能目录（包含 SKILL.md）
                if (skill_dir / "SKILL.md").exists():
                    skill_name = skill_dir.name
                    # 优先级：.claude/skills > skills > ~/.xbot/skills
                    if skill_name not in discovered:
                        discovered[skill_name] = skill_dir

        logger.debug(f"Discovered {len(discovered)} skills")
        return discovered

    def get_manifest(self, skill_name: str) -> Optional[SkillManifest]:
        """
        获取技能清单

        Args:
            skill_name: 技能名称

        Returns:
            技能清单对象，如果不存在则返回 None
        """
        if skill_name not in self._manifests:
            # 尝试发现技能
            discovered = self.discover_skills()
            skill_path = discovered.get(skill_name)

            if not skill_path:
                return None

            manifest = self.parser.parse_file(skill_path)
            if manifest:
                self._manifests[skill_name] = manifest

        return self._manifests.get(skill_name)

    def list_skills(
        self,
        category: Optional[SkillCategory] = None,
        tags: Optional[List[str]] = None,
    ) -> List[Dict[str, Any]]:
        """
        列出技能

        Args:
            category: 按分类过滤
            tags: 按标签过滤

        Returns:
            技能信息列表
        """
        discovered = self.discover_skills()
        results = []

        for skill_name, skill_path in discovered.items():
            manifest = self.parser.parse_file(skill_path)

            if not manifest:
                continue

            # 分类过滤
            if category and manifest.category != category:
                continue

            # 标签过滤
            if tags and not any(tag in manifest.tags for tag in tags):
                continue

            results.append(
                {
                    "name": manifest.name,
                    "display_name": manifest.display_name,
                    "description": manifest.description,
                    "version": manifest.version,
                    "author": manifest.author,
                    "category": manifest.category.value,
                    "tags": manifest.tags,
                    "path": str(skill_path),
                    "installed": self._is_installed(manifest),
                }
            )

        # 排序：按名称
        results.sort(key=lambda x: x["name"])
        return results

    def apply_skill(
        self,
        skill_name: str,
        skill_path: Optional[Path] = None,
        dry_run: bool = False,
    ) -> SkillApplyResult:
        """
        应用技能

        Args:
            skill_name: 技能名称
            skill_path: 技能目录路径（如果未指定则自动发现）
            dry_run: 是否为试运行

        Returns:
            技能应用结果
        """
        # 查找技能路径
        if not skill_path:
            discovered = self.discover_skills()
            skill_path = discovered.get(skill_name)

            if not skill_path:
                return SkillApplyResult(
                    success=False,
                    skill_name=skill_name,
                    errors=[f"Skill '{skill_name}' not found"],
                )

        # 解析清单
        manifest = self.parser.parse_file(skill_path)

        if not manifest:
            return SkillApplyResult(
                success=False,
                skill_name=skill_name,
                errors=["Failed to parse SKILL.md"],
            )

        # 检查是否已安装
        if self._is_installed(manifest):
            return SkillApplyResult(
                success=False,
                skill_name=skill_name,
                errors=[f"Skill '{skill_name}' is already installed"],
            )

        # 应用技能
        result = self.applier.apply(skill_path, dry_run)

        # 如果成功，更新缓存
        if result.success:
            self._manifests[skill_name] = manifest

            # 创建安装标记
            self._mark_installed(manifest)

        return result

    def uninstall_skill(
        self,
        skill_name: str,
        keep_config: bool = False,
    ) -> bool:
        """
        卸载技能

        Args:
            skill_name: 技能名称
            keep_config: 是否保留配置文件

        Returns:
            True 如果成功
        """
        manifest = self.get_manifest(skill_name)

        if not manifest:
            logger.error(f"Skill '{skill_name}' not found")
            return False

        # 执行后置卸载脚本
        if manifest.post_uninstall:
            try:
                self.applier._run_script(manifest.post_uninstall, dry_run=False)
                logger.info(f"Executed post-uninstall script for {skill_name}")
            except Exception as e:
                logger.error(f"Post-uninstall script failed: {e}")

        # 移除安装标记
        self._mark_uninstalled(manifest)

        # 清理缓存
        if skill_name in self._manifests:
            del self._manifests[skill_name]

        logger.info(f"Skill '{skill_name}' uninstalled")
        return True

    def update_skill(
        self,
        skill_name: str,
    ) -> SkillApplyResult:
        """
        更新技能（先卸载再应用）

        Args:
            skill_name: 技能名称

        Returns:
            技能应用结果
        """
        self.uninstall_skill(skill_name)
        return self.apply_skill(skill_name)

    def _is_installed(self, manifest: SkillManifest) -> bool:
        """检查技能是否已安装"""
        installed_file = (
            self.project_root / ".claude" / "installed" / f"{manifest.name}.json"
        )
        return installed_file.exists()

    def _mark_installed(self, manifest: SkillManifest) -> None:
        """标记技能为已安装"""
        installed_dir = self.project_root / ".claude" / "installed"
        installed_dir.mkdir(parents=True, exist_ok=True)

        import json

        installed_file = installed_dir / f"{manifest.name}.json"
        installed_file.write_text(
            json.dumps(
                {
                    "name": manifest.name,
                    "version": manifest.version,
                    "installed_at": datetime.now().isoformat(),
                }
            )
        )

    def _mark_uninstalled(self, manifest: SkillManifest) -> None:
        """标记技能为未安装"""
        installed_file = (
            self.project_root / ".claude" / "installed" / f"{manifest.name}.json"
        )

        if installed_file.exists():
            installed_file.unlink()

    def generate_template(
        self,
        name: str,
        category: str = "utility",
        description: str = "",
    ) -> str:
        """
        生成技能模板

        Args:
            name: 技能名称
            category: 分类
            description: 描述

        Returns:
            技能模板内容
        """

        template = f"""---
name: {name}
display_name: {name.replace("_", " ").title()}
description: {description}
version: 0.0.1
author: Your Name
license: MIT
category: {category}
tags:
  - example

# 依赖项（可选）
# dependencies:
#   - package-name>=1.0.0

# 文件操作（可选）
# files:
#   - type: write
#     path: path/to/file.py
#     content: |
#       # 文件内容

# 命令（可选）
# commands:
#   /{name}: Description of command

# 环境变量（可选）
# environment:
#   EXAMPLE_VAR: value

# 其他说明
notes: |
  Add any additional notes here.

---

# 技能说明

## 功能描述

{description}

## 安装说明

1. 安装此技能
2. 重启 XBot
3. 使用 `/help` 查看新增命令

## 使用方法

`/{name} <args>` - 执行此技能

## 配置

此技能支持以下配置选项：

| 选项 | 默认值 | 说明 |
|------|---------|------|
| - | - | - |
"""
        return template

    def create_skill(
        self,
        name: str,
        category: str = "utility",
        description: str = "",
    ) -> Path:
        """
        创建新技能目录和模板

        Args:
            name: 技能名称
            category: 分类
            description: 描述

        Returns:
            技能目录路径
        """
        skills_dir = self.skills_base_dir
        skills_dir.mkdir(parents=True, exist_ok=True)

        skill_dir = skills_dir / name

        if skill_dir.exists():
            raise FileExistsError(f"Skill directory already exists: {skill_dir}")

        skill_dir.mkdir()

        # 创建模板文件
        template_content = self.generate_template(
            name=name,
            category=category,
            description=description,
        )

        (skill_dir / "SKILL.md").write_text(template_content)

        logger.info(f"Created new skill at {skill_dir}")
        return skill_dir

    def get_stats(self) -> Dict[str, Any]:
        """获取技能统计信息"""
        discovered = self.discover_skills()
        installed = []
        by_category = {}

        for skill_name, skill_path in discovered.items():
            manifest = self.parser.parse_file(skill_path)

            if manifest:
                # 分类统计
                cat = manifest.category.value
                if cat not in by_category:
                    by_category[cat] = 0
                by_category[cat] += 1

                # 已安装统计
                if self._is_installed(manifest):
                    installed.append(skill_name)

        return {
            "total_discovered": len(discovered),
            "total_installed": len(installed),
            "installed_skills": installed,
            "by_category": by_category,
        }


# 全局技能管理器实例
_global_skill_manager: Optional[SkillManager] = None


def get_skill_manager(project_root: str = ".") -> SkillManager:
    """获取或创建全局技能管理器实例"""
    global _global_skill_manager
    if _global_skill_manager is None:
        _global_skill_manager = SkillManager(project_root)
    return _global_skill_manager
