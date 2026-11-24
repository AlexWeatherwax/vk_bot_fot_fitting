import asyncio, base64, binascii, hashlib, io, json, logging, math, os, secrets, threading, time, unicodedata, uuid, fcntl, tempfile
from contextlib import ExitStack
from dataclasses import fields as dataclass_fields
from pathlib import Path
from typing import Literal
from unittest.mock import patch
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, JSONResponse, Response
from starlette.concurrency import run_in_threadpool
from pydantic import BaseModel, ConfigDict, Field, field_validator
from PIL import Image, ImageOps
from bot.jewelry.catalog import GALLERY_DIR
from bot.jewelry.models import Category, JewelryItem, CATEGORY_TITLES, item_from_dict
from bot.jewelry.selection import validate_selection
from bot.tryon.errors import TryOnError

# Catalogue operations and the admin shell do not initialize native models.
# The editor is a separate one-worker process; rendering loads them on demand.
pipeline = None


def get_pipeline():
    global pipeline
    if pipeline is None:
        from bot.tryon import pipeline as native_pipeline
        pipeline = native_pipeline
    return pipeline

HERE=Path(__file__).resolve().parent
GALLERY=Path(os.getenv('EDITOR_GALLERY',str(GALLERY_DIR))).expanduser().resolve()
MANIFEST=GALLERY/'manifest.json'
USER=os.getenv('EDITOR_USER','author')
PASSWORD=os.getenv('EDITOR_PASSWORD','')
if len(PASSWORD)<16:
    raise RuntimeError('Задайте EDITOR_PASSWORD длиной не менее 16 символов')
STAGING=GALLERY/'.editor-staging'
STAGING.mkdir(parents=True,exist_ok=True)
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
        return JSONResponse({'detail':'Требуется вход'},401,headers={'WWW-Authenticate':'Basic realm="Jewelry editor", charset="UTF-8"','X-Imladris-Editor':'1','Cache-Control':'no-store'})
    if request.method not in {'GET','HEAD'}:
        if request.headers.get('x-editor-request')!='1' or request.headers.get('sec-fetch-site')=='cross-site':
            return JSONResponse({'detail':'Недопустимый источник запроса'},403)
        length=request.headers.get('content-length')
        if length and (not length.isdecimal() or int(length)>MAX_BYTES):
            return JSONResponse({'detail':'Максимум 12 МБ'},413)
    response=await call_next(request)
    response.headers.update({'X-Imladris-Editor':'1','Cache-Control':'no-store','X-Content-Type-Options':'nosniff','X-Frame-Options':'DENY','Referrer-Policy':'no-referrer','Content-Security-Policy':"default-src 'self'; img-src 'self' data:; style-src 'self'; script-src 'self'; frame-ancestors 'none'; base-uri 'none'; form-action 'self'"})
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

def prepare(raw,jewelry=False,crop=False,require_transparency=True):
    try:
        with Image.open(io.BytesIO(raw)) as source:
            if source.format not in {'PNG','JPEG','WEBP'}: raise ValueError('Разрешены PNG, JPEG, WebP')
            if source.width*source.height>12000000: raise ValueError('Максимум 12 мегапикселей')
            im=ImageOps.exif_transpose(source)
            if jewelry:
                im=im.convert('RGBA')
                alpha=im.getchannel('A'); lo,hi=alpha.getextrema()
                if hi<160 or (require_transparency and lo==255): raise ValueError('Нужно изображение с прозрачным фоном и видимым украшением')
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
        if not a or (kind is not None and a[1]!=kind) or time.monotonic()-a[2]>TTL:
            raise ValueError('Черновик истёк. Загрузите картинку снова (срок хранения 1 час).')
        ASSETS[token]=(a[0],a[1],time.monotonic())
        return a[0],a[0].read_bytes()

