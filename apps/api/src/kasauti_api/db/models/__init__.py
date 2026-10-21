"""All ORM models. Importing this package registers every table on Base.metadata,
which Alembic autogenerate and SQLAdmin both rely on."""

from kasauti_api.db.models.benchmark import (
    BenchmarkAgreementMetric,
    BenchmarkReport,
    BenchmarkResult,
    BenchmarkRun,
    LabeledAnswer,
    LabeledAnswerSet,
)
from kasauti_api.db.models.billing import EvaluationCredit, Payment, Subscription
from kasauti_api.db.models.cost_ledger import LlmUsageEvent
from kasauti_api.db.models.evaluations import (
    AnswerSubmission,
    Evaluation,
    EvaluationStep,
    EvaluationStepCitation,
)
from kasauti_api.db.models.intelligence import TopicAnalysis, TopicNote
from kasauti_api.db.models.practice import (
    PracticeMode,
    PracticeSession,
    QuestionAttempt,
)
from kasauti_api.db.models.profiles import QuestionProfile
from kasauti_api.db.models.questions import (
    Question,
    QuestionEmbedding,
    QuestionOption,
    QuestionStimulus,
    QuestionTopicMap,
    SourceScan,
    StimulusKind,
)
from kasauti_api.db.models.taxonomy import Exam, Paper, PaperSubjectMap, Subject, Topic
from kasauti_api.db.models.users import User

__all__ = [
    "AnswerSubmission",
    "BenchmarkAgreementMetric",
    "BenchmarkReport",
    "BenchmarkResult",
    "BenchmarkRun",
    "Evaluation",
    "EvaluationCredit",
    "EvaluationStep",
    "EvaluationStepCitation",
    "Exam",
    "LabeledAnswer",
    "LabeledAnswerSet",
    "LlmUsageEvent",
    "Paper",
    "PaperSubjectMap",
    "Payment",
    "PracticeMode",
    "PracticeSession",
    "Question",
    "QuestionAttempt",
    "QuestionEmbedding",
    "QuestionOption",
    "QuestionProfile",
    "QuestionStimulus",
    "QuestionTopicMap",
    "SourceScan",
    "StimulusKind",
    "Subject",
    "Subscription",
    "Topic",
    "TopicAnalysis",
    "TopicNote",
    "User",
]
