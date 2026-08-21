"""Out-of-sample, walk-forward, sensitivity and regime validation."""

from app.validation.multiple_testing import MultipleTestingDiagnostic, benjamini_hochberg
from app.validation.perturbation import PerturbationResult, evaluate_price_perturbation
from app.validation.qualification import (
    QualificationDecision,
    QualificationEvidence,
    QualificationRequirements,
    evaluate_paper_qualification,
)
from app.validation.regimes import (
    RegimeObservation,
    RegimePerformance,
    analyse_by_regime,
    classify_regimes,
)
from app.validation.sensitivity import ParameterSensitivityAnalyzer
from app.validation.walk_forward import WalkForwardConfig, WalkForwardValidator

__all__ = [
    "MultipleTestingDiagnostic",
    "ParameterSensitivityAnalyzer",
    "PerturbationResult",
    "QualificationDecision",
    "QualificationEvidence",
    "QualificationRequirements",
    "RegimeObservation",
    "RegimePerformance",
    "WalkForwardConfig",
    "WalkForwardValidator",
    "analyse_by_regime",
    "benjamini_hochberg",
    "classify_regimes",
    "evaluate_paper_qualification",
    "evaluate_price_perturbation",
]
