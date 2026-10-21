import pytest_asyncio
from kasauti_api.db.base import engine


@pytest_asyncio.fixture(autouse=True)
async def _dispose_engine_pool():
    """Each test runs in its own event loop, but the async engine is module-level.
    Dispose pooled connections inside the test's loop so the next test doesn't
    inherit connections bound to a closed loop."""
    yield
    await engine.dispose()