class Settings(BaseModel):
    model_config=ConfigDict(extra='forbid',allow_inf_nan=False)
    name:str=Field(min_length=1,max_length=160)
    category:Category
    anchor_scale:float=Field(default=1,ge=.05,le=5)
    offset_x:float=Field(default=0,ge=-3,le=3)
    offset_y:float=Field(default=0,ge=-3,le=3)
    rotation_offset:float=Field(default=0,ge=-180,le=180)
    overlay_anchor:tuple[float,float]|None=None
    pair_image:bool=False
    pair_overlay_anchors:tuple[tuple[float,float],tuple[float,float]]|None=None
    single_ear:bool=False
    brooch_side:Literal['left','right']='left'
    chain_color:Literal['silver','gold','none','front_v3_silver','front_v3_copper',
                        'curated_silver','curated_gold','curated_brass',
                        'curated_copper','curated_dark_silver']='silver'
    kaffy_side:Literal['left','right']='left'
    kaffy_anchor_y:float=Field(default=.8,ge=0,le=1)
    hairpin_style:Literal['updo','side','bun']='updo'
    hairpin_side:Literal['left','right']='left'
    hairpin_head_fraction:float|None=Field(default=None,gt=0,lt=1)

    @field_validator('overlay_anchor')
    @classmethod
    def normalized_anchor(cls,value):
        if value is not None and any(not 0<=v<=1 for v in value):
            raise ValueError('Точка крепления должна быть в пределах PNG')
        return value

class Payload(BaseModel):
    model_config=ConfigDict(extra='forbid')
    settings:Settings
    asset:str
    photo:str|None=None
    revision:str=''
    editing_id:str|None=None
    component_id:str|None=None
    replace:bool=False

def parse(raw):
    try: p=Payload.model_validate(raw)
    except ValueError: raise HTTPException(422,'Проверьте поля: масштаб .05–5, смещения −3…3, угол −180…180, название до 160 символов.')
    p.settings.name=' '.join(p.settings.name.split())
    if not p.settings.name: raise HTTPException(422,'Введите название')
    if p.settings.category==Category.SET: raise HTTPException(422,'В этом редакторе настраиваются отдельные украшения. Набор состоит из нескольких изделий.')
    if p.settings.pair_image and p.settings.single_ear: raise HTTPException(422,'Пара и моно-серьга несовместимы')
    try: item_from_dict(dict(p.settings.model_dump(mode='json'),id='preview',image='preview.png'))
    except ValueError as exc: raise HTTPException(422,str(exc))
    return p

def data_image(image, image_format='PNG'):
    out=io.BytesIO()
    image.save(out,format=image_format,**({'quality':94} if image_format=='JPEG' else {}))
    mime='image/jpeg' if image_format=='JPEG' else 'image/png'
    return 'data:'+mime+';base64,'+base64.b64encode(out.getvalue()).decode()


def available_references():
    root=HERE.parent/'фото для калибровки'
    specs=[
        ('front','В фас — лицо, шея и плечи',root/'анфас-v3/reference-front.jpg',
         ['earrings','pendant','beads','diadem','hairpin','brooch']),
        ('ear','Ухо — три четверти',root/'1000013935_profil_ukho_kaffy.jpg',['kaffy']),
        ('hand','Кисть — кольца',root/'1000013933.jpg',['ring']),
        ('wrist','Кисть и запястье',root/'1000013934.jpg',['bracelet']),
        ('bun','Причёска с пучком',root/'заколки/reference-updo.png',['hairpin']),
    ]
    refs={key:dict(id=key,title=title,path=path,categories=categories)
          for key,title,path,categories in specs if path.is_file()}
    if not refs and (HERE/'examples/model.jpg').is_file():
        refs['example']=dict(id='example',title='Пример фотографии',
                             path=HERE/'examples/model.jpg',
                             categories=[c.value for c in Category if c!=Category.SET])
    return refs


def reference_bytes(reference_id):
    reference=available_references().get(reference_id)
    if reference is None:
        raise HTTPException(404,'Фотография-референс не найдена')
    return prepare(reference['path'].read_bytes())


def default_reference(item):
    refs=available_references()
    requested=('bun' if item.category==Category.HAIRPIN and item.hairpin_style=='bun'
               else {'kaffy':'ear','ring':'hand','bracelet':'wrist'}.get(item.category.value,'front'))
    if requested in refs:
        return reference_bytes(requested)
    matching=next((ref for ref in refs.values() if item.category.value in ref['categories']),None)
    if matching:
        return reference_bytes(matching['id'])
    raise ValueError('Загрузите подходящую фотографию-референс для этой категории.')


