"""Bound API bodies before parsing; Content-Type is never a size bypass."""
from starlette.responses import JSONResponse


class JsonRequestLimit:
    def __init__(self,app,limit=512*1024,upload_limit=21*1024*1024):
        self.app,self.limit,self.upload_limit=app,limit,upload_limit

    async def __call__(self,scope,receive,send):
        if (scope['type']!='http' or scope.get('method') not in ('POST','PUT','PATCH','DELETE')
                or not scope.get('path','').startswith('/api/')):
            return await self.app(scope,receive,send)
        # FastAPI parses multipart before invoking the upload route. Bound the
        # whole request here as well as its individual file inside the route.
        limit=self.upload_limit if scope.get('path')=='/api/files' else self.limit
        lengths=[value for key,value in scope.get('headers',[]) if key.lower()==b'content-length']
        if lengths:
            try:
                if len(set(lengths))!=1 or not lengths[0].isdigit():raise ValueError()
                declared=int(lengths[0])
            except ValueError:
                return await JSONResponse({'detail':'請求長度格式錯誤'},400)(scope,receive,send)
            if declared>limit:
                return await JSONResponse({'detail':'請求內容過大，請縮減文字或分批提交'},413)(scope,receive,send)
        chunks=[];size=0
        while True:
            message=await receive()
            if message['type']=='http.disconnect':return
            size+=len(message.get('body',b''))
            if size>limit:
                return await JSONResponse({'detail':'請求內容過大，請縮減文字或分批提交'},413)(scope,receive,send)
            chunks.append(message.get('body',b''))
            if not message.get('more_body',False):break
        body=b''.join(chunks);sent=False
        async def replay():
            nonlocal sent
            if not sent:
                sent=True
                return {'type':'http.request','body':body,'more_body':False}
            return await receive()
        await self.app(scope,replay,send)
