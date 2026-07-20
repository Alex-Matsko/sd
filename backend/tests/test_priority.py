import pytest

from app.core.enums import ImpactUrgencyLevel, Priority
from app.services import priority as priority_service


@pytest.mark.parametrize(
    "impact,urgency,expected",
    [
        (ImpactUrgencyLevel.HIGH, ImpactUrgencyLevel.HIGH, Priority.P1),
        (ImpactUrgencyLevel.HIGH, ImpactUrgencyLevel.MEDIUM, Priority.P2),
        (ImpactUrgencyLevel.MEDIUM, ImpactUrgencyLevel.HIGH, Priority.P2),
        (ImpactUrgencyLevel.LOW, ImpactUrgencyLevel.LOW, Priority.P4),
    ],
)
def test_compute_priority_matrix_lookup(db, impact, urgency, expected):
    assert priority_service.compute_priority(db, impact, urgency) == expected


def test_compute_priority_missing_rule_raises(db):
    from app.models.priority import ImpactUrgencyRule

    db.query(ImpactUrgencyRule).delete()
    db.commit()

    with pytest.raises(ValueError):
        priority_service.compute_priority(db, ImpactUrgencyLevel.HIGH, ImpactUrgencyLevel.HIGH)
