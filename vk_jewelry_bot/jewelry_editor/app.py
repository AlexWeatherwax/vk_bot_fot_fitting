import asyncio, base64, binascii, hashlib, io, json, logging, math, os, secrets, threading, time, unicodedata, uuid, fcntl, tempfile
from contextlib import ExitStack
from dataclasses import fields as dataclass_fields
from pathlib import Path
from typing import Literal
from unittest.mock import patch
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, JSONResponse
from starlette.concurrency import run_in_threadpool
from pydantic import BaseModel, ConfigDict, Field
from PIL import Image, ImageOps
from bot.jewelry.catalog import GALLERY_DIR
from bot.jewelry.models import Category, JewelryItem, CATEGORY_TITLES
from bot.tryon import pipeline

HERE=Path(__file__).resolve().parent
GALLERY=Path(GALLERY_DIR).resolve()
MANIFEST=GALLERY/'manifest.json'
USER=os.getenv('EDITOR_USER','author')
PASSWORD=os.getenv('EDITOR_PASSWORD','')
if len(PASSWORD)<16:
    raise RuntimeError('Задайте EDITOR_PASSWORD длиной не менее 16 символов')
STAGING=GALLERY/'.editor-staging'
STAGING.mkdir(exist_ok=True)
# Только один процесс редактора; черновики предыдущего запуска недействительны.
for old in STAGING.glob('*'):
    if old.is_file() and old.suffix in {'.png','.jpg'}: old.unlink()
ASSETS={}
ASSET_LOCK=threading.Lock()
RENDER_LOCK=threading.Lock()
QUEUE=asyncio.Semaphore(1)
TTL=3600
MAX_BYTES=12*1024*1024
Image.MAX_IMAGE_PIXELS=12000000
app=FastAPI(docs_url=None,redoc_url=None,openapi_url=None)

@app.middleware('http')
async def security(request,call_next):
    ok=False
    try:
        scheme,value=request.headers.get('authorization','').split(' ',1)
        user,password=base64.b64decode(value,validate=True).decode().split(':',1)
        ok=scheme.lower()=='basic' and secrets.compare_digest(user.encode(),USER.encode()) and secrets.compare_digest(password.encode(),PASSWORD.encode())
    except (ValueError,UnicodeError,binascii.Error): pass
    if not ok:
        return JSONResponse({'detail':'Требуется вход'},401,headers={'WWW-Authenticate':'Basic realm="Jewelry editor", charset="UTF-8"'})
    if request.method not in {'GET','HEAD'}:
        if request.headers.get('x-editor-request')!='1' or request.headers.get('sec-fetch-site')=='cross-site':
            return JSONResponse({'detail':'Недопустимый источник запроса'},403)
        length=request.headers.get('content-length')
        if length and (not length.isdecimal() or int(length)>MAX_BYTES):
            return JSONResponse({'detail':'Максимум 12 МБ'},413)
    response=await call_next(request)
    response.headers.update({'Cache-Control':'no-store','X-Content-Type-Options':'nosniff','X-Frame-Options':'DENY','Referrer-Policy':'no-referrer','Content-Security-Policy':"default-src 'self'; img-src 'self' data:; style-src 'self'; script-src 'self'; frame-ancestors 'none'; base-uri 'none'; form-action 'self'"})
    return response

def normalize(s):
    return ' '.join(unicodedata.normalize('NFKC',s).split()).casefold()

def read_catalog():
    raw=MANIFEST.read_bytes()
    entries=json.loads(raw)
    if not isinstance(entries,list): raise ValueError('manifest должен содержать массив')
    return entries,hashlib.sha256(raw).hexdigest()

def image_path(entry):
    path=(GALLERY/entry['image']).resolve()
    if not path.is_relative_to(GALLERY) or not path.is_file(): raise ValueError('Неверный путь изображения')
    return path

async def body(request,limit=MAX_BYTES):
    raw=bytearray()
    async for chunk in request.stream():
        raw.extend(chunk)
        if len(raw)>limit: raise HTTPException(413,'Слишком большой запрос')
    return bytes(raw)

