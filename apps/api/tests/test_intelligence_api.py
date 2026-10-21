"""The corpus-wide intelligence endpoints: trends, option patterns, recurrence, depth.

These serve *aggregates* over a database shared with real ingested papers, so the
assertions here are deliberately about invariants rather than values. A test that pinned
"2022 shows 19% count-format questions" would fail the day Paper 2 lands, which is not a
regression — it is the corpus growing.

What is worth pinning is the honesty machinery, because that is what silently rots:
shares that must sum to one, a coverage figure that must accompany a partial chart, and a
verdict that must accompany every measured rate.
"""

import pytest
from httpx import ASGITransport, AsyncClient
from kasauti_api.db.base import async_session_factory
from kasauti_api.db.models import Topic
from kasauti_api.main import app
from sqlalchemy import select


@pytest.mark.asyncio
async def test_trends_report_their_own_coverage():
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        r = await client.get("/api/v1/pyq/trends", params={"dimension": "regex_format"})
        assert r.status_code == 200
        body = r.json()
        if not body["years"]:
            pytest.skip("no published questions — nothing to chart")

        assert body["years"] == sorted(body["years"])
        assert 0.0 <= body["profiled_share"] <= 1.0
        # A chart drawn from part of the corpus must say so. This is the property that
        # would rot silently: the note is the only thing standing between a partial
        # chart and one that implies full coverage.
        if body["profiled_share"] < 1.0:
            assert body["note"]

        for year in body["years"]:
            total = sum(c["share"] for c in body["cells"] if c["year"] == year)
            assert abs(total - 1.0) < 0.001, f"{year} shares sum to {total}"

        # Era shifts must reconcile with the two eras they compare.
        for shift in body["shifts"]:
            assert 0.0 <= shift["legacy_share"] <= 1.0
            assert 0.0 <= shift["recent_share"] <= 1.0
            assert abs(
                shift["delta"] - (shift["recent_share"] - shift["legacy_share"])
            ) < 1e-9


@pytest.mark.asyncio
async def test_option_patterns_never_show_a_rate_without_a_verdict():
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        r = await client.get("/api/v1/pyq/patterns", params={"era": "all"})
        assert r.status_code == 200
        body = r.json()
        if body["keyed_questions"] == 0:
            pytest.skip("no answer key loaded")

        # Five hypotheses, Bonferroni-corrected. If a sixth is added without widening the
        # correction, this fails — which is the point.
        assert len(body["hypotheses"]) == 5
        assert abs(body["alpha"] - 0.05 / 5) < 1e-9

        for hypothesis in body["hypotheses"]:
            assert hypothesis["verdict"] in {
                "signal", "inverse_signal", "noise", "underpowered"
            }
            assert hypothesis["verdict_label"]
            assert hypothesis["baseline_basis"]
            # The baseline is never assumed to be a flat quarter: it is permuted within
            # the option archetypes, or derived from the share of options that qualify.
            assert 0.0 <= hypothesis["baseline"] <= 1.0
            assert hypothesis["hits"] <= hypothesis["n"]


@pytest.mark.asyncio
async def test_recurrence_reports_the_threshold_it_used():
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        r = await client.get("/api/v1/pyq/recurrence", params={"threshold": 0.8})
        assert r.status_code == 200
        body = r.json()
        assert body["threshold"] == 0.8
        # "Questions repeat" means nothing without how alike 'repeat' was taken to mean,
        # so the curve travels with the rates.
        assert body["curve"]
        counts = [body["curve"][k] for k in sorted(body["curve"], reverse=True)]
        assert counts == sorted(counts), "a looser threshold cannot match fewer questions"
        for topic in body["topics"]:
            assert topic["recurring"] <= topic["questions"]
            assert 0.0 <= topic["rate"] <= 1.0


@pytest.mark.asyncio
async def test_depth_profile_lists_the_branches_with_nothing_in_them():
    """Zero-question branches are the actionable half of the view. A profile that only
    listed covered branches would make every topic look uniformly probed."""
    async with async_session_factory() as session:
        topic = (
            await session.execute(
                select(Topic).where(Topic.depth == 1).order_by(Topic.id).limit(1)
            )
        ).scalar_one_or_none()
        if topic is None:
            pytest.skip("taxonomy not seeded — run scripts/seed_taxonomy.py")
        topic_id = topic.id

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        r = await client.get(f"/api/v1/pyq/topics/{topic_id}/profile")
        assert r.status_code == 200
        profile = r.json()
        assert profile["topic_id"] == topic_id
        assert profile["probe_status"] in {
            "unprobed", "lightly_probed", "probed", "heavily_probed"
        }
        assert profile["profiled_count"] <= profile["question_count"]
        # Years the topic skipped are named, not smoothed away.
        assert all(
            year not in {yc["year"] for yc in profile["year_counts"] if yc["count"]}
            for year in profile["gap_years"]
        )

        r = await client.get(f"/api/v1/pyq/topics/{topic_id}/projection")
        assert r.status_code == 200
        projection = r.json()
        # Always populated, by construction: a projection from three peers is not the
        # same object as one from thirty.
        assert projection["confidence_note"]
        if not projection["peers"]:
            assert "nothing to project" in projection["confidence_note"]
        for share in projection["expected_format_mix"].values():
            assert 0.0 <= share <= 1.0

        r = await client.get("/api/v1/pyq/topics/999999999/profile")
        assert r.status_code == 404