def render(p):
    native=get_pipeline()
    path,_=asset(p.asset,'jewelry')
    settings=p.settings.model_dump(mode='json')
    kwargs={k:v for k,v in settings.items() if k in JewelryItem.__dataclass_fields__}
    kwargs.update(id='preview',image=str(path),category=Category(settings['category']))
    item=JewelryItem(**kwargs)
    photo=asset(p.photo,'photo')[1] if p.photo else default_reference(item)
    with Image.open(io.BytesIO(photo)) as source:
        background=ImageOps.exif_transpose(source).convert('RGB')
    detected={}; captures=[]; visible_ears={}
    # Trace the actual renderer; no separate geometry formulas for catalogue
    # calibration. Raw layers let the browser move the jewellery immediately.
    with RENDER_LOCK,ExitStack() as stack:
        for module,func in [(native.face_mod,'get_face_anchors'),
                            (native.hand_mod,'get_ring_anchor'),
                            (native.hand_mod,'get_wrist_anchor'),
                            (native.pose_mod,'get_neck_anchor')]:
            original=getattr(module,func)
            def cached(img,*args,original=original,key=func,**kwargs):
                if key not in detected: detected[key]=original(img,*args,**kwargs)
                return detected[key]
            stack.enter_context(patch.object(module,func,cached))
        if hasattr(native,'earring_points'):
            original_points=native.earring_points
            def capture_points(*args,**kwargs):
                points=original_points(*args,**kwargs)
                visible_ears.update(points or {})
                return points
            stack.enter_context(patch.object(native,'earring_points',capture_points))
        if item.category==Category.HAIRPIN and item.hairpin_style=='bun':
            original_bun=native.hair_placement.detect_bun
            def capture_bun(*args,**kwargs):
                placement=original_bun(*args,**kwargs)
                detected['bun_placement']=placement
                return placement
            stack.enter_context(patch.object(native.hair_placement,'detect_bun',capture_bun))
        if item.category==Category.PENDANT and hasattr(native,'_pendant_frame'):
            original_frame=native._pendant_frame
            def capture_pendant_frame(*args,**kwargs):
                frame=original_frame(*args,**kwargs)
                detected['pendant_frame']=frame
                return frame
            stack.enter_context(patch.object(native,'_pendant_frame',capture_pendant_frame))
        original=native.overlay_image
        def trace(base,overlay,anchor_xy,target_width,rotation_deg=0,overlay_anchor=(.5,.5)):
            h=target_width*overlay.height/max(1,overlay.width)
            if not math.isfinite(target_width+h) or target_width<0 or target_width+h>10000 or (target_width+h)**2/2>18000000:
                raise ValueError('Слишком большой размер украшения. Уменьшите масштаб или обрежьте прозрачные поля.')
            captures.append(dict(
                x=float(anchor_xy[0]),y=float(anchor_xy[1]),
                width=float(target_width),height=float(h),rotation=float(rotation_deg),
                anchor=[float(v) for v in overlay_anchor],
                image=data_image(overlay.convert('RGBA')),
                sign=1,editable=True,scale_with_item=True,rotate_with_item=True,
            ))
            return original(base,overlay,anchor_xy,target_width,rotation_deg,overlay_anchor)
        stack.enter_context(patch.object(native,'overlay_image',trace))
        result=native.apply_tryon(item,path,photo)
        if len(native._PAIR_CACHE)>64: native._PAIR_CACHE.clear()
    cat=item.category.value
    if cat=='hairpin' and detected.get('get_face_anchors') is None and 'bun_placement' in detected:
        unit=detected['bun_placement'].face_width
    elif cat in {'earrings','kaffy','diadem','hairpin'}: unit=detected['get_face_anchors'].face_width
    elif cat=='ring': unit=detected['get_ring_anchor'].finger_width
    elif cat=='bracelet': unit=detected['get_wrist_anchor'].wrist_width
    else: unit=detected['get_neck_anchor'].shoulder_width
    if not math.isfinite(unit) or unit<1: raise ValueError('Не удалось определить надёжный масштаб тела')
    for index,layer in enumerate(captures):
        if cat=='earrings':
            candidates=[]
            anchors=detected['get_face_anchors']
            points=visible_ears or {
                side:getattr(anchors,side+'_lobe') for side in ('left','right')
                if hasattr(anchors,side+'_lobe')
            }
            for side,point in points.items():
                sign=-1 if side=='left' else 1
                expected=(point[0]+unit*item.offset_x*sign,
                          point[1]+unit*item.offset_y)
                candidates.append((math.hypot(layer['x']-expected[0],layer['y']-expected[1]),sign))
            # An inseparable pair is placed once between both ears. Its X
            # offset uses +1; a split pair with one visible ear uses that ear.
            if item.pair_image and len(captures)==1 and len(points)==2:
                expected=((points['left'][0]+points['right'][0])/2+unit*item.offset_x,
                          (points['left'][1]+points['right'][1])/2+unit*item.offset_y)
                candidates.append((math.hypot(layer['x']-expected[0],layer['y']-expected[1]),1))
            if candidates: layer['sign']=min(candidates,key=lambda candidate:candidate[0])[1]
        elif cat=='kaffy':
            layer['sign']=1 if item.kaffy_side=='right' else -1
        elif cat=='hairpin' and item.hairpin_style=='side':
            layer['sign']=1 if item.hairpin_side=='right' else -1
        if cat=='pendant' and index<len(captures)-1:
            frame=detected.get('pendant_frame')
            chain_anchors=getattr(frame,'anchors',detected['get_neck_anchor'])
            layer.update(editable=False,scale_with_item=False,rotate_with_item=False,
                         height_with_item_offset=True,
                         height_axis=list(getattr(chain_anchors,'down',(0,1))),
                         min_height=1)
            if hasattr(native,'_neck_chain_height'):
                layer['height_offset_origin']=float(native._neck_chain_height(
                    chain_anchors,(layer['x'],layer['y']),
                    detected.get('get_face_anchors')))
            mask=getattr(frame,'occlusion_mask',None)
            if mask is not None:
                import numpy as np
                confidence=np.asarray(mask,dtype=np.float32)
                if confidence.shape!=(background.height,background.width) or not np.isfinite(confidence).all():
                    raise ValueError('Не удалось подготовить маску лица для примерки. Попробуйте другое фото.')
                alpha=Image.fromarray(np.rint(np.clip(confidence,0,1)*255).astype(np.uint8))
                occlusion=Image.new('RGBA',background.size,(255,255,255,0))
                occlusion.putalpha(alpha)
                layer['occlusion_mask']=data_image(occlusion)
    handles=[dict(x=layer['x'],y=layer['y'],sign=layer['sign'])
             for layer in captures if layer['editable']]
    with Image.open(io.BytesIO(result)) as im: width,height=im.size
    if background.size!=(width,height):
        raise ValueError('Размер референса изменился при обработке. Загрузите фото заново.')
    return dict(image='data:image/jpeg;base64,'+base64.b64encode(result).decode(),
                base_image=data_image(background,'JPEG'),width=width,height=height,
                unit=float(unit),handles=handles,layers=captures,settings=settings)

