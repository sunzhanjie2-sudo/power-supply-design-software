"""Loopback-only FastAPI transport; no arbitrary filesystem/command endpoints."""
import asyncio
from contextlib import asynccontextmanager
import ipaddress
from pathlib import Path
import re
import secrets
from urllib.parse import urlsplit

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, JSONResponse, HTMLResponse, Response
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, ConfigDict, Field
from typing import Any, Literal

from .jobs import JobManager
from .metadata import bootstrap, preview, read_example, normalize_config


class StrictModel(BaseModel):
    model_config = ConfigDict(extra='forbid', strict=True)


class DesignRequest(StrictModel):
    spec: dict[str, Any]
    cross_regulation: bool = False


class CurveRequest(StrictModel):
    filename: str = Field(min_length=1,max_length=250)
    content: str = Field(max_length=5*1024*1024)
    target: str = Field(pattern=r'^(Q1:(transfer|charge)|D1|D2|D_IN|D_OUT|D_[OFB][1-6])$')


class CurveApply(CurveRequest):
    spec: dict[str, Any]
    index: int = Field(default=0,ge=0,le=99)
    x_multiplier: float = Field(default=1.,gt=0,le=1e12)
    y_multiplier: float = Field(default=1.,gt=0,le=1e12)
    plateau_start: float | None = None
    plateau_end: float | None = None


class ExportRequest(StrictModel):
    format: Literal['xlsx','docx','json','zip','comparison']
    mos_real_time: bool = False


class ActionRequest(StrictModel):
    action: Literal['tune', 'compensate', 'sweep', 'find_target', 'optimize', 'corners', 'loop_response', 'winding_preview']
    options: dict[str, Any] = Field(default_factory=dict)


class WorkspaceRequest(StrictModel):
    project: dict[str, Any]


