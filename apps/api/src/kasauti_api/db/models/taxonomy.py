import enum

from sqlalchemy import Enum, ForeignKey, Index, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy_utils import LtreeType

from kasauti_api.db.base import Base


class Stage(enum.Enum):
    prelims = "prelims"
    mains = "mains"


class Exam(Base):
    __tablename__ = "exams"

    id: Mapped[int] = mapped_column(primary_key=True)
    code: Mapped[str] = mapped_column(String(32), unique=True)  # e.g. "upsc-cse"
    name_en: Mapped[str] = mapped_column(String(200))
    name_hi: Mapped[str] = mapped_column(String(200))

    papers: Mapped[list["Paper"]] = relationship(back_populates="exam")


class Paper(Base):
    __tablename__ = "papers"

    id: Mapped[int] = mapped_column(primary_key=True)
    exam_id: Mapped[int] = mapped_column(ForeignKey("exams.id"))
    code: Mapped[str] = mapped_column(String(64))  # e.g. "mains-maths-1", "mains-gs2"
    name_en: Mapped[str] = mapped_column(String(200))
    name_hi: Mapped[str] = mapped_column(String(200))
    stage: Mapped[Stage] = mapped_column(Enum(Stage, name="stage"))
    # Set for optional-subject papers (e.g. "maths"); NULL for GS/essay papers.
    optional_subject_code: Mapped[str | None] = mapped_column(String(64))

    exam: Mapped[Exam] = relationship(back_populates="papers")
    subjects: Mapped[list["Subject"]] = relationship(back_populates="paper")

    __table_args__ = (Index("ix_papers_exam_code", "exam_id", "code", unique=True),)


class PaperSubjectMap(Base):
    """Tag-target mapping: which subjects' topic trees a paper's questions are
    tagged against, beyond the subject's home paper.

    UPSC publishes a detailed syllabus only for Mains; Prelims questions map
    onto the Mains topic tree. A prelims paper therefore has no subjects of its
    own — it points here at one or more Mains subjects.
    """

    __tablename__ = "paper_subject_map"

    paper_id: Mapped[int] = mapped_column(ForeignKey("papers.id"), primary_key=True)
    subject_id: Mapped[int] = mapped_column(ForeignKey("subjects.id"), primary_key=True)
    # Deepest topic level this paper may tag against in that subject. NULL = whole tree.
    # Used when a paper touches a subject only glancingly: Prelims tests ethics rarely
    # (2026 had three items; earlier years none), so it tags gs4 at the broad level
    # instead of pulling 35 fine-grained ethics topics into every tagging prompt.
    max_topic_depth: Mapped[int | None] = mapped_column(Integer, nullable=True)


class Subject(Base):
    __tablename__ = "subjects"

    id: Mapped[int] = mapped_column(primary_key=True)
    paper_id: Mapped[int] = mapped_column(ForeignKey("papers.id"))
    code: Mapped[str] = mapped_column(String(64))
    name_en: Mapped[str] = mapped_column(String(200))
    name_hi: Mapped[str] = mapped_column(String(200))

    paper: Mapped[Paper] = relationship(back_populates="subjects")
    topics: Mapped[list["Topic"]] = relationship(back_populates="subject")

    __table_args__ = (Index("ix_subjects_paper_code", "paper_id", "code", unique=True),)


class Topic(Base):
    __tablename__ = "topics"

    id: Mapped[int] = mapped_column(primary_key=True)
    subject_id: Mapped[int] = mapped_column(ForeignKey("subjects.id"))
    parent_id: Mapped[int | None] = mapped_column(ForeignKey("topics.id"))
    # Materialized hierarchy path, e.g. "maths.calculus.definite_integrals"
    path: Mapped[str] = mapped_column(LtreeType, unique=True)
    depth: Mapped[int] = mapped_column()
    slug: Mapped[str] = mapped_column(String(128))
    name_en: Mapped[str] = mapped_column(String(300))
    name_hi: Mapped[str] = mapped_column(String(300))
    description_en: Mapped[str | None] = mapped_column(Text)
    description_hi: Mapped[str | None] = mapped_column(Text)

    subject: Mapped[Subject] = relationship(back_populates="topics")
    parent: Mapped["Topic | None"] = relationship(remote_side=[id])

    __table_args__ = (
        # GiST index makes ancestor/descendant queries (path <@ 'maths.calculus') fast.
        Index("ix_topics_path_gist", "path", postgresql_using="gist"),
    )
