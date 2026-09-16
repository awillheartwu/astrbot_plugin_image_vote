"""Isolated local workspace acceptance host using the official AstrBot web/bridge sources.

Requires FastAPI, uvicorn, Pillow, and --astrbot-source pointing at a v4.27.5 checkout.
The host uses real plugin services and SQLite; group sending and model calls are isolated fakes.
No production configuration, messages, or databases are accessed.
"""
import argparse
import asyncio
import importlib.util
import json
import secrets
import sys
import tempfile
from contextlib import asynccontextmanager
from pathlib import Path
from types import SimpleNamespace

import uvicorn
from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse, FileResponse, JSONResponse

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))
from src.application import VoteApplication
from src.config import VoteConfig
from src.image_processor import PillowImageProcessor
from src.persistence import SQLiteStore
from src.project_registry import ProjectRegistry
from src.project_service import ProjectService
from src.report_generator import DirectoryReportGenerator
from src.session_manager import SessionManager
from src.vote_collector import VoteRouter
from src.workspace_api import WorkspaceAPI


def build_host(astrbot_source):
    spec = importlib.util.spec_from_file_location('official_astrbot_web', Path(astrbot_source)/'astrbot/api/web.py')
    web = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(web)
    state = tempfile.TemporaryDirectory(prefix='lirating-workspace-acceptance-')
    root = Path(state.name)
    project = root/'projects'/'海滨之家'
    project.mkdir(parents=True)
    from tools.sample_project import create_sample_project
    create_sample_project(project)
    token = secrets.token_hex(24)

    class Config(dict):
        config_path = str(root/'plugin-config.json')
        def save_config(self, values):
            self.update(values)
            Path(self.config_path).write_text(json.dumps(self, ensure_ascii=False))

    config = Config({'paths':{'input_root':str(root/'projects'),'output_root':str(root/'reports')},
                     'voting':{'default_interval_seconds':20,'score_max':5},
                     'ai':{'ai_summary_enabled':False},'report':{'report_include_avatars':False}})
    config.save_config({})
    class Context:
        registered_web_apis=[]
        def get_config(self):
            return {'dashboard':{'username':'local-qa'}}
        def register_web_api(self,path,handler,methods,description):
            self.registered_web_apis[:]=[r for r in self.registered_web_apis if (r[0],r[2])!=(path,methods)]
            self.registered_web_apis.append((path,handler,methods,description))
        def get_all_providers(self):
            return []
    async def group_action(action):
        if action != 'get_group_list':
            raise RuntimeError('Unexpected external action')
        return [{'group_id':101,'group_name':'本地验收群 A'},{'group_id':102,'group_name':'本地验收群 B'}]
    platform=SimpleNamespace(meta=lambda:SimpleNamespace(name='aiocqhttp',id='isolated-onebot'),
                             get_client=lambda:SimpleNamespace(call_action=group_action))
    context=Context()
    context.platform_manager=SimpleNamespace(get_insts=lambda:[platform])
    store=SQLiteStore(root/'state.db')
    manager=SessionManager()
    plugin=SimpleNamespace(context=context,store=store,session_manager=manager,_page_config_object=config,
                           project_registry=ProjectRegistry(root/'projects.json'))
    sent=[]
    async def sender(session,candidate,path):
        sent.append((session.id,candidate.id))
    def apply(raw,source=None):
        plugin.settings=VoteConfig.from_mapping(raw)
        plugin.project_service=ProjectService(Path(plugin.settings.input_root),registry=plugin.project_registry)
        plugin.application=VoteApplication(plugin.settings,plugin.project_service,store,manager,VoteRouter(),
                            sender=sender,report_generator=DirectoryReportGenerator(),image_processor=PillowImageProcessor())
    plugin._apply_config=apply
    plugin._ensure_config=lambda:apply(config) if dict(config)!=getattr(plugin,'last_config',{}) else None
    # Keep service objects stable until a config actually changes.
    def ensure():
        raw=json.loads(Path(config.config_path).read_text())
        if raw!=getattr(plugin,'last_config',None):
            apply(raw)
            plugin.last_config=raw
    plugin._ensure_config=ensure
    ensure()
    api=WorkspaceAPI(plugin,web=web)

    @asynccontextmanager
    async def lifespan(app):
        await store.initialize()
        api.register()
        api.ready=True
        yield
        await api.close()
        await manager.shutdown()
        await store.close()
        state.cleanup()
    app=FastAPI(lifespan=lifespan)
    app.state.plugin=plugin
    app.state.workspace=api
    app.state.fixture_root=root
    app.state.sent=sent

    @app.get('/')
    async def home():
        response=HTMLResponse(HOST)
        response.set_cookie('local_qa',token,httponly=True,samesite='strict')
        return response

    @app.get('/page/{filename}')
    async def page(filename):
        if filename not in {'index.html','style.css','app.js','bridge.js'}:
            return JSONResponse({},404)
        if filename=='bridge.js':
            return FileResponse(Path(astrbot_source)/'astrbot/dashboard/plugin_page_bridge.js',media_type='text/javascript')
        file=REPO/'pages/image-vote'/filename
        if filename=='index.html':
            text=file.read_text().replace('<script src="app.js" defer>',
                '<script src="bridge.js"></script><script>window.AstrBotPluginPage.__setInitialContext({isDark:false,pluginName:"astrbot_plugin_image_vote"});</script><script src="app.js" defer>')
            return HTMLResponse(text)
        return FileResponse(file)

    @app.api_route('/extension/{endpoint:path}',methods=['GET','POST'])
    async def extension(endpoint,request:Request):
        if request.cookies.get('local_qa')!=token:
            return JSONResponse({'status':'error','message':'Local acceptance login required'},403)
        if request.headers.get('origin') not in {None,str(request.base_url).rstrip('/')}:
            return JSONResponse({},403)
        route='/astrbot_plugin_image_vote/'+endpoint
        handler=next((r[1] for r in context.registered_web_apis if r[0]==route and request.method in r[2]),None)
        if handler is None:
            return JSONResponse({},404)
        with web.bind_request_context(web.PluginRequest(request,plugin_name='astrbot_plugin_image_vote',username='local-qa')):
            return await handler()
    return app