async def run_preview(p):
    try: await asyncio.wait_for(QUEUE.acquire(),timeout=3)
    except asyncio.TimeoutError: raise HTTPException(429,'Предпросмотр занят. Повторите через несколько секунд.')
    try: return await run_in_threadpool(render,p)
    except (ValueError,TryOnError) as e: raise HTTPException(422,str(e))
    except Exception:
        logging.exception('Ошибка предпросмотра')
        raise HTTPException(500,'Ошибка примерки. Проверьте журнал сервера и файлы моделей MediaPipe.')
    finally: QUEUE.release()

def commit_catalog(entries,current,new_image=None):
    """Called under .editor.lock by both save and delete."""
    data=(json.dumps(entries,ensure_ascii=False,indent=2)+'\n').encode()
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
        if not committed and new_image is not None: new_image.unlink(missing_ok=True)
    return hashlib.sha256(data).hexdigest()


def save(p,raw):
    with (GALLERY/'.editor.lock').open('a+b') as lock:
        fcntl.flock(lock,fcntl.LOCK_EX)
        entries,current=read_catalog()
        if current!=p.revision: raise HTTPException(409,'Каталог изменился. Обновите список, проверьте данные и повторите сохранение.')
        settings=p.settings.model_dump(mode='json')
        if p.component_id is not None:
            parents=[entry for entry in entries if entry['id']==p.editing_id]
            if len(parents)!=1 or parents[0]['category']!=Category.SET.value:
                raise HTTPException(409,'Редактируемый набор не найден. Откройте его заново.')
            parent=parents[0]
            parts=[part for part in parent.get('components',[]) if part['id']==p.component_id]
            if len(parts)!=1:
                raise HTTPException(409,'Украшение в наборе изменилось. Откройте набор заново.')
            target=parts[0]
            if not p.replace:
                raise HTTPException(409,'Откройте украшение набора для изменения.')
            if any(part['id']!=target['id'] and normalize(part['name'])==normalize(settings['name'])
                   for part in parent['components']):
                raise HTTPException(409,'Такое название уже есть у другого украшения этого набора.')
            entry=dict(target); entry.update(settings); entry['id']=target['id']
            folder=GALLERY/'custom'; folder.mkdir(exist_ok=True)
            image=folder/(uuid.uuid4().hex+'.png'); entry['image']=image.relative_to(GALLERY).as_posix()
            changed=dict(parent,components=[entry if part is target else part for part in parent['components']])
            try: validate_selection([item_from_dict(changed)])
            except (ValueError,TypeError,KeyError) as exc: raise HTTPException(422,str(exc))
            with image.open('xb') as f:
                f.write(raw); f.flush(); os.fsync(f.fileno())
            updated=[changed if existing is parent else existing for existing in entries]
            revision=commit_catalog(updated,current,new_image=image)
            return dict(entry=entry,parent=changed,revision=revision,updated=True)
        matches=[e for e in entries if normalize(e['name'])==normalize(settings['name'])]
        if len(matches)>1: raise HTTPException(409,'Несколько записей с одинаковым названием. Устраните дубликаты вручную.')
        target=matches[0] if matches else None
        if p.editing_id:
            selected=[e for e in entries if e['id']==p.editing_id]
            if len(selected)!=1: raise HTTPException(409,'Редактируемая запись не найдена или id неоднозначен')
            if target and target['id']!=p.editing_id: raise HTTPException(409,'Название принадлежит другой записи. Откройте её отдельно.')
            target=selected[0]
        if target is not None and not p.replace: raise HTTPException(409,'Такое название уже есть. Откройте существующее украшение для изменения.')
        if target is not None and target['category']==Category.SET.value:
            raise HTTPException(422,'Набор нельзя заменить одним украшением в этом редакторе.')
        entry=dict(target or {}); entry.update(settings)
        entry['id']=target['id'] if target else uuid.uuid4().hex
        folder=GALLERY/'custom'; folder.mkdir(exist_ok=True)
        image=folder/(uuid.uuid4().hex+'.png'); entry['image']=image.relative_to(GALLERY).as_posix()
        with image.open('xb') as f:
            f.write(raw); f.flush(); os.fsync(f.fileno())
        updated=[entry if e is target else e for e in entries] if target else entries+[entry]
        revision=commit_catalog(updated,current,new_image=image)
        return dict(entry=entry,revision=revision,updated=target is not None)


