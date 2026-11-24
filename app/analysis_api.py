"""Tenant-scoped asynchronous conversation and insight artifact API."""
import json
from datetime import datetime, timedelta, timezone
from typing import Literal

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query
from fastapi.responses import Response
from pydantic import BaseModel, Field, field_validator
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.analysis_agent import execute_run, effective_thinking
from app.analysis_tools import TOOL_GUIDE
from app.config import settings
from app.db import get_db
from app.models import AnalysisRun, AnalysisSession, InsightArtifact
from app.services import owned


class SessionIn(BaseModel):
    title: str = Field(default='新的研究对话', min_length=1, max_length=240)


class MessageIn(BaseModel):
    question: str = Field(min_length=2, max_length=2000)
    request_id: str = Field(min_length=8, max_length=80)

    @field_validator('question')
    @classmethod
    def not_blank(cls, value):
        if not value.strip():
            raise ValueError('empty question')
        return value.strip()


def timestamp(value):
    if value is None:
        return None
    return value.replace(tzinfo=value.tzinfo or timezone.utc).isoformat()


def session_json(session):
    return {'id': session.id, 'title': session.title, 'created_at': timestamp(session.created_at),
            'updated_at': timestamp(session.updated_at)}


def artifact_json(artifact, detail=False):
    d = {'id': artifact.id, 'session_id': artifact.session_id, 'run_id': artifact.run_id,
         'title': artifact.title, 'created_at': timestamp(artifact.created_at),
         'summary': artifact.content['summary'], 'synthetic': artifact.content['synthetic']}
    if detail:
        d['content'] = artifact.content
    return d


def expire_stale(db, runs):
    now = datetime.now(timezone.utc)
    changed = False
    for run in runs:
        created = run.created_at.replace(tzinfo=run.created_at.tzinfo or timezone.utc)
        if run.status in ('queued', 'running') and now-created > timedelta(minutes=10):
            run.status, run.error, run.finished_at = 'failed', '任务已过期或服务曾重启，请重试。', now
            changed = True
    if changed:
        db.commit()


def run_json(db, run):
    artifact = db.scalar(select(InsightArtifact).where(InsightArtifact.run_id == run.id,
                          InsightArtifact.tenant_id == run.tenant_id))
    return {'id': run.id, 'session_id': run.session_id, 'question': run.question, 'status': run.status,
            'trace': run.trace, 'answer': run.answer, 'error': run.error, 'model': run.model,
            'usage': run.usage, 'created_at': timestamp(run.created_at),
            'finished_at': timestamp(run.finished_at),
            'artifact': artifact_json(artifact, True) if artifact else None}


def markdown_report(artifact):
    c = artifact.content
    lines = [f'# {artifact.title}', '', f'研究问题：{c["question"]}', '',
             f'生成时间（UTC）：{timestamp(artifact.created_at)}', f'模型：{c["model"]}', f'本体版本：{c.get("ontology_version", "历史产物未记录")}', '',
             '> 模型解释需研究者复核；引用 ID 核验通过不等于所有自然语言结论已经验证。', '',
             '## 摘要', '', c['summary'], '', '## 洞察', '']
    kinds = {'observation': '数据观察', 'hypothesis': '待验证假设', 'recommendation': '行动建议'}
    for finding in c['findings']:
        lines.extend([f'### {kinds[finding["kind"]]}：{finding["title"]}', '', finding['interpretation'], '',
                      '事实引用：'+', '.join(finding['fact_ids']),
                      '证据引用：'+', '.join(finding['evidence_ids']), ''])
    lines.extend(['## 程序计算的事实', ''])
    for fact in c['facts']:
        source = next((r for r in c['tool_results'] if any(f['id'] == fact['id'] for f in r['facts'])), {})
        scope_context = {'scope': fact.get('scope', source.get('scope')), 'compare_to': source.get('compare_to'), **fact['context']}
        lines.extend([f'- [{fact["id"]}] {fact["label"]}：{fact["value"]}{fact["unit"]}；样本量 {fact["sample_size"]}；口径 {json.dumps(scope_context, ensure_ascii=False)}'])
    lines.extend(['', '## 下一步验证', ''])
    for action in c['next_actions']:
        lines.extend([f'- {action["action"]}（{", ".join(action["fact_ids"])}）',
                      f'  验证方法：{action["validation_plan"]}'])
    lines.extend(['', '## 证据来源', ''])
    for ref in c['citations']:
        lines.extend([f'### {ref["source_id"]}', '', f'证据 ID：{ref["id"]}；合成：{ref["synthetic"]}；标签来源：{ref["annotation_type"]}', '',
                      *['> '+line for line in ref['quote'].splitlines()], ''])
    lines.extend(['## 限制与口径', '', *['- '+x for x in c['limitations']], '',
                  '## 工具执行记录', '', '```json',
                  json.dumps([{'tool': x['tool'], 'scope': x['scope'], 'graph': x.get('graph')}
                              for x in c['tool_results']], ensure_ascii=False, indent=2), '```', ''])
    return '\n'.join(lines)