HOST='''<!doctype html><html lang="zh-CN"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>图片投票 · 本地隔离验收</title></head><body style="margin:0;font:13px system-ui"><div style="height:38px;padding:8px 16px;box-sizing:border-box;background:#eeeaf8;color:#544e68">本地隔离验收 · 真正的插件服务与 SQLite · 不连接 QQ 或真实模型</div><iframe title="图片投票工作区" src="/page/index.html" style="border:0;width:100%;height:calc(100vh - 42px)"></iframe><script>
const frame=document.querySelector('iframe');
addEventListener('message',async event=>{
 const m=event.data;if(event.source!==frame.contentWindow||m?.channel!=='astrbot-plugin-page'||m.kind!=='request')return;
 try{
  if(!/^[a-z/]+$/.test(m.endpoint||''))throw Error('Unsupported endpoint');
  const u=new URL('/extension/'+m.endpoint,location.origin);Object.entries(m.params||{}).forEach(([k,v])=>{if(v!==undefined&&v!==null)u.searchParams.set(k,v)});
  const r=await fetch(u,{method:m.action==='api:post'?'POST':'GET',headers:{'Content-Type':'application/json'},body:m.action==='api:post'?JSON.stringify(m.body||{}):undefined});
  let value;
  if(m.action==='files:download'&&r.ok){const url=URL.createObjectURL(await r.blob()),a=document.createElement('a');a.href=url;a.download=m.filename||(r.headers.get('content-type').includes('zip')?'report.zip':'report.html');a.click();setTimeout(()=>URL.revokeObjectURL(url),5000);value={downloaded:true};}
  else{value=await r.json();if(!r.ok||value.status==='error')throw Error(value.message||'Request failed');value=value.data??value;}
  frame.contentWindow.postMessage({channel:m.channel,kind:'response',requestId:m.requestId,ok:true,data:value},location.origin);
 }catch(e){frame.contentWindow.postMessage({channel:m.channel,kind:'response',requestId:m.requestId,ok:false,error:e.message},location.origin);}
});</script></body></html>'''

if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--astrbot-source',type=Path,required=True)
    parser.add_argument('--port',type=int,default=8769)
    args=parser.parse_args()
    uvicorn.run(build_host(args.astrbot_source),host='127.0.0.1',port=args.port)
