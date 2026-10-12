"""学习路径端点(重设计)。

GET /api/learning/path —— 拓扑分层 + BKT 状态覆盖(纯派生视图)。
处理器用同步 def(FastAPI 自动放线程池)。
"""

from __future__ import annotations

from fastapi import APIRouter, Query

from services.learning.path import build_learning_path

router = APIRouter(prefix="/api/learning", tags=["learning"])


@router.get("/path")
def learning_path(learner: str = Query("default"), project_id: str = Query("default")):
    """分层学习路径:levels(Kahn 并列分层) + unresolved(环观察区) + 进度。"""
    return build_learning_path(project_id, learner)
