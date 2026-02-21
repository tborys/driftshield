from dataclasses import dataclass, field


@dataclass(slots=True)
class ClassificationResult:
    score: int
    likelihood: str
    is_candidate: bool
    signals: list[str] = field(default_factory=list)


@dataclass(slots=True)
class GraveyardCandidate:
    repo: str
    issue_number: int
    issue_url: str
    title: str
    evidence_text: str
    score: int
    likelihood: str
    signals: list[str]


@dataclass(slots=True)
class GraveyardCollectResult:
    total_issues: int
    candidate_count: int
    candidates: list[GraveyardCandidate]
