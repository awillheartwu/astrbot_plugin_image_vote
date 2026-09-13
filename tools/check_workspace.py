"""Exercise real workspace HTTP handlers with disposable SQLite, images and fake groups."""
import argparse
import io
import json
import time
import zipfile
from pathlib import Path

from fastapi.testclient import TestClient
from preview_workspace import build_host


def check(source):
    app=build_host(source)
    checked=[]
    with TestClient(app) as client:
        assert client.get('/extension/config').status_code==403
        client.get('/')
        def get(path, **query):
            r=client.get('/extension/'+path,params=query)
            assert r.status_code==200,(path,r.text)
            return r.json()['data']
        def post(path,body,code=200):
            r=client.post('/extension/'+path,json=body)
            assert r.status_code==code,(path,r.text)
            return r.json().get('data')
        original=get('config')
        assert client.post('/extension/config',json={},headers={'Origin':'https://foreign.invalid'}).status_code==403
        post('config',{'revision':'stale','values':{}},409)
        post('config',{'revision':original['revision'],'values':{'score_max':True}},400)
        checked.append('authorization, origin, optimistic config revision, JSON type validation')
        project=get('projects')[0]
        registered=post('projects/register',{'name':'验收项目','path':project['path'],'interval_seconds':20,'recursive':False})
        assert any(p['name']=='验收项目' for p in registered)
        preview=get('projects/preview',name='验收项目')
        assert preview['count']==3 and preview['interval_source']=='project'
        thumb=get('thumbnail',project='验收项目',index=1)
        assert thumb['image'].startswith('data:image/webp;base64,')
        assert get('browse')['roots']
        assert client.get('/extension/browse',params={'root':'/'}).status_code==403
        checked.append('registration, real image scan, thumbnail compression, directory bounds')
        groups=get('groups')
        assert len(groups)==2
        first=post('sessions/start',{'project':'验收项目','umo':groups[0]['umo']})['session_id']
        second=post('sessions/start',{'project':'验收项目','umo':groups[1]['umo']})['session_id']
        post('sessions/start',{'project':'验收项目','umo':groups[0]['umo']},400)
        post('sessions/start',{'project':'验收项目','umo':'forged'},403)
        def wait_for(predicate):
            deadline=time.monotonic()+12
            while time.monotonic()<deadline:
                if predicate():
                    return
                time.sleep(.03)
            raise AssertionError('bounded workspace operation timed out')
        wait_for(lambda: all(r['active_candidate'] for r in get('sessions',active='true')['sessions']))
        post('sessions/control',{'session_id':first,'action':'pause'})
        active=get('sessions',active='true')['sessions']
        assert {r['status'] for r in active}=={'RUNNING','PAUSED'}
        async def cast_vote():
            plugin=app.state.plugin
            session=await plugin.store.get_session(first)
            candidates=await plugin.store.list_candidates(first)
            active=next(c for c in candidates if c.id==session.active_candidate_id)
            return await plugin.application.record_vote(session,candidates,'5','fixture-user','验收参与者',active)
        assert client.portal.call(cast_vote) is not None
        post('sessions/control',{'session_id':first,'action':'resume'})
        post('sessions/control',{'session_id':first,'action':'finish','confirmed':True})
        post('sessions/control',{'session_id':second,'action':'stop','confirmed':True})
        wait_for(lambda: next(r for r in get('sessions')['sessions'] if r['id']==first)['report_state']=='ready')
        checked.append('two-group isolation, duplicate start, paused vote, resume, early finish, cancellation')
        response=client.get('/extension/reports/download',params={'session_id':first})
        assert response.status_code==200
        with zipfile.ZipFile(io.BytesIO(response.content)) as archive:
            names=archive.namelist()
            assert 'index.html' in names and any(p.startswith('images/') for p in names)
            payload=json.loads(archive.read('data.json'))
            assert payload['participants'][0]['name']=='验收参与者'
            assert payload['statistics']['total_valid_votes']==1
        assert '<script id="report-data"' in get('reports/preview',session_id=first)['html']
        checked.append('real report generation, streamed ZIP contents, embedded preview, participant projection')
        current=get('config')
        post('config',{'revision':current['revision'],'values':{'report_mode':'single_html','score_max':10,'report_include_participants':False}})
        post('reports/export',{'session_id':first})
        wait_for(lambda: next(r for r in get('sessions')['sessions'] if r['id']==first)['report_state']=='ready')
        response=client.get('/extension/reports/download',params={'session_id':first})
        assert response.status_code==200 and response.headers['content-type'].startswith('text/html')
        assert 'data:image/webp;base64,' in response.text
        assert '验收参与者' not in response.text
        assert '评分范围 1-5' in response.text
        saved=json.loads(Path(app.state.plugin._page_config_object.config_path).read_text())
        assert saved['voting']['score_max']==10
        checked.append('persistent config write, single HTML export, share privacy, historic score snapshot')
        post('reports/cleanup',{'session_id':first,'confirmed':True})
        assert next(r for r in get('sessions')['sessions'] if r['id']==first)['report_state']=='missing'
        assert len(list(Path(project['path']).glob('*.png')))==3
        post('reports/export',{'session_id':first})
        wait_for(lambda: next(r for r in get('sessions')['sessions'] if r['id']==first)['report_state']=='ready')
        checked.append('report-only cleanup, retained originals and votes, regeneration after cleanup')
    return {'passed':checked,'scope':'Official v4.27.5 PluginRequest/response source + real plugin services. Fake OneBot and no model calls.'}


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--astrbot-source',type=Path,required=True)
    args=parser.parse_args()
    print(json.dumps(check(args.astrbot_source),ensure_ascii=False,indent=2))