async def json_body(request):
    try: return json.loads(await body(request,65536))
    except (ValueError,UnicodeError): raise HTTPException(400,'Некорректный JSON')

def prepare(raw,jewelry=False,crop=False):
    try:
        with Image.open(io.BytesIO(raw)) as source:
            if source.format not in {'PNG','JPEG','WEBP'}: raise ValueError('Разрешены PNG, JPEG, WebP')
            if source.width*source.height>12000000: raise ValueError('Максимум 12 мегапикселей')
            im=ImageOps.exif_transpose(source)
            if jewelry:
                im=im.convert('RGBA')
                alpha=im.getchannel('A'); lo,hi=alpha.getextrema()
                if lo==255 or hi<160: raise ValueError('Нужно изображение с прозрачным фоном и видимым украшением')
                bbox=alpha.point(lambda x:255 if x>=160 else 0).getbbox()
                if not bbox: raise ValueError('Пустое изображение')
                if crop: im=im.crop(bbox)
                if max(im.size)>4096: raise ValueError('Сторона украшения не больше 4096 пикселей')
            else:
                im=im.convert('RGB'); im.thumbnail((1800,1800),Image.Resampling.LANCZOS)
            out=io.BytesIO()
            im.save(out,format='PNG' if jewelry else 'JPEG',**({} if jewelry else {'quality':94}))
            return out.getvalue()
    except (OSError,Image.DecompressionBombError) as exc:
        raise ValueError('Не удалось прочитать изображение или оно слишком велико') from exc

def put_asset(raw,kind):
    with ASSET_LOCK:
        now=time.monotonic()
        for key,(path,k,t) in list(ASSETS.items()):
            if now-t>TTL:
                path.unlink(missing_ok=True); del ASSETS[key]
        if len(ASSETS)>=80: raise ValueError('Лимит черновиков. Подождите 1 час или перезапустите редактор.')
        token=secrets.token_urlsafe(24)
        path=STAGING/(uuid.uuid4().hex+('.png' if kind=='jewelry' else '.jpg'))
        path.write_bytes(raw); ASSETS[token]=(path,kind,now)
        return token

def asset(token,kind):
    with ASSET_LOCK:
        a=ASSETS.get(token)
        if not a or a[1]!=kind or time.monotonic()-a[2]>TTL:
            raise ValueError('Черновик истёк. Загрузите картинку снова (срок хранения 1 час).')
        ASSETS[token]=(a[0],kind,time.monotonic())
        return a[0],a[0].read_bytes()

class Settings(BaseModel):
    model_config=ConfigDict(extra='forbid',allow_inf_nan=False)
    name:str=Field(min_length=1,max_length=160)
    category:Category
    anchor_scale:float=Field(default=1,ge=.05,le=5)
    offset_x:float=Field(default=0,ge=-3,le=3)
    offset_y:float=Field(default=0,ge=-3,le=3)
    rotation_offset:float=Field(default=0,ge=-180,le=180)
    pair_image:bool=False
    single_ear:bool=False
    brooch_side:Literal['left','right']='left'
    chain_color:Literal['silver','gold','none']='silver'
    kaffy_side:Literal['left','right']='left'
    kaffy_anchor_y:float=Field(default=.8,ge=0,le=1)
    hairpin_style:Literal['updo','side']='updo'
    hairpin_side:Literal['left','right']='left'

class Payload(BaseModel):
    model_config=ConfigDict(extra='forbid')
    settings:Settings
    asset:str
    photo:str|None=None
    revision:str=''
    editing_id:str|None=None
    replace:bool=False

def parse(raw):
    try: p=Payload.model_validate(raw)
    except ValueError: raise HTTPException(422,'Проверьте поля: масштаб .05–5, смещения −3…3, угол −180…180, название до 160 символов.')
    p.settings.name=' '.join(p.settings.name.split())
    if not p.settings.name: raise HTTPException(422,'Введите название')
    if p.settings.pair_image and p.settings.single_ear: raise HTTPException(422,'Пара и моно-серьга несовместимы')
    return p

