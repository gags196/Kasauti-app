"""question profiles and analysis backtest scope

Revision ID: 66db809bca5b
Revises: a6519429a0b0
Create Date: 2026-08-18 11:56:28.818559

Hand-corrected after autogenerate, which got three things wrong here — the same three
ARCHITECTURE.md warns about:

1. `format` and `regex_format` are both `question_format`, and autogenerate emitted an
   inline `sa.Enum` for each, so the DDL tried to CREATE TYPE question_format twice and
   aborted. The types are created explicitly and referenced with create_type=False.
2. `classified_by` reuses the existing `tagged_by` type; the inline enum would have tried
   to create it again.
3. The two new `llm_feature` values are invisible to autogenerate entirely and need
   hand-written ALTER TYPE.

The downgrade also drops the types it created. Without that, a
downgrade → upgrade cycle fails with "type question_format already exists" — the bug the
existing 7546b8c255f2 downgrade still carries.
"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = '66db809bca5b'
down_revision: str | None = 'a6519429a0b0'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

QUESTION_FORMAT = (
    "statement_evaluation", "how_many_correct", "pairs_matched", "match_the_following",
    "assertion_reason", "chronological_order", "single_fact", "passage_based", "other",
)
QUESTION_DEPTH = ("recall", "comprehension", "application", "analysis")
OPTION_ARCHETYPE = (
    "subset_of_numbered", "count_of_correct", "entity_choice", "numeric", "ordering",
    "other",
)


def _enum(values: tuple[str, ...], name: str) -> postgresql.ENUM:
    """Reference a type that already exists rather than emitting CREATE TYPE."""
    return postgresql.ENUM(*values, name=name, create_type=False)


def upgrade() -> None:
    # Postgres allows ADD VALUE inside a transaction but forbids *using* the new value
    # in that same transaction. Nothing below inserts one, so this is safe here.
    op.execute("ALTER TYPE llm_feature ADD VALUE IF NOT EXISTS 'question_profile'")
    op.execute("ALTER TYPE llm_feature ADD VALUE IF NOT EXISTS 'prediction_scoring'")

    question_format = sa.Enum(*QUESTION_FORMAT, name="question_format")
    question_depth = sa.Enum(*QUESTION_DEPTH, name="question_depth")
    option_archetype = sa.Enum(*OPTION_ARCHETYPE, name="option_archetype")
    bind = op.get_bind()
    question_format.create(bind, checkfirst=True)
    question_depth.create(bind, checkfirst=True)
    option_archetype.create(bind, checkfirst=True)

    op.create_table(
        'question_profiles',
        sa.Column('question_id', sa.Integer(), nullable=False),
        # --- classified by the batched LLM pass; NULL means "not yet", never a guess ---
        sa.Column('format', _enum(QUESTION_FORMAT, 'question_format'), nullable=True),
        sa.Column('depth', _enum(QUESTION_DEPTH, 'question_depth'), nullable=True),
        sa.Column('current_affairs_anchored', sa.Boolean(), nullable=True),
        sa.Column('llm_confidence', sa.Float(), nullable=True),
        sa.Column('model_name', sa.String(length=128), nullable=True),
        sa.Column('prompt_ref', sa.String(length=256), nullable=True),
        sa.Column('classified_by', postgresql.ENUM(name='tagged_by', create_type=False),
                  nullable=True),
        sa.Column('classified_at', sa.DateTime(timezone=True), nullable=True),
        # --- derived in Python, no LLM; rebuilt whenever derived_rev moves ---
        sa.Column('derived_rev', sa.Integer(), nullable=False),
        sa.Column('derived_at', sa.DateTime(timezone=True),
                  server_default=sa.text('now()'), nullable=False),
        sa.Column('regex_format', _enum(QUESTION_FORMAT, 'question_format'),
                  nullable=True),
        sa.Column('statement_count', sa.Integer(), nullable=True),
        sa.Column('option_count', sa.Integer(), nullable=False),
        sa.Column('option_archetype', _enum(OPTION_ARCHETYPE, 'option_archetype'),
                  nullable=True),
        sa.Column('stem_chars_en', sa.Integer(), nullable=True),
        sa.Column('stem_chars_hi', sa.Integer(), nullable=True),
        sa.Column('has_table', sa.Boolean(), nullable=False),
        sa.Column('has_all_of_above', sa.Boolean(), nullable=False),
        sa.Column('has_none_of_above', sa.Boolean(), nullable=False),
        # Denormalised from question_options so every option statistic is a GROUP BY.
        sa.Column('correct_label', sa.String(length=4), nullable=True),
        sa.Column('correct_is_longest', sa.Boolean(), nullable=True),
        sa.Column('longest_margin', sa.Float(), nullable=True),
        sa.Column('dated_option_count', sa.Integer(), nullable=False,
                  server_default=sa.text('0')),
        sa.Column('dated_correct', sa.Boolean(), nullable=True),
        sa.ForeignKeyConstraint(['question_id'], ['questions.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('question_id'),
    )
    op.create_index('ix_question_profiles_archetype', 'question_profiles',
                    ['option_archetype'], unique=False)
    op.create_index('ix_question_profiles_format', 'question_profiles',
                    ['format', 'depth'], unique=False)
    op.create_index('ix_question_profiles_rev', 'question_profiles',
                    ['derived_rev'], unique=False)

    op.add_column('topic_analyses', sa.Column('is_backtest', sa.Boolean(),
                                              server_default=sa.text('false'),
                                              nullable=False))
    op.add_column('topic_analyses', sa.Column('corpus_year_min', sa.Integer(),
                                              nullable=True))
    op.add_column('topic_analyses', sa.Column('corpus_year_max', sa.Integer(),
                                              nullable=True))
    op.create_index('ix_topic_analyses_live', 'topic_analyses',
                    ['topic_id', 'scope', 'is_backtest', 'generated_at'], unique=False)


def downgrade() -> None:
    op.drop_index('ix_topic_analyses_live', table_name='topic_analyses')
    op.drop_column('topic_analyses', 'corpus_year_max')
    op.drop_column('topic_analyses', 'corpus_year_min')
    op.drop_column('topic_analyses', 'is_backtest')
    op.drop_index('ix_question_profiles_rev', table_name='question_profiles')
    op.drop_index('ix_question_profiles_format', table_name='question_profiles')
    op.drop_index('ix_question_profiles_archetype', table_name='question_profiles')
    op.drop_table('question_profiles')
    # Autogenerate never emits these, and without them a downgrade → upgrade cycle
    # fails on the second CREATE TYPE. tagged_by is left alone: it predates this
    # migration and other tables use it.
    op.execute("DROP TYPE IF EXISTS option_archetype")
    op.execute("DROP TYPE IF EXISTS question_depth")
    op.execute("DROP TYPE IF EXISTS question_format")
    # llm_feature values are deliberately not removed — Postgres cannot drop an enum
    # value, and leaving them costs nothing.