def register_analysis(app, tenant_auth):
    router = APIRouter(prefix='/v1/agent', tags=['Insight Agent'])

    @router.get('/capabilities')
    def capabilities(tenant: str = Depends(tenant_auth)):
        return {'enabled': settings.llm_enabled, 'model': settings.llm_model,
                'tools': TOOL_GUIDE, 'max_tool_calls': min(6, max(1, settings.agent_max_tool_calls)),
                'execution': 'in_process_background_task', 'timeout_seconds': 420,
                'thinking': effective_thinking(), 'parallel_tools': settings.agent_parallel_tools}

    @router.post('/sessions', status_code=201)
    def create_session(payload: SessionIn, db: Session = Depends(get_db), tenant: str = Depends(tenant_auth)):
        row = AnalysisSession(tenant_id=tenant, title=payload.title)
        db.add(row)
        db.commit()
        return session_json(row)

    @router.get('/sessions')
    def list_sessions(limit: int = Query(30, ge=1, le=100), db: Session = Depends(get_db),
                      tenant: str = Depends(tenant_auth)):
        rows = db.scalars(select(AnalysisSession).where(AnalysisSession.tenant_id == tenant)
                          .order_by(AnalysisSession.updated_at.desc()).limit(limit)).all()
        return [session_json(s) for s in rows]

    @router.get('/sessions/{session_id}')
    def get_session(session_id: str, db: Session = Depends(get_db), tenant: str = Depends(tenant_auth)):
        session = owned(db, AnalysisSession, tenant, session_id)
        recent = db.scalars(select(AnalysisRun).where(AnalysisRun.session_id == session.id,
                            AnalysisRun.tenant_id == tenant).order_by(AnalysisRun.created_at.desc()).limit(100)).all()
        expire_stale(db, recent)
        return {**session_json(session), 'runs': [run_json(db, r) for r in reversed(recent)]}

    @router.post('/sessions/{session_id}/messages', status_code=202)
    def message(session_id: str, payload: MessageIn, tasks: BackgroundTasks,
                db: Session = Depends(get_db), tenant: str = Depends(tenant_auth)):
        if not settings.llm_enabled:
            raise HTTPException(503, 'LLM 未启用，请配置模型服务后使用洞察 Agent。')
        with db.begin():
            session = db.scalar(select(AnalysisSession).where(AnalysisSession.id == session_id,
                                AnalysisSession.tenant_id == tenant).with_for_update())
            if not session:
                raise HTTPException(404, 'research session not found')
            duplicate = db.scalar(select(AnalysisRun).where(AnalysisRun.session_id == session.id,
                                  AnalysisRun.request_id == payload.request_id))
            if duplicate:
                if duplicate.question != payload.question:
                    raise HTTPException(409, 'request_id already used for a different question')
                return {'id': duplicate.id, 'status': duplicate.status, 'session_id': session.id}
            active = db.scalars(select(AnalysisRun).where(AnalysisRun.session_id == session.id,
                               AnalysisRun.status.in_(['queued', 'running']))).all()
            now = datetime.now(timezone.utc)
            for run in active:
                created = run.created_at.replace(tzinfo=run.created_at.tzinfo or timezone.utc)
                if now-created < timedelta(minutes=10):
                    raise HTTPException(409, '上一轮分析仍在进行，请等待完成后继续追问。')
                run.status, run.error, run.finished_at = 'failed', '任务已过期或服务曾重启，请重试。', now
            run = AnalysisRun(tenant_id=tenant, session_id=session.id, request_id=payload.request_id,
                              question=payload.question, status='queued', model=settings.llm_model)
            db.add(run)
            db.flush()
            session.updated_at = now
            run_id = run.id
        tasks.add_task(execute_run, run_id)
        return {'id': run_id, 'status': 'queued', 'session_id': session_id}

    @router.get('/runs/{run_id}')
    def get_run(run_id: str, db: Session = Depends(get_db), tenant: str = Depends(tenant_auth)):
        run = owned(db, AnalysisRun, tenant, run_id)
        expire_stale(db, [run])
        return run_json(db, run)

    @router.get('/artifacts')
    def list_artifacts(limit: int = Query(30, ge=1, le=100), db: Session = Depends(get_db),
                       tenant: str = Depends(tenant_auth)):
        return [artifact_json(a) for a in db.scalars(select(InsightArtifact).where(
            InsightArtifact.tenant_id == tenant).order_by(InsightArtifact.created_at.desc()).limit(limit)).all()]

    @router.get('/artifacts/{artifact_id}')
    def get_artifact(artifact_id: str, db: Session = Depends(get_db), tenant: str = Depends(tenant_auth)):
        return artifact_json(owned(db, InsightArtifact, tenant, artifact_id), True)

    @router.get('/artifacts/{artifact_id}/export')
    def export_artifact(artifact_id: str, format: Literal['markdown', 'json'] = 'markdown',
                        db: Session = Depends(get_db), tenant: str = Depends(tenant_auth)):
        artifact = owned(db, InsightArtifact, tenant, artifact_id)
        content = markdown_report(artifact) if format == 'markdown' else json.dumps(artifact_json(artifact, True), ensure_ascii=False, indent=2)
        ext = 'md' if format == 'markdown' else 'json'
        return Response(content, media_type='text/markdown' if format == 'markdown' else 'application/json',
                        headers={'Content-Disposition': f'attachment; filename="insight-{artifact.id}.{ext}"'})

    app.include_router(router)