def render(p):
    path,_=asset(p.asset,'jewelry')
    photo=asset(p.photo,'photo')[1] if p.photo else prepare((HERE/'examples/model.jpg').read_bytes())
    settings=p.settings.model_dump(mode='json')
    kwargs={k:v for k,v in settings.items() if k in JewelryItem.__dataclass_fields__}
    kwargs.update(id='preview',image=str(path),category=Category(settings['category']))
    item=JewelryItem(**kwargs)
    detected={}; captures=[]
    # monkeypatch допустим только в отдельном процессе редактора, не ВК-бота.
    with RENDER_LOCK,ExitStack() as stack:
        for module,func in [(pipeline.face_mod,'get_face_anchors'),(pipeline.hand_mod,'get_ring_anchor'),(pipeline.hand_mod,'get_wrist_anchor'),(pipeline.pose_mod,'get_neck_anchor')]:
            original=getattr(module,func)
            def cached(img,original=original,key=func):
                if key not in detected: detected[key]=original(img)
                return detected[key]
            stack.enter_context(patch.object(module,func,cached))
        original=pipeline.overlay_image
        def trace(base,overlay,anchor_xy,target_width,rotation_deg=0,overlay_anchor=(.5,.5)):
            h=target_width*overlay.height/max(1,overlay.width)
            if not math.isfinite(target_width+h) or target_width<0 or target_width+h>10000 or (target_width+h)**2/2>18000000:
                raise ValueError('Слишком большой размер украшения. Уменьшите масштаб или обрежьте прозрачные поля.')
            captures.append(dict(x=float(anchor_xy[0]),y=float(anchor_xy[1])))
            return original(base,overlay,anchor_xy,target_width,rotation_deg,overlay_anchor)
        stack.enter_context(patch.object(pipeline,'overlay_image',trace))
        result=pipeline.apply_tryon(item,path,photo)
        if len(pipeline._PAIR_CACHE)>64: pipeline._PAIR_CACHE.clear()
    cat=item.category.value
    if cat in {'earrings','kaffy','diadem','hairpin'}: unit=detected['get_face_anchors'].face_width
    elif cat=='ring': unit=detected['get_ring_anchor'].finger_width
    elif cat=='bracelet': unit=detected['get_wrist_anchor'].wrist_width
    else: unit=detected['get_neck_anchor'].shoulder_width
    if not math.isfinite(unit) or unit<1: raise ValueError('Не удалось определить надёжный масштаб тела')
    handles=captures[-1:] if cat=='pendant' else captures
    for i,h in enumerate(handles):
        sign=1
        if cat=='earrings': sign=(-1 if i==0 else 1) if len(handles)==2 else (1 if item.pair_image else -1)
        elif cat=='kaffy': sign=1 if item.kaffy_side=='right' else -1
        elif cat=='hairpin' and item.hairpin_style=='side': sign=1 if item.hairpin_side=='right' else -1
        h['sign']=sign
    with Image.open(io.BytesIO(result)) as im: width,height=im.size
    return dict(image='data:image/jpeg;base64,'+base64.b64encode(result).decode(),width=width,height=height,unit=float(unit),handles=handles)

async def run_preview(p):
    try: await asyncio.wait_for(QUEUE.acquire(),timeout=3)
    except asyncio.TimeoutError: raise HTTPException(429,'Предпросмотр занят. Повторите через несколько секунд.')
    try: return await run_in_threadpool(render,p)
    except (ValueError,pipeline.TryOnError) as e: raise HTTPException(422,str(e))
    except Exception:
        logging.exception('Ошибка предпросмотра')
        raise HTTPException(500,'Ошибка примерки. Проверьте журнал сервера и файлы моделей MediaPipe.')
    finally: QUEUE.release()

