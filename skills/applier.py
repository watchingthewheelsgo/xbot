"""
技能应用器
执行技能清单中定义的操作
"""

import shutil
import subprocess
from pathlib import Path
from typing import List, Dict, Any
from datetime import datetime

from loguru import logger

from .protocol import (
    FileOperation,
    OperationType,
    Dependency,
    SkillApplyResult,
    SkillError,
)
from .parser import SkillParser


class SkillApplier:
    """
    技能应用器

    功能：
    1. 执行文件操作（写、替换、删除等）
    2. 安装依赖项
    3. 执行数据库迁移
    4. 创建备份
    5. 支持回滚
    """

    def __init__(self, project_root: str = "."):
        self.project_root = Path(project_root).resolve()
        self.backup_dir = self.project_root / ".skills" / "backups"
        self.backup_dir.mkdir(parents=True, exist_ok=True)
        self.parser = SkillParser()

    def apply(
        self,
        skill_path: Path,
        dry_run: bool = False,
    ) -> SkillApplyResult:
        """
        应用技能

        Args:
            skill_path: 技能目录路径
            dry_run: 是否为试运行（不实际修改）

        Returns:
            技能应用结果
        """
        logger.info(f"Applying skill from {skill_path}")

        # 解析清单
        manifest = self.parser.parse_file(skill_path)
        if not manifest:
            return SkillApplyResult(
                success=False,
                skill_name=skill_path.name,
                errors=["Failed to parse SKILL.md"],
            )

        result = SkillApplyResult(
            success=True,
            skill_name=manifest.name,
        )

        # 检查警告
        if manifest.warnings:
            result.warnings.extend(manifest.warnings)

        try:
            # 1. 创建备份
            backup_path = self._create_backup(dry_run)
            result.backup_path = str(backup_path)
            result.changes_made.append(f"Backup created at {backup_path}")

            # 2. 执行文件操作
            for file_op in manifest.files:
                try:
                    self._apply_file_operation(file_op, dry_run)
                    result.changes_made.append(
                        f"File operation: {file_op.type} on {file_op.path}"
                    )
                except Exception as e:
                    result.errors.append(f"File operation failed: {e}")

            # 3. 安装依赖项
            for dep in manifest.dependencies:
                try:
                    self._install_dependency(dep, dry_run)
                    result.changes_made.append(f"Installed: {dep.name}")
                except Exception as e:
                    result.errors.append(f"Dependency installation failed: {e}")

            # 4. 执行数据库迁移
            for migration in manifest.migrations:
                try:
                    self._run_migration(migration, dry_run)
                    result.changes_made.append(f"Migration: {migration.name}")
                except Exception as e:
                    result.errors.append(f"Migration failed: {e}")

            # 5. 执行后置脚本
            if manifest.post_install:
                try:
                    self._run_script(manifest.post_install, dry_run)
                    result.changes_made.append("Post-install script executed")
                except Exception as e:
                    result.errors.append(f"Post-install script failed: {e}")

            # 检查是否有错误
            if result.errors:
                result.success = False
                logger.error(
                    f"Skill application completed with errors: {result.errors}"
                )
            else:
                logger.info(f"Skill {manifest.name} applied successfully")

            return result

        except Exception as e:
            logger.error(f"Skill application failed: {e}")
            return SkillApplyResult(
                success=False,
                skill_name=manifest.name,
                errors=[str(e)],
            )

    def _create_backup(self, dry_run: bool = False) -> Path:
        """创建备份"""
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        backup_name = f"backup_{timestamp}"
        backup_path = self.backup_dir / backup_name

        if dry_run:
            logger.debug(f"[DRY RUN] Would create backup at {backup_path}")
            return backup_path

        try:
            # 复制需要备份的文件/目录
            # 简化实现：备份整个项目
            if not backup_path.exists():
                shutil.copytree(
                    self.project_root,
                    backup_path / "project",
                    ignore=shutil.ignore_patterns(".*__pycache__*"),
                )

            logger.info(f"Backup created at {backup_path}")
            return backup_path

        except Exception as e:
            logger.warning(f"Backup creation failed: {e}")
            return backup_path

    def _apply_file_operation(self, operation: FileOperation, dry_run: bool) -> None:
        """应用文件操作"""
        target_path = self.project_root / operation.path

        if dry_run:
            logger.debug(f"[DRY RUN] File op: {operation.type} on {operation.path}")
            return

        # 根据操作类型执行
        if operation.type == OperationType.WRITE:
            target_path.parent.mkdir(parents=True, exist_ok=True)
            if operation.content is not None:
                target_path.write_text(operation.content, encoding="utf-8")
            logger.debug(f"Wrote file: {operation.path}")

        elif operation.type == OperationType.REPLACE:
            if not target_path.exists():
                raise SkillError(f"File not found for replacement: {operation.path}")

            old_content = target_path.read_text(encoding="utf-8")
            new_content = old_content

            if operation.pattern:
                if operation.old_content:
                    # 简单字符串替换
                    new_content = old_content.replace(
                        operation.old_content, operation.content or ""
                    )
                else:
                    # 正则替换（简化）
                    import re

                    new_content = re.sub(
                        operation.pattern, operation.content or "", old_content
                    )
            else:
                new_content = operation.content or old_content

            target_path.write_text(new_content, encoding="utf-8")
            logger.debug(f"Replaced content in: {operation.path}")

        elif operation.type == OperationType.DELETE:
            if target_path.exists():
                if target_path.is_dir():
                    shutil.rmtree(target_path)
                else:
                    target_path.unlink()
                logger.debug(f"Deleted: {operation.path}")

        elif operation.type == OperationType.CREATE_DIR:
            target_path.mkdir(parents=True, exist_ok=True)
            logger.debug(f"Created directory: {operation.path}")

        elif operation.type == OperationType.RENAME:
            if not target_path.exists():
                raise SkillError(f"Source file not found: {operation.path}")
            new_name = (
                operation.old_content or "renamed_file"
            )  # old_content 复用为 new_name
            target_path.rename(target_path.parent / new_name)
            logger.debug(f"Renamed {operation.path} to {new_name}")

        else:
            logger.warning(f"Unsupported file operation type: {operation.type}")

    def _install_dependency(self, dependency: Dependency, dry_run: bool) -> None:
        """安装依赖项"""
        if dry_run:
            logger.debug(f"[DRY RUN] Would install: {dependency.name}")
            return

        if dependency.install_command:
            # 自定义安装命令
            subprocess.run(
                dependency.install_command,
                shell=True,
                check=True,
                cwd=self.project_root,
            )
        elif dependency.channel == "pypi":
            # 使用 pip/uv 安装
            try:
                # 检查是否使用 uv
                subprocess.run(
                    ["uv", "pip", "install", dependency.to_pip_str()],
                    check=True,
                    cwd=self.project_root,
                )
            except (FileNotFoundError, subprocess.CalledProcessError):
                # 回退到 pip
                subprocess.run(
                    ["pip", "install", dependency.to_pip_str()],
                    check=True,
                )

        logger.debug(f"Installed dependency: {dependency.name}")

    def _run_migration(self, migration: Any, dry_run: bool) -> None:
        """执行数据库迁移"""
        # 简化实现：记录迁移日志
        migration_dir = self.project_root / "migrations"
        migration_dir.mkdir(parents=True, exist_ok=True)

        if dry_run:
            logger.debug(f"[DRY RUN] Would run migration: {migration.version}")
            return

        migration_file = migration_dir / f"{migration.version}_{migration.name}.sql"
        if migration.up_sql:
            migration_file.write_text(migration.up_sql)

        logger.debug(f"Migration prepared: {migration.version}")

    def _run_script(self, script: str, dry_run: bool) -> None:
        """运行后置脚本"""
        if dry_run:
            logger.debug(f"[DRY RUN] Would run script: {script}")
            return

        script_path = self.project_root / script

        if not script_path.exists():
            logger.warning(f"Script not found: {script}")
            return

        # 判断脚本类型
        if script_path.suffix == ".sh":
            subprocess.run(
                ["bash", str(script_path)], check=True, cwd=self.project_root
            )
        elif script_path.suffix == ".py":
            subprocess.run(
                ["python", str(script_path)], check=True, cwd=self.project_root
            )
        else:
            logger.warning(f"Unsupported script type: {script_path.suffix}")

    def rollback(self, backup_path: str) -> bool:
        """
        回滚到备份

        Args:
            backup_path: 备份路径

        Returns:
            True 如果成功
        """
        backup = Path(backup_path)

        if not backup.exists():
            logger.error(f"Backup not found: {backup_path}")
            return False

        try:
            project_backup = backup / "project"

            if not project_backup.exists():
                logger.error(f"Project backup not found: {project_backup}")
                return False

            # 删除当前项目内容（保留 .skills 目录）
            for item in self.project_root.iterdir():
                if item.name == ".skills":
                    continue
                if item.is_dir():
                    shutil.rmtree(item)
                else:
                    item.unlink()

            # 恢复备份
            for item in project_backup.iterdir():
                if item.is_dir():
                    shutil.copytree(item, self.project_root / item.name)
                else:
                    shutil.copy2(item, self.project_root / item.name)

            logger.info(f"Rolled back to backup: {backup_path}")
            return True

        except Exception as e:
            logger.error(f"Rollback failed: {e}")
            return False

    def list_backups(self) -> List[Dict[str, Any]]:
        """列出所有备份"""
        backups = []

        for backup_dir in self.backup_dir.iterdir():
            if not backup_dir.is_dir():
                continue

            stat = backup_dir.stat()
            backups.append(
                {
                    "name": backup_dir.name,
                    "path": str(backup_dir),
                    "created_at": datetime.fromtimestamp(stat.st_ctime).isoformat(),
                    "size_mb": sum(
                        f.stat().st_size for f in backup_dir.rglob("*") if f.is_file()
                    )
                    / (1024 * 1024),
                }
            )

        return sorted(backups, key=lambda x: x["created_at"], reverse=True)

    def cleanup_old_backups(self, keep_count: int = 5) -> None:
        """清理旧备份，保留最近的 N 个"""
        backups = self.list_backups()

        for backup in backups[keep_count:]:
            backup_path = Path(backup["path"])
            try:
                shutil.rmtree(backup_path)
                logger.info(f"Cleaned up old backup: {backup['name']}")
            except Exception as e:
                logger.warning(f"Failed to delete backup {backup['name']}: {e}")