def create_app(*, testing=False, pcs_root=None):
    token=secrets.token_urlsafe(32)
    @asynccontextmanager
    async def lifespan(app):
        manager=JobManager(presentation='pcs' if pcs_root else 'default')
        app.state.jobs=manager
        app.state.bootstrap=await asyncio.to_thread(bootstrap)
        try:
            yield
        finally:
            await asyncio.to_thread(manager.close)

    app=FastAPI(title='Power Design · Local API',version='0.2.0',lifespan=lifespan,
                docs_url=None,redoc_url=None,openapi_url=None)

    @app.middleware('http')
    async def local_security(request: Request, call_next):
        host=urlsplit('//'+request.headers.get('host','')).hostname
        allowed={'127.0.0.1','localhost','::1'} | ({'testserver'} if testing else set())
        if host not in allowed:
            return JSONResponse(dict(error='仅允许本机访问'),status_code=403)
        client=request.client.host if request.client else ''
        try:
            local=ipaddress.ip_address(client).is_loopback
        except ValueError:
            local=testing and client=='testclient'
        if not local or request.headers.get('sec-fetch-site')=='cross-site':
            return JSONResponse(dict(error='拒绝非本地或跨站请求'),status_code=403)
        origin=request.headers.get('origin')
        if origin and origin.rstrip('/') != request.url.scheme+'://'+request.headers['host']:
            return JSONResponse(dict(error='拒绝跨来源请求'),status_code=403)
        if request.url.path.startswith('/api/') and request.url.path not in ('/api/bootstrap','/api/health'):
            if not secrets.compare_digest(request.headers.get('x-power-token',''),token):
                return JSONResponse(dict(error='本地会话已过期，请刷新页面'),status_code=403)
        length=request.headers.get('content-length')
        if length:
            try:
                if int(length)>16*1024*1024:
                    return JSONResponse(dict(error='请求超过16 MiB'),status_code=413)
            except ValueError:
                return JSONResponse(dict(error='无效请求长度'),status_code=400)
        if request.method in ('POST','PUT','PATCH'):
            parts=[]; total=0
            async for part in request.stream():
                total += len(part)
                if total>16*1024*1024:
                    return JSONResponse(dict(error='请求超过16 MiB'),status_code=413)
                parts.append(part)
            request._body=b''.join(parts)
        response=await call_next(request)
        response.headers.update({
            'X-Content-Type-Options':'nosniff','X-Frame-Options':'DENY',
            'Referrer-Policy':'no-referrer','Cache-Control':'no-store',
            'Content-Security-Policy':"default-src 'self'; img-src 'self' blob: data:; style-src 'self' 'unsafe-inline'; connect-src 'self'; frame-ancestors 'none'; object-src 'none'; base-uri 'self'"})
        return response

    @app.exception_handler(ValueError)
    async def invalid(request,exc):
        return JSONResponse(dict(error=str(exc)),status_code=422)

    @app.exception_handler(KeyError)
    async def missing(request,exc):
        return JSONResponse(dict(error=str(exc).strip("'")),status_code=404)

    @app.get('/api/health')
    async def health():
        return dict(app='power-design-local-web',version='0.2.0',local_only=True)

    @app.get('/api/bootstrap')
    async def initial(request: Request):
        return dict(request.app.state.bootstrap,token=token)

    @app.get('/api/ldo/defaults')
    async def ldo_defaults():
        from ldo import DEFAULTS,FIELDS
        return dict(spec=DEFAULTS,fields=FIELDS)

    @app.post('/api/ldo/calculate')
    async def ldo_calculate(body:DesignRequest):
        from ldo import calculate
        return await asyncio.to_thread(calculate,body.spec)

    @app.post('/api/ldo/export/{kind}')
    async def ldo_export(kind:str,body:DesignRequest):
        if kind not in ('docx','xlsx','json'):raise ValueError('LDO 仅支持 docx/xlsx/json')
        def generate():
            import tempfile
            from power_units import export_ldo
            with tempfile.TemporaryDirectory(prefix='ldo-report-') as folder:
                path=Path(folder)/('LDO.'+kind);result=export_ldo(body.spec,path)
                return path.read_bytes(),result['media_type']
        data,media=await asyncio.to_thread(generate)
        return Response(data,media_type=media,headers={'Content-Disposition':'attachment; filename="LDO.'+kind+'"'})

    @app.get('/api/workspace/ldo-example')
    async def ldo_example():
        from system_workspace import load_project,checks
        def load():
            p=load_project(Path(__file__).parent.parent/'examples/SYSTEM_LDO.json')
            return dict(project=p,checks=checks(p))
        return await asyncio.to_thread(load)

    @app.get('/api/examples/{name}')
    async def example(name: str):
        return await asyncio.to_thread(read_example,name)

    @app.get('/api/manual')
    async def manual():
        # A single shipped white-listed document, never a client-supplied path.
        from app_resources import resource_path
        path = resource_path('计算方法与公式说明.docx')
        if not path.is_file():
            raise HTTPException(404, '计算方法与公式说明文档未找到')
        return FileResponse(path, media_type='application/vnd.openxmlformats-officedocument.wordprocessingml.document', filename=path.name)

    @app.get('/api/tutorial')
    async def tutorial():
        # Fixed shipped tutorial only; do not expose filesystem paths.
        from app_resources import resource_path
        path = resource_path('多路反激电源设计入门教程.docx')
        if not path.is_file():
            raise HTTPException(404, '多路反激电源设计入门教程未找到，请保留完整程序目录')
        return FileResponse(path, media_type='application/vnd.openxmlformats-officedocument.wordprocessingml.document', filename=path.name)

    @app.post('/api/preview')
    async def preview_input(body: DesignRequest):
        from design_engine.contracts import json_value
        return json_value(await asyncio.to_thread(preview,body.spec))

    @app.post('/api/config')
    async def normalize(body: DesignRequest):
        from design_engine.contracts import json_value
        return json_value(await asyncio.to_thread(normalize_config,body.spec))

    @app.post('/api/curves/inspect')
    async def inspect(body: CurveRequest):
        from .curves import inspect_curve
        return await asyncio.to_thread(inspect_curve,body.filename,body.content,body.target)

    @app.post('/api/curves/apply')
    async def apply(body: CurveApply):
        from .curves import apply_curve
        from design_engine.contracts import json_value
        return json_value(await asyncio.to_thread(apply_curve,**body.model_dump()))

    @app.post('/api/jobs',status_code=202)
    async def submit(body: DesignRequest,request: Request):
        return request.app.state.jobs.submit(body.spec,body.cross_regulation)

    @app.get('/api/jobs/{identity}')
    async def status(identity: str,request: Request):
        return request.app.state.jobs.status(identity)

    @app.get('/api/jobs/{identity}/result')
    async def result(identity: str,request: Request):
        return request.app.state.jobs.result(identity)

    @app.post('/api/jobs/{identity}/cancel')
    async def cancel(identity: str,request: Request):
        return request.app.state.jobs.cancel(identity)

    @app.get('/api/jobs/{identity}/chart/{kind}')
    async def chart(identity: str,kind: str,request: Request,case: Literal['Vinmin','Vinmax']='Vinmin',output: int=1):
        from .charts import KINDS
        if kind not in KINDS or not 1<=output<=6:
            raise HTTPException(422,'图表或输出编号无效')
        manager=request.app.state.jobs
        operation,future=manager.operate(identity,'chart',chart=kind,case=case,output=output)
        try:
            await asyncio.wrap_future(future)
        except asyncio.CancelledError:
            raise HTTPException(409, '图表请求已失效，请使用最新计算快照') from None
        path,media_type=manager.file(operation)
        return FileResponse(path,media_type=media_type)

    @app.post('/api/jobs/{identity}/export',status_code=202)
    async def export(identity: str,body: ExportRequest,request: Request):
        operation,_=request.app.state.jobs.operate(identity,'export',format=body.format,mos_real_time=body.mos_real_time)
        return dict(id=operation,state='queued')

    @app.post('/api/jobs/{identity}/action', status_code=202)
    async def action(identity: str, body: ActionRequest, request: Request):
        from .actions import validate_options
        options = validate_options(body.action, body.options)
        operation, _ = request.app.state.jobs.operate(identity, 'action', action=body.action, options=options)
        return dict(id=operation, state='queued')

    @app.post('/api/operations/{identity}/cancel')
    async def cancel_action(identity: str, request: Request):
        row = request.app.state.jobs.cancel_operation(identity)
        if row.get('result'):
            row['result'] = {key: value for key, value in row['result'].items() if key != 'path'}
        return row

    @app.get('/api/operations/{identity}')
    async def operation(identity: str,request: Request):
        row=request.app.state.jobs.operation(identity)
        if row.get('result'):
            row['result']={key:value for key,value in row['result'].items() if key!='path'}
        return row

    @app.get('/api/files/{identity}')
    async def download(identity: str,request: Request,filename: str='电源设计报告'):
        path,media_type=request.app.state.jobs.file(identity)
        safe=re.sub(r'[<>:"/\\|?*\x00-\x1f]','_',filename)[:100].strip(' .') or '电源设计报告'
        return FileResponse(path,media_type=media_type,filename=safe+path.suffix)

    @app.post('/api/workspace/validate')
    async def workspace_validate(body: WorkspaceRequest):
        from system_workspace import normalize_project, checks
        from design_engine.contracts import json_value
        def validate():
            project = normalize_project(body.project)
            return json_value(dict(project=project, checks=checks(project)))
        return await asyncio.to_thread(validate)

    @app.get('/api/workspace/example')
    async def workspace_example():
        from system_workspace import load_project, checks
        from design_engine.contracts import json_value
        def load():
            p=load_project(Path(__file__).parent.parent/'examples/SYSTEM_AUX_ORING.json')
            return json_value(dict(project=p,checks=checks(p)))
        return await asyncio.to_thread(load)

    @app.post('/api/workspace/sync-input/{identity}')
    async def workspace_sync(identity: str, body: WorkspaceRequest):
        from system_workspace import normalize_project, sync_input, checks
        from design_engine.contracts import json_value
        def sync():
            p = normalize_project(body.project)
            sync_input(p, identity)
            return json_value(dict(project=p, checks=checks(p)))
        return await asyncio.to_thread(sync)

    @app.post('/api/pcs/reports',status_code=202)
    async def pcs_report(body: WorkspaceRequest,request: Request):
        from pcs_workspace import validate_project
        project=await asyncio.to_thread(validate_project,body.project)
        return request.app.state.jobs.submit(project,workspace=True)

    @app.post('/api/workspace/reports',status_code=202)
    async def system_report(body: WorkspaceRequest,request: Request):
        from system_workspace import normalize_project
        project=await asyncio.to_thread(normalize_project,body.project)
        return request.app.state.jobs.submit(project,workspace=True)

    @app.get('/api/pcs/reports/{identity}')
    async def pcs_report_download(identity: str,request: Request):
        path,media_type=request.app.state.jobs.file(identity)
        return FileResponse(path,media_type=media_type,filename='电源系统报告包.zip')

    if pcs_root:
        company = Path(pcs_root).resolve()
        if not (company/'index.html').is_file():
            raise ValueError('PCS 工作区未找到 index.html')
        app.mount('/pcs', StaticFiles(directory=company, html=True), name='pcs-workspace')
    pcs_assets = Path(__file__).parent/'pcs_static'
    if pcs_assets.is_dir():
        app.mount('/pcs-engine', StaticFiles(directory=pcs_assets), name='pcs-calculator-assets')
    static=Path(__file__).parent/'static'
    if (static/'index.html').is_file():
        app.mount('/',StaticFiles(directory=static,html=True),name='frontend')
    else:
        @app.get('/')
        async def not_built():
            return HTMLResponse('<h1>前端尚未构建</h1><p>请在 web_app/frontend 中运行 npm ci 和 npm run build。</p>',status_code=503)
    return app