def delete_item(item_id,revision):
    with (GALLERY/'.editor.lock').open('a+b') as lock:
        fcntl.flock(lock,fcntl.LOCK_EX)
        entries,current=read_catalog()
        if revision!=current:
            raise HTTPException(409,'Каталог изменился. Обновите список перед удалением.')
        matches=[entry for entry in entries if entry['id']==item_id]
        if len(matches)!=1:
            raise HTTPException(404,'Позиция не найдена или ID неоднозначен')
        entry=matches[0]
        updated=[existing for existing in entries if existing is not entry]
        # Keep source images and the catalogue backup for recovery.
        return dict(removed=dict(id=entry['id'],name=entry['name']),
                    revision=commit_catalog(updated,current))

@app.get('/')
@app.get('/index.html')
def index(): return FileResponse(HERE/'static/index.html')
@app.get('/static/{name}')
def static(name:str):
    if name not in {'app.js','transforms.js','style.css'}: raise HTTPException(404)
    return FileResponse(HERE/'static'/name)

# Relative assets also resolve when the author opens static/index.html as a
# local file. The same URLs work under a reverse-proxy prefix such as /editor/.
@app.get('/style.css')
def stylesheet(): return static('style.css')
@app.get('/app.js')
def application_script(): return static('app.js')
@app.get('/transforms.js')
def transform_script(): return static('transforms.js')
@app.get('/api/catalog')
def catalog():
    entries,revision=read_catalog()
    return dict(entries=[dict(e,editable=e['category']!=Category.SET.value) for e in entries],revision=revision,
                categories=[dict(value=c.value,title=CATEGORY_TITLES[c]) for c in Category if c!=Category.SET])
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
def load(item_id:str,component_id:str|None=None):
    entries,revision=read_catalog(); matches=[e for e in entries if e['id']==item_id]
    if len(matches)!=1: raise HTTPException(404,'Запись не найдена или id неоднозначен')
    entry=matches[0]; parent=None
    if component_id is not None:
        if entry['category']!=Category.SET.value: raise HTTPException(422,'У этой позиции нет частей набора.')
        parent=entry
        parts=[part for part in parent.get('components',[]) if part['id']==component_id]
        if len(parts)!=1: raise HTTPException(404,'Украшение в наборе не найдено')
        entry=parts[0]
    elif entry['category']==Category.SET.value:
        raise HTTPException(422,'Выберите отдельное украшение из набора для подгонки.')
    try:
        # A validated upload can become opaque when transparent margins are
        # cropped (e.g. a rectangular ornament). Keep its pixels and anchors.
        raw=prepare(image_path(entry).read_bytes(),True,require_transparency=False)
        return dict(entry=entry,parent=parent,asset=put_asset(raw,'jewelry'),revision=revision)
    except ValueError as e: raise HTTPException(422,str(e))
