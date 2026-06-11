from app.forensics.models import DocumentClass, ForensicFinding, Severity
from app.forensics.scorer import score_findings


def make_finding(technique="typography", severity=Severity.MEDIUM, page=0,
                 bbox=(10, 10, 50, 50), score=0.5):
    return ForensicFinding(
        technique=technique, severity=severity, page=page,
        bbox=bbox, score=score, explanation="test",
    )


def test_no_findings_zero_risk():
    risk, review, _ = score_findings([], DocumentClass.SCANNED)
    assert risk == 0.0
    assert review is False


def test_risk_bounded_0_1():
    findings = [make_finding(score=1.0) for _ in range(10)]
    risk, _, _ = score_findings(findings, DocumentClass.SCANNED)
    assert 0.0 <= risk <= 1.0


def test_high_severity_forces_review():
    f = make_finding(severity=Severity.HIGH, score=0.1)
    _, review, _ = score_findings([f], DocumentClass.SCANNED)
    assert review is True


def test_cross_reinforcement_same_space():
    # Dos técnicas distintas sobre bboxes solapados (mismo espacio: puntos PDF)
    # deben elevarse mutuamente a HIGH y duplicar score.
    a = make_finding(technique="typography", bbox=(10, 10, 50, 50), score=0.3)
    b = make_finding(technique="ela", bbox=(12, 12, 52, 52), score=0.3)
    _, review, scored = score_findings([a, b], DocumentClass.SCANNED)
    assert all(f.severity == Severity.HIGH for f in scored)
    assert all(abs(f.score - 0.6) < 1e-9 for f in scored)
    assert review is True


def test_no_reinforcement_for_same_technique():
    a = make_finding(technique="typography", bbox=(10, 10, 50, 50), score=0.3)
    b = make_finding(technique="typography", bbox=(12, 12, 52, 52), score=0.3)
    _, _, scored = score_findings([a, b], DocumentClass.SCANNED)
    assert all(f.severity == Severity.MEDIUM for f in scored)


def test_no_reinforcement_across_pages():
    a = make_finding(technique="typography", page=0)
    b = make_finding(technique="ela", page=1)
    _, _, scored = score_findings([a, b], DocumentClass.SCANNED)
    assert all(f.severity == Severity.MEDIUM for f in scored)
