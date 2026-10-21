"""Attach a hand-cropped diagram image to a `question_stimuli` row.

Cropping a diagram out of a scan is a manual step, not an LLM one: bounding-box cropping
is not something a structured-output call should be trusted with, the same
deterministic-trust-boundary reasoning that keeps MCQ `is_correct` out of extraction (see
ARCHITECTURE.md's "Structured outputs everywhere; deterministic trust boundary"). This script is
where a founder's own crop becomes the learner-facing asset, mirroring how
`publish_scan.py --marks` fills a gap extraction deliberately leaves open.

    uv run python scripts/attach_figure.py 42 var/figures/2011_q12.png

Sets the stimulus's `kind` to 'figure' (refusing to overwrite a passage/directions block
by accident — pass --force to override) and uploads the image to
`settings.r2_bucket_question_assets` under a key derived from the stimulus id, so
re-running with a corrected crop overwrites the same object rather than accumulating
orphans. Does not touch `text_en`/`text_hi`: those still carry the surrounding
instruction text plus an alt-text description, filled in separately at extraction time.
"""

import argparse
import asyncio
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "apps" / "api" / "src"))

from kasauti_api.db.base import async_session_factory  # noqa: E402
from kasauti_api.db.models import QuestionStimulus  # noqa: E402
from kasauti_api.db.models.questions import StimulusKind  # noqa: E402
from kasauti_api.settings import get_settings  # noqa: E402
from kasauti_api.storage import upload_bytes  # noqa: E402
from sqlalchemy import select  # noqa: E402

_CONTENT_TYPES = {".png": "image/png", ".jpg": "image/jpeg", ".jpeg": "image/jpeg"}


async def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("stimulus_id", type=int)
    parser.add_argument("image_path", type=Path)
    parser.add_argument(
        "--force",
        action="store_true",
        help="overwrite a stimulus that is currently a passage/directions block",
    )
    args = parser.parse_args()

    if not args.image_path.exists():
        print(f"no such file: {args.image_path}", file=sys.stderr)
        return 1
    suffix = args.image_path.suffix.lower()
    content_type = _CONTENT_TYPES.get(suffix)
    if content_type is None:
        print(f"unsupported image type {suffix!r}; expected one of {sorted(_CONTENT_TYPES)}",
              file=sys.stderr)
        return 1

    async with async_session_factory() as session:
        stimulus = (
            await session.execute(
                select(QuestionStimulus).where(QuestionStimulus.id == args.stimulus_id)
            )
        ).scalar_one_or_none()
        if stimulus is None:
            print(f"no such question_stimuli row: {args.stimulus_id}", file=sys.stderr)
            return 1
        if stimulus.kind != StimulusKind.figure and not args.force:
            print(
                f"stimulus {args.stimulus_id} is kind={stimulus.kind.value!r}, not 'figure'"
                " — pass --force to convert it",
                file=sys.stderr,
            )
            return 1

        asset_key = f"figures/{args.stimulus_id}{suffix}"
        data = args.image_path.read_bytes()
        await asyncio.to_thread(
            upload_bytes, get_settings().r2_bucket_question_assets, asset_key, data, content_type
        )

        stimulus.kind = StimulusKind.figure
        stimulus.asset_key = asset_key
        await session.commit()

    print(f"stimulus {args.stimulus_id}: attached {args.image_path} as {asset_key}")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