def save(p,raw):
    with (GALLERY/'.editor.lock').open('a+b') as lock:
        fcntl.flock(lock,fcntl.LOCK_EX)
        entries,current=read_catalog()
        if current!=p.revision: raise HTTPException(409,'Каталог изменился. Обновите список, проверьте данные и повторите сохранение.')
        settings=p.settings.model_dump(mode='json')
        matches=[e for e in entries if normalize(e['name'])==normalize(settings['name'])]
        if len(matches)>1: raise HTTPException(409,'Несколько записей с одинаковым названием. Устраните дубликаты вручную.')
        target=matches[0] if matches else None
        if p.editing_id:
            selected=[e for e in entries if e['id']==p.editing_id]
            if len(selected)!=1: raise HTTPException(409,'Редактируемая запись не найдена или id неоднозначен')
            if target and target['id']!=p.editing_id: raise HTTPException(409,'Название принадлежит другой записи. Откройте её отдельно.')
            target=selected[0]
        if target is not None and not p.replace: raise HTTPException(409,'Подтвердите обновление существующего украшения галочкой')
        entry=dict(target or {}); entry.update(settings)
        entry['id']=target['id'] if target else uuid.uuid4().hex
        folder=GALLERY/'custom'; folder.mkdir(exist_ok=True)
        image=folder/(uuid.uuid4().hex+'.png'); entry['image']=image.relative_to(GALLERY).as_posix()
        with image.open('xb') as f:
            f.write(raw); f.flush(); os.fsync(f.fileno())
        updated=[entry if e is target else e for e in entries] if target else entries+[entry]
        data=(json.dumps(updated,ensure_ascii=False,indent=2)+'\n').encode()
        temp=None; committed=False
        try:
            backups=GALLERY/'.editor-backups'; backups.mkdir(exist_ok=True)
            backup=backups/(current+'.json')
            if not backup.exists(): backup.write_bytes(MANIFEST.read_bytes())
            fd,temp=tempfile.mkstemp(prefix='.manifest-',dir=GALLERY)
            with os.fdopen(fd,'wb') as f:
                f.write(data); f.flush(); os.fsync(f.fileno())
            os.chmod(temp,MANIFEST.stat().st_mode&0o777)
            os.replace(temp,MANIFEST); committed=True
            fd=os.open(GALLERY,os.O_RDONLY)
            try: os.fsync(fd)
            finally: os.close(fd)
        finally:
            if temp and os.path.exists(temp): os.unlink(temp)
            if not committed: image.unlink(missing_ok=True)
        return dict(entry=entry,revision=hashlib.sha256(data).hexdigest(),updated=target is not None)

@app.get('/')
def index(): return FileResponse(HERE/'static/index.html')
@app.get('/static/{name}')
def static(name:str):
    if name not in {'app.js','style.css'}: raise HTTPException(404)
    return FileResponse(HERE/'static'/name)
@app.get('/api/catalog')
def catalog():
    entries,revision=read_catalog()
    return dict(entries=entries,revision=revision,categories=[dict(value=c.value,title=CATEGORY_TITLES[c]) for c in Category])
@app.get('/api/check')
def check(name:str=''):
    entries,_=read_catalog()
    return dict(matches=[dict(id=e['id'],name=e['name'],category=e['category']) for e in entries if normalize(e['name'])==normalize(name)])
@app.post('/api/upload/{kind}')
async def upload(kind:str,request:Request,crop:bool=False):
    if kind not in {'photo','jewelry'}: raise HTTPException(404)
    raw=await body(request)
    try:
        prepared=await run_in_threadpool(prepare,raw,kind=='jewelry',crop)
        return dict(token=await run_in_threadpool(put_asset,prepared,kind))
    except ValueError as e: raise HTTPException(422,str(e))
@app.post('/api/load/{item_id}')
def load(item_id:str):
    entries,revision=read_catalog(); matches=[e for e in entries if e['id']==item_id]
    if len(matches)!=1: raise HTTPException(404,'Запись не найдена или id неоднозначен')
    try:
        raw=prepare(image_path(matches[0]).read_bytes(),True)
        return dict(entry=matches[0],asset=put_asset(raw,'jewelry'),revision=revision)
    except ValueError as e: raise HTTPException(422,str(e))
@app.post('/api/preview')
async def preview_endpoint(request:Request): return await run_preview(parse(await json_body(request)))
@app.post('/api/save')
async def save_endpoint(request:Request):
    p=parse(await json_body(request)); await run_preview(p)
    try: _,raw=asset(p.asset,'jewelry')
    except ValueError as e: raise HTTPException(422,str(e))
    return await run_in_threadpool(save,p,raw)
