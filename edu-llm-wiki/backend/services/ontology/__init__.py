"""EDU-ONTO 教育学本体包(v4 新模块,与现有引擎并行)。"""

from services.ontology.edu_onto import (
    BASE_IRI,
    MASTERY_THRESHOLD,
    PAGE_TEMPLATES,
    RELATION_SPECS,
    VERSION,
    EduOnto,
    RelationSpec,
    build_ontology,
    get_edu_ontology,
)

__all__ = [
    "BASE_IRI",
    "MASTERY_THRESHOLD",
    "PAGE_TEMPLATES",
    "RELATION_SPECS",
    "VERSION",
    "EduOnto",
    "RelationSpec",
    "build_ontology",
    "get_edu_ontology",
]
