from arq.connections import RedisSettings

from kasauti_api.settings import get_settings
from kasauti_api.workers.embedding_tasks import embed_question
from kasauti_api.workers.ingestion_tasks import process_scan
from kasauti_api.workers.intelligence_tasks import analyze_topic, generate_topic_note


def redis_settings() -> RedisSettings:
    return RedisSettings.from_dsn(get_settings().redis_url)


class WorkerSettings:
    """arq worker entrypoint: `uv run arq kasauti_api.workers.queue.WorkerSettings`."""

    functions = [process_scan, embed_question, analyze_topic, generate_topic_note]
    redis_settings = redis_settings()
    max_jobs = 4          # LLM-bound jobs; keep concurrency modest
    job_timeout = 900     # a full paper extraction can take several minutes
    keep_result = 3600
