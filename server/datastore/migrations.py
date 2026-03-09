"""
数据库迁移支持
使用 Alembic 进行数据库版本控制
"""

from pathlib import Path
from typing import List, Optional, Dict, Any
from datetime import datetime

from loguru import logger


class Migration:
    """数据库迁移基类"""

    def __init__(
        self,
        version: str,
        name: str,
        description: str = "",
        up_sql: str = "",
        down_sql: str = "",
        depends_on: Optional[List[str]] = None,
    ):
        self.version = version  # 格式: YYYYMMDD_HHMMSS
        self.name = name
        self.description = description
        self.up_sql = up_sql
        self.down_sql = down_sql
        self.depends_on = depends_on or []
        self.applied_at: Optional[datetime] = None

    def __repr__(self) -> str:
        return f"Migration({self.version}: {self.name})"


class MigrationManager:
    """
    数据库迁移管理器

    提供数据库版本控制和迁移执行功能
    """

    def __init__(self, engine, base_dir: str = ""):
        self._engine = engine
        self._base_dir = Path(base_dir) if base_dir else Path.cwd()
        self._migrations_dir = self._base_dir / "migrations"
        self._migrations: Dict[str, Migration] = {}

        # 创建迁移目录
        self._migrations_dir.mkdir(exist_ok=True, parents=True)

        # 内置迁移
        self._builtin_migrations: List[Migration] = [
            Migration(
                version="20240301_000001",
                name="initial_schema",
                description="Initial database schema",
                up_sql=self._get_initial_schema_sql(),
                down_sql="",
                depends_on=[],
            ),
            Migration(
                version="20240310_000001",
                name="add_news_analysis_cache",
                description="Add news analysis cache table",
                up_sql="""
                    CREATE TABLE IF NOT EXISTS news_analysis_cache (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        news_hash TEXT UNIQUE NOT NULL,
                        chinese_summary TEXT DEFAULT '',
                        background TEXT DEFAULT '',
                        market_impact_json TEXT DEFAULT '',
                        action TEXT DEFAULT '',
                        importance INTEGER DEFAULT 0,
                        cached_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                        expires_at DATETIME NULL
                    );
                    CREATE INDEX IF NOT EXISTS idx_cache_hash ON news_analysis_cache(news_hash);
                    CREATE INDEX IF NOT EXISTS idx_cache_expires ON news_analysis_cache(expires_at);
                """,
                down_sql="DROP TABLE IF EXISTS news_analysis_cache;",
                depends_on=["20240301_000001"],
            ),
            Migration(
                version="20240401_000001",
                name="add_memory_tables",
                description="Add memory and conversation tables",
                up_sql="""
                    CREATE TABLE IF NOT EXISTS memory_items (
                        id TEXT PRIMARY KEY,
                        type TEXT NOT NULL,
                        scope TEXT NOT NULL,
                        namespace TEXT NOT NULL DEFAULT 'default',
                        key TEXT NOT NULL,
                        value TEXT NOT NULL,
                        importance INTEGER DEFAULT 0,
                        created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                        updated_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                        expires_at DATETIME NULL
                    );
                    CREATE INDEX IF NOT EXISTS idx_memory_key ON memory_items(scope, namespace, key);
                    CREATE INDEX IF NOT EXISTS idx_memory_type ON memory_items(type);
                    CREATE INDEX IF NOT EXISTS idx_memory_importance ON memory_items(importance);

                    CREATE TABLE IF NOT EXISTS conversation_summaries (
                        summary_id TEXT PRIMARY KEY,
                        namespace TEXT NOT NULL DEFAULT 'default',
                        participants TEXT,
                        topic TEXT,
                        start_time DATETIME NOT NULL,
                        end_time DATETIME NOT NULL,
                        key_points TEXT,
                        sentiment TEXT,
                        created_at DATETIME DEFAULT CURRENT_TIMESTAMP
                    );
                    CREATE INDEX IF NOT EXISTS idx_conv_namespace ON conversation_summaries(namespace);
                    CREATE INDEX IF NOT EXISTS idx_conv_created ON conversation_summaries(created_at);
                """,
                down_sql="""
                    DROP TABLE IF EXISTS conversation_summaries;
                    DROP TABLE IF EXISTS memory_items;
                """,
                depends_on=["20240310_000001"],
            ),
            Migration(
                version="20240410_000001",
                name="fix_news_push_log_platform",
                description="Fix news_push_log table - ensure platform column exists",
                up_sql="""
                    -- Ensure platform column exists and has proper default
                    ALTER TABLE news_push_log ADD COLUMN platform TEXT DEFAULT '';
                """,
                down_sql="",
                depends_on=["20240301_000001"],
            ),
        ]

        # 迁移版本表
        self._schema_table = "_schema_version"

    def _get_initial_schema_sql(self) -> str:
        """获取初始数据库架构 SQL"""
        return """
            CREATE TABLE IF NOT EXISTS rss_feeds (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT UNIQUE NOT NULL,
                description TEXT DEFAULT '',
                category TEXT DEFAULT '',
                url TEXT NOT NULL,
                source TEXT DEFAULT '',
                last_fetched DATETIME NULL,
                enabled INTEGER DEFAULT 1 NOT NULL,
                created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                updated_at DATETIME DEFAULT CURRENT_TIMESTAMP
            );

            CREATE TABLE IF NOT EXISTS rss_articles (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                feed_name TEXT NOT NULL,
                guid TEXT UNIQUE NOT NULL,
                title TEXT NOT NULL,
                link TEXT NOT NULL,
                published DATETIME NOT NULL,
                summary TEXT DEFAULT '',
                content TEXT NULL,
                author TEXT NULL,
                category TEXT DEFAULT '',
                fetched_at DATETIME DEFAULT CURRENT_TIMESTAMP
            );

            CREATE INDEX IF NOT EXISTS idx_feed_published ON rss_articles(feed_name, published);
            CREATE INDEX IF NOT EXISTS idx_feed_fetched ON rss_articles(feed_name, fetched_at);
            CREATE INDEX IF NOT EXISTS idx_published ON rss_articles(published);

            CREATE TABLE IF NOT EXISTS market_news (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                news_id TEXT UNIQUE NOT NULL,
                category TEXT DEFAULT 'general',
                headline TEXT NOT NULL,
                summary TEXT DEFAULT '',
                source TEXT DEFAULT '',
                url TEXT NOT NULL,
                image_url TEXT NULL,
                related_symbols TEXT DEFAULT '',
                published_at DATETIME NOT NULL,
                fetched_at DATETIME DEFAULT CURRENT_TIMESTAMP
            );

            CREATE INDEX IF NOT EXISTS idx_market_news_published ON market_news(published_at);
            CREATE INDEX IF NOT EXISTS idx_market_news_category ON market_news(category, published_at);

            CREATE TABLE IF NOT EXISTS insider_transactions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                transaction_id TEXT UNIQUE NOT NULL,
                symbol TEXT NOT NULL,
                name TEXT NOT NULL,
                share INTEGER DEFAULT 0,
                change INTEGER DEFAULT 0,
                transaction_price REAL DEFAULT 0,
                transaction_code TEXT DEFAULT '',
                transaction_date DATETIME NOT NULL,
                filing_date DATETIME NOT NULL,
                is_derivative INTEGER DEFAULT 0,
                fetched_at DATETIME DEFAULT CURRENT_TIMESTAMP
            );

            CREATE INDEX IF NOT EXISTS idx_insider_symbol_date ON insider_transactions(symbol, transaction_date);

            CREATE TABLE IF NOT EXISTS earnings_calendar (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                symbol TEXT NOT NULL,
                report_date DATETIME NOT NULL,
                hour TEXT DEFAULT '',
                quarter INTEGER DEFAULT 0,
                year INTEGER DEFAULT 0,
                eps_estimate REAL NULL,
                eps_actual REAL NULL,
                revenue_estimate REAL NULL,
                revenue_actual REAL NULL,
                fetched_at DATETIME DEFAULT CURRENT_TIMESTAMP
            );

            CREATE INDEX IF NOT EXISTS idx_earnings_date ON earnings_calendar(report_date);
            CREATE INDEX IF NOT EXISTS idx_earnings_symbol_date ON earnings_calendar(symbol, report_date);

            CREATE TABLE IF NOT EXISTS watchlist (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                symbol TEXT UNIQUE NOT NULL,
                name TEXT DEFAULT '',
                watch_type TEXT DEFAULT 'stock',
                added_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                enabled INTEGER DEFAULT 1
            );

            CREATE TABLE IF NOT EXISTS news_push_log (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                news_hash TEXT NOT NULL,
                push_type TEXT DEFAULT 'digest',
                platform TEXT DEFAULT '',
                pushed_at DATETIME DEFAULT CURRENT_TIMESTAMP
            );

            CREATE INDEX IF NOT EXISTS idx_news_push_hash ON news_push_log(news_hash);
            CREATE INDEX IF NOT EXISTS idx_news_push_type ON news_push_log(push_type);
            CREATE INDEX IF NOT EXISTS idx_news_push_platform ON news_push_log(platform);
            CREATE INDEX IF NOT EXISTS idx_news_pushed_at ON news_push_log(pushed_at);
        """

    async def initialize(self) -> None:
        """初始化迁移系统"""
        # 创建版本表
        await self._create_version_table()

        # 加载迁移
        self._load_builtin_migrations()

        # 加载外部迁移
        self._load_external_migrations()

        logger.info(f"Migration initialized: {len(self._migrations)} migrations")

    async def _create_version_table(self) -> None:
        """创建版本表"""
        async with self._engine.begin() as conn:
            await conn.execute(f"""
                CREATE TABLE IF NOT EXISTS {self._schema_table} (
                    version TEXT PRIMARY KEY,
                    applied_at DATETIME NOT NULL,
                    success INTEGER DEFAULT 1,
                    description TEXT
                )
            """)

    def _load_builtin_migrations(self) -> None:
        """加载内置迁移"""
        for migration in self._builtin_migrations:
            self._migrations[migration.version] = migration

    def _load_external_migrations(self) -> None:
        """加载外部迁移文件"""
        for migration_file in self._migrations_dir.glob("*.sql"):
            try:
                version = migration_file.stem.split("_")[0]
                if version in self._migrations:
                    continue  # 内置迁移优先

                # 读取迁移文件
                content = migration_file.read_text()

                # 解析迁移文件
                self._migrations[version] = Migration(
                    version=version,
                    name=migration_file.stem,
                    description=f"External migration from {migration_file.name}",
                    up_sql=content,
                    down_sql="",
                )

                logger.debug(f"Loaded external migration: {version}")
            except Exception as e:
                logger.warning(f"Failed to load migration {migration_file}: {e}")

    async def get_current_version(self) -> Optional[str]:
        """获取当前数据库版本"""
        async with self._engine.connect() as conn:
            result = await conn.execute(
                f"SELECT MAX(version) as version FROM {self._schema_table} WHERE success = 1"
            )
            row = result.fetchone()
            return row[0] if row and row[0] else None

    async def get_applied_versions(self) -> List[str]:
        """获取已应用的版本"""
        async with self._engine.connect() as conn:
            result = await conn.execute(
                f"SELECT version FROM {self._schema_table} WHERE success = 1 ORDER BY version"
            )
            return [row[0] for row in result.fetchall()]

    async def get_pending_migrations(self) -> List[Migration]:
        """获取待执行的迁移"""
        applied = set(await self.get_applied_versions())
        pending = []

        for migration in self._builtin_migrations:
            if migration.version not in applied:
                # 检查依赖是否满足
                if all(dep in applied for dep in migration.depends_on):
                    pending.append(migration)
                else:
                    logger.warning(
                        f"Migration {migration.version} has unmet dependencies: "
                        f"{migration.depends_on}"
                    )

        return pending

    async def run_migration(self, migration: Migration) -> bool:
        """
        执行单个迁移

        Args:
            migration: 迁移对象

        Returns:
            True 如果成功
        """
        logger.info(f"Running migration: {migration.version} - {migration.name}")

        try:
            async with self._engine.begin() as conn:
                # 执行迁移 SQL
                if migration.up_sql:
                    await conn.execute(migration.up_sql)

                # 记录迁移
                await conn.execute(
                    f"""
                    INSERT INTO {self._schema_table} (version, applied_at, success, description)
                    VALUES (?, ?, ?, ?)
                    """,
                    (
                        migration.version,
                        datetime.now().isoformat(),
                        1,
                        migration.description,
                    ),
                )

            migration.applied_at = datetime.now()
            logger.info(f"Migration completed: {migration.version}")
            return True

        except Exception as e:
            logger.error(f"Migration failed: {migration.version} - {e}")

            # 记录失败
            async with self._engine.connect() as conn:
                await conn.execute(
                    f"""
                    INSERT INTO {self._schema_table} (version, applied_at, success, description)
                    VALUES (?, ?, ?, ?)
                    """,
                    (
                        migration.version,
                        datetime.now().isoformat(),
                        0,
                        migration.description,
                    ),
                )

            return False

    async def upgrade(self, target: Optional[str] = None) -> bool:
        """
        升级数据库到指定版本

        Args:
            target: 目标版本，如果为 None 则升级到最新

        Returns:
            True 如果全部成功
        """
        current = await self.get_current_version()
        logger.info(f"Current database version: {current or 'none'}")

        pending = await self.get_pending_migrations()

        if not pending:
            logger.info("Database is up to date")
            return True

        # 过滤到目标版本
        to_apply = pending
        if target:
            to_apply = [m for m in pending if m.version <= target]

        if not to_apply:
            logger.info(f"Already at version {target or 'latest'}")
            return True

        logger.info(f"Applying {len(to_apply)} migrations...")

        for migration in to_apply:
            if not await self.run_migration(migration):
                logger.error(f"Migration stopped due to failure: {migration.version}")
                return False

        logger.info("All migrations completed successfully")
        return True

    async def downgrade(self, target: Optional[str] = None, steps: int = 1) -> bool:
        """
        降级数据库

        Args:
            target: 目标版本
            steps: 降级步数

        Returns:
            True 如果成功
        """
        logger.warning("Downgrading database is potentially dangerous")

        applied = await self.get_applied_versions()

        if not applied:
            logger.warning("No migrations to downgrade")
            return True

        # 确定要降级的版本
        to_remove = []
        if target:
            to_remove = [v for v in applied if v > target]
        else:
            to_remove = applied[-steps:]

        if not to_remove:
            logger.info(f"Already at target version {target}")
            return True

        # 执行降级（需要每个迁移定义 down_sql）
        for version in reversed(to_remove):
            migration = self._migrations.get(version)

            if not migration or not migration.down_sql:
                logger.warning(f"No downgrade script for {version}")
                continue

            try:
                async with self._engine.begin() as conn:
                    await conn.execute(migration.down_sql)

                    # 移除版本记录
                    await conn.execute(
                        f"DELETE FROM {self._schema_table} WHERE version = ?",
                        (version,),
                    )

                logger.info(f"Downgraded to: {version}")

            except Exception as e:
                logger.error(f"Downgrade failed for {version}: {e}")
                return False

        logger.info("Downgrade completed")
        return True

    def get_status(self) -> Dict[str, Any]:
        """获取迁移状态"""
        return {
            "current_version": None,  # 需要异步获取
            "pending_migrations": len(self._migrations),  # 需要异步计算
            "available_migrations": len(self._migrations),
        }


# 全局迁移管理器实例
_global_migration_manager: Optional[MigrationManager] = None


def get_migration_manager(engine, base_dir: str = "") -> MigrationManager:
    """获取或创建全局迁移管理器实例"""
    global _global_migration_manager
    if _global_migration_manager is None:
        _global_migration_manager = MigrationManager(engine, base_dir)
    return _global_migration_manager
