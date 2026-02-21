"""Watchlist service — CRUD operations for WatchlistDB, syncs with global_settings."""

from loguru import logger
from sqlalchemy import select, delete

from server.datastore.models import WatchlistDB
from server.settings import global_settings


async def load_watchlist(session_factory) -> list[str]:
    """Load stock watchlist from DB into global_settings on startup."""
    try:
        async with session_factory() as session:
            result = await session.execute(
                select(WatchlistDB)
                .where(WatchlistDB.enabled.is_(True))
                .where(WatchlistDB.watch_type == "stock")
            )
            items = result.scalars().all()

            if items:
                symbols = [item.symbol for item in items]
                global_settings.watchlist_symbols = symbols
                logger.info(f"Loaded {len(symbols)} watchlist symbols from DB")
                return symbols
            else:
                # First run: seed DB from default settings
                await _seed_defaults(session)
                logger.info("Seeded watchlist DB with defaults")
                return global_settings.watchlist_symbols
    except Exception as e:
        logger.error(f"Failed to load watchlist: {e}")
        return global_settings.watchlist_symbols


async def _seed_defaults(session) -> None:
    """Seed DB with default watchlist symbols from settings."""
    for symbol in global_settings.watchlist_symbols:
        existing = await session.execute(
            select(WatchlistDB).where(WatchlistDB.symbol == symbol)
        )
        if not existing.scalar_one_or_none():
            session.add(WatchlistDB(symbol=symbol, watch_type="stock"))
    await session.commit()


async def add_watch(
    session_factory, symbol: str, watch_type: str = "stock", name: str = ""
) -> bool:
    """Add an item to watchlist. Returns True if added, False if already exists."""
    try:
        async with session_factory() as session:
            existing = await session.execute(
                select(WatchlistDB).where(WatchlistDB.symbol == symbol)
            )
            if existing.scalar_one_or_none():
                return False

            session.add(
                WatchlistDB(
                    symbol=symbol,
                    name=name,
                    watch_type=watch_type,
                    enabled=True,
                )
            )
            await session.commit()

        # Sync to in-memory settings for stock type
        if watch_type == "stock" and symbol not in global_settings.watchlist_symbols:
            global_settings.watchlist_symbols.append(symbol)

        return True
    except Exception as e:
        logger.error(f"Failed to add watch {symbol}: {e}")
        return False


async def remove_watch(session_factory, symbol: str) -> bool:
    """Remove an item from watchlist. Returns True if removed."""
    try:
        async with session_factory() as session:
            result = await session.execute(
                delete(WatchlistDB).where(WatchlistDB.symbol == symbol)
            )
            await session.commit()
            removed = result.rowcount > 0

        # Sync to in-memory settings
        if symbol in global_settings.watchlist_symbols:
            global_settings.watchlist_symbols.remove(symbol)

        return removed
    except Exception as e:
        logger.error(f"Failed to remove watch {symbol}: {e}")
        return False


async def list_watches(session_factory, watch_type: str | None = None) -> list[dict]:
    """List all watchlist items, optionally filtered by type."""
    try:
        async with session_factory() as session:
            query = select(WatchlistDB).where(WatchlistDB.enabled.is_(True))
            if watch_type:
                query = query.where(WatchlistDB.watch_type == watch_type)
            query = query.order_by(WatchlistDB.watch_type, WatchlistDB.added_at)

            result = await session.execute(query)
            items = result.scalars().all()

            return [
                {
                    "symbol": item.symbol,
                    "name": item.name,
                    "watch_type": item.watch_type,
                    "added_at": item.added_at,
                }
                for item in items
            ]
    except Exception as e:
        logger.error(f"Failed to list watches: {e}")
        return []
