import asyncio, copy, hashlib, json
from pathlib import Path
from importlib.metadata import version
from unittest.mock import patch
from fastapi import HTTPException, FastAPI
from fastapi.testclient import TestClient
from litellm.proxy import proxy_server
from sift.litellm_proxy import SiftLiteLLMHook, compact_proxy_request
root=Path(__file__).resolve().parents[3]
readme=(root/'README.md').read_text(encoding='utf-8')
block=next(b.split('```',1)[0] for b in readme.split('```python\n')[1:] if 'class PassThroughOn413Hook' in b.split('```',1)[0])
ns={};exec(compile(block,'README callback','exec'),ns)
class Counter:
 def _count_pre_call_check_tokens(self,messages,input,request_kwargs):return len(json.dumps(messages))//4
active={'model':'local','messages':[{'role':'user','content':'active '*1000}]}
cycle={'model':'local','messages':[{'role':'user','content':'inspect'},{'role':'assistant','content':None,'tool_calls':[{'id':'a','type':'function','function':{'name':'read','arguments':'{}'}}]},{'role':'tool','tool_call_id':'a','content':'result '*1000}]}
checks=[]
async def run():
 for name,data,phrase in [('single-active',active,'active turn and instructions exceed target'),('latest-cycle',cycle,'active task or latest tool cycle exceeds target')]:
  saved=copy.deepcopy(data)
  try:await SiftLiteLLMHook({'local':400}).async_pre_call_hook(None,None,data,'acompletion')
  except HTTPException as exc:
   assert exc.status_code==413 and exc.headers['x-sift-error-code']=='active_too_large'
   assert exc.detail=='Sift: '+phrase and exc.__cause__.code=='active_too_large'
  else:raise AssertionError('default must reject')
  result=await ns['PassThroughOn413Hook']({'local':400}).async_pre_call_hook(None,None,data,'acompletion')
  assert result is None and data==saved
  checks.append(name+': default rejects, README opt-in passes unchanged')
 for name,options,code in [('raw-limit',{'raw_limit':600},'raw_limit'),('input-size',{'max_input_characters':100},'input_size_limit')]:
  saved=copy.deepcopy(active)
  try:await ns['PassThroughOn413Hook']({'local':400},**options).async_pre_call_hook(None,None,active,'acompletion')
  except HTTPException as exc:assert exc.status_code==413 and exc.headers['x-sift-error-code']==code
  else:raise AssertionError('guard bypassed')
  assert active==saved;checks.append(name+': README callback preserves rejection')
 small={'model':'local','messages':[{'role':'user','content':'hello'}]}
 result=await ns['PassThroughOn413Hook']({'local':400}).async_pre_call_hook(None,None,small,'acompletion')
 assert result['messages']==small['messages'] and not result['metadata']['sift']['compacted']
 checks.append('under-target: no-op preserved')
with patch.object(proxy_server,'llm_router',Counter()):asyncio.run(run())
app=FastAPI()
@app.post('/compact')
def endpoint(data:dict):return compact_proxy_request(Counter(),data,call_type='acompletion',target=400)
with TestClient(app) as client:
 response=client.post('/compact',json=cycle)
 assert response.status_code==413 and response.headers['x-sift-error-code']=='active_too_large'
 assert response.json()['detail']=='Sift: active task or latest tool cycle exceeds target'
checks.append('FastAPI: latest-cycle code and unchanged error detail serialize')
print(json.dumps({'result':'PASS','litellm':version('litellm'),'checks':checks,'sha256':{p:hashlib.sha256((root/p).read_bytes()).hexdigest() for p in ['src/sift/litellm_proxy.py','tests/test_litellm_proxy.py','README.md','docs/evals/issue-59/verify_callback.py']}},indent=2))