@app.post('/api/preview')
async def preview_endpoint(request:Request): return await run_preview(parse(await json_body(request)))
@app.post('/api/save')
async def save_endpoint(request:Request):
    p=parse(await json_body(request)); await run_preview(p)
    try: _,raw=asset(p.asset,'jewelry')
    except ValueError as e: raise HTTPException(422,str(e))
    return await run_in_threadpool(save,p,raw)


@app.get('/api/references')
def references():
    refs=available_references()
    defaults={}
    for reference in refs.values():
        for category in reference['categories']:
            defaults.setdefault(category,reference['id'])
    return dict(references=[{key:value for key,value in ref.items() if key!='path'}
                            for ref in refs.values()],defaults=defaults)

@app.get('/api/reference/{reference_id}')
def reference_image(reference_id:str):
    return Response(reference_bytes(reference_id),media_type='image/jpeg')

@app.post('/api/reference/{reference_id}')
def select_reference(reference_id:str):
    return dict(token=put_asset(reference_bytes(reference_id),'photo'))

@app.get('/api/asset/{token}')
def asset_image(token:str):
    try: path,raw=asset(token,None)
    except ValueError as exc: raise HTTPException(404,str(exc))
    return Response(raw,media_type='image/png' if path.suffix=='.png' else 'image/jpeg')

@app.get('/api/image/{item_id}')
def catalog_image(item_id:str):
    entries,_=read_catalog()
    matches=[entry for entry in entries if entry['id']==item_id]
    if len(matches)!=1: raise HTTPException(404,'Позиция не найдена')
    try:
        with Image.open(image_path(matches[0])) as source:
            image=source.convert('RGBA')
            image.thumbnail((320,320),Image.Resampling.LANCZOS)
            out=io.BytesIO(); image.save(out,format='PNG')
    except (OSError,ValueError,Image.DecompressionBombError):
        raise HTTPException(404,'Изображение позиции недоступно')
    return Response(out.getvalue(),media_type='image/png')

@app.delete('/api/items/{item_id}')
async def delete_endpoint(item_id:str,request:Request):
    raw=await json_body(request)
    if not isinstance(raw,dict) or raw.get('confirm') is not True:
        raise HTTPException(422,'Подтвердите удаление выбранной позиции.')
    revision=raw.get('revision')
    if not isinstance(revision,str):
        raise HTTPException(422,'Обновите каталог перед удалением.')
    return await run_in_threadpool(delete_item,item_id,revision)


def rename_item(item_id,revision,name):
    with (GALLERY/'.editor.lock').open('a+b') as lock:
        fcntl.flock(lock,fcntl.LOCK_EX)
        entries,current=read_catalog()
        if revision!=current: raise HTTPException(409,'Каталог изменился. Откройте позицию заново.')
        selected=[entry for entry in entries if entry['id']==item_id]
        if len(selected)!=1: raise HTTPException(404,'Позиция не найдена')
        if any(entry['id']!=item_id and normalize(entry['name'])==normalize(name) for entry in entries):
            raise HTTPException(409,'Такое название уже есть у другой позиции.')
        target=selected[0]; changed=dict(target,name=name)
        updated=[changed if entry is target else entry for entry in entries]
        return dict(entry=changed,revision=commit_catalog(updated,current))


@app.patch('/api/items/{item_id}')
async def rename_endpoint(item_id:str,request:Request):
    raw=await json_body(request)
    if not isinstance(raw,dict) or not isinstance(raw.get('name'),str) or not isinstance(raw.get('revision'),str):
        raise HTTPException(422,'Укажите название и обновите каталог.')
    name=' '.join(raw['name'].split())
    if not 1<=len(name)<=160: raise HTTPException(422,'Название должно содержать от 1 до 160 символов.')
    return await run_in_threadpool(rename_item,item_id,raw['revision'],name)
