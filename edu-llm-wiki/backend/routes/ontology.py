"""EDU-ONTO 本体服务端点(v4 · 第二阶段 S2/S3)。

- GET  /api/ontology/schema            本体 schema 摘要(生成层/前端用,
                                        从单一事实来源派生)
- POST /api/ontology/reason            逐学习者推理(就绪/迁移/预警)
- GET  /api/ontology/tree              知识目录 + TeachingObject 六组(可带学习者状态)

处理器用同步 def(FastAPI 自动放线程池)——HermiT 推理是阻塞的 Java
子进程调用,不能占事件循环。
"""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel

from services.ontology import PAGE_TEMPLATES, RELATION_SPECS, VERSION
from services.ontology.abox import OntologyViolation, get_abox
from services.ontology.edu_onto import KNOWLEDGE_CLASS_NAMES
from services.ontology.reasoning import build_learner_view

router = APIRouter(prefix="/api/ontology", tags=["ontology"])


class ReasonRequest(BaseModel):
    learner: str


@router.get("/schema")
def ontology_schema(project_id: str = Query("default")):
    """本体 schema 摘要，TeachingObject 分组直接派生自 ontology_v2。"""
    from services.ontology_v2 import TEACHING_CLASS_GROUPS, TEACHING_CLASS_LABELS

    return {
        "version": VERSION,
        "atom_types": list(KNOWLEDGE_CLASS_NAMES),
        "teaching_object_groups": [
            {
                "name": group_name,
                "zh": str(group["zh"]),
                "folder": str(group["folder"]),
                "classes": [
                    {
                        "name": class_name,
                        "zh": TEACHING_CLASS_LABELS.get(class_name, (class_name, ""))[0],
                        "description": TEACHING_CLASS_LABELS.get(class_name, (class_name, ""))[1],
                    }
                    for class_name in group.get("classes", ())
                ],
            }
            for group_name, group in TEACHING_CLASS_GROUPS.items()
        ],
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
    """知识目录与六组教学对象;带 learner 时附状态视图。"""
    # derive 模块(S3)尚未实现,惰性导入避免阻塞整个后端启动
    try:
        from services.ontology.derive import generate_tree
    except ImportError as exc:
        raise HTTPException(
            status_code=501,
            detail="ontology tree projection is unavailable",
        ) from exc
    try:
        abox = get_abox(project_id)
        return generate_tree(abox, learner=learner)
    except OntologyViolation as exc:
        raise HTTPException(status_code=404, detail=exc.message) from exc
