"""EDU-ONTO 本体服务端点(v4 · 第二阶段 S2/S3)。

- GET  /api/ontology/schema            本体 schema 摘要(生成层/前端用,
                                        从单一事实来源派生)
- POST /api/ontology/reason            逐学习者推理(就绪/迁移/预警)
- GET  /api/ontology/tree              五区目录树(可带学习者状态)

处理器用同步 def(FastAPI 自动放线程池)——HermiT 推理是阻塞的 Java
子进程调用,不能占事件循环。
"""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel

from services.ontology import PAGE_TEMPLATES, RELATION_SPECS, VERSION
from services.ontology.abox import OntologyViolation, get_abox
from services.ontology.derive import generate_tree
from services.ontology.edu_onto import KNOWLEDGE_CLASS_NAMES
from services.ontology.reasoning import build_learner_view

router = APIRouter(prefix="/api/ontology", tags=["ontology"])


class ReasonRequest(BaseModel):
    learner: str


@router.get("/schema")
def ontology_schema(project_id: str = Query("default")):
    """本体 schema 摘要(关系词汇表 + 页面模板 + 原子类型)。"""
    return {
        "version": VERSION,
        "atom_types": list(KNOWLEDGE_CLASS_NAMES),
        "relations": [
            {
                "name": s.name,
                "zh": s.zh,
                "domain": list(s.domain),
                "range": list(s.range),
                "characteristics": s.characteristics,
                "rationale": s.rationale,
            }
            for s in RELATION_SPECS
        ],
        "page_templates": {
            template: {"atom_class": cls, "zh": zh}
            for template, (cls, zh) in PAGE_TEMPLATES.items()
        },
    }


@router.post("/reason")
def reason(req: ReasonRequest, project_id: str = Query("default")):
    """逐学习者推理:已掌握/就绪/迁移候选/迷思预警/闭包先修边。"""
    try:
        abox = get_abox(project_id)
        return build_learner_view(abox, req.learner).to_dict()
    except OntologyViolation as exc:
        raise HTTPException(status_code=404, detail=exc.message) from exc


@router.get("/tree")
def tree(project_id: str = Query("default"), learner: str | None = Query(None)):
    """五区目录树;带 learner 时附学习区(就绪/迁移/已掌握/预警)。"""
    try:
        abox = get_abox(project_id)
        return generate_tree(abox, learner=learner)
    except OntologyViolation as exc:
        raise HTTPException(status_code=404, detail=exc.message) from exc
