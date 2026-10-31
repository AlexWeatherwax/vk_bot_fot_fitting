from pathlib import Path
import argparse,os,sys,time,json,hashlib,statistics
os.environ['ORT_DISABLE_TELEMETRY']='1'
ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT))
ap=argparse.ArgumentParser(description='Offline research probe; no training and no image downloads. Run through offline.py on Linux.')
ap.add_argument('--sam-dir',type=Path,required=True)
ap.add_argument('--dino-dir',type=Path,required=True)
ap.add_argument('--photos',type=Path,required=True)
ap.add_argument('--output',type=Path,required=True)
ap.add_argument('--debug-dir',type=Path,help='Optional private mask previews; delete after review')
args=ap.parse_args()
import cv2,numpy as np,onnxruntime as ort
from PIL import Image,ImageDraw
from bot.tryon.landmarks_face import get_face_anchors
opt=ort.SessionOptions();opt.intra_op_num_threads=2;opt.inter_op_num_threads=1
enc=ort.InferenceSession(str(args.sam_dir/'encoder.onnx'),sess_options=opt,providers=['CPUExecutionProvider'])
dec=ort.InferenceSession(str(args.sam_dir/'decoder.onnx'),sess_options=opt,providers=['CPUExecutionProvider'])
dino=ort.InferenceSession(str(args.dino_dir/'model_quantized.onnx'),sess_options=opt,providers=['CPUExecutionProvider'])
vocab=(args.dino_dir/'vocab.txt').read_text().splitlines()
ids=np.array([[vocab.index('[CLS]'),vocab.index('ear'),vocab.index('.'),vocab.index('[SEP]')]],np.int64)
def predict(im):
 a=get_face_anchors(cv2.cvtColor(np.array(im),cv2.COLOR_RGB2BGR),lobe_down=.05)
 if a is None:return None,[]
 cx=(a.left_ear[0]+a.right_ear[0])/2;cy=(a.forehead_top[1]+a.chin[1])/2;side=a.face_width*1.65
 box=tuple(round(v) for v in (cx-side/2,cy-side/2,cx+side/2,cy+side/2));crop=im.crop(box)
 t=np.asarray(crop.resize((1024,1024),Image.Resampling.BILINEAR),np.float32)/255
 t=(t-np.array([.485,.456,.406],np.float32))/np.array([.229,.224,.225],np.float32)
 features=enc.run(None,{'image':t.transpose(2,0,1)[None]});feed=dict(zip([o.name for o in enc.get_outputs()],features))
 out=np.array(crop.resize((512,512)));rows=[]
 dt=np.asarray(crop.resize((800,800),Image.Resampling.BILINEAR),np.float32)/255
 dt=(dt-np.array([.485,.456,.406],np.float32))/np.array([.229,.224,.225],np.float32)
 lg,bb=dino.run(None,{'pixel_values':dt.transpose(2,0,1)[None],'input_ids':ids,'token_type_ids':np.zeros_like(ids),'attention_mask':np.ones_like(ids),'pixel_mask':np.ones((1,800,800),np.int64)})
 confidence=1/(1+np.exp(-np.clip(lg[0,:,1],-50,50)))
 for name,sign,ear in [('left',-1,a.left_ear),('right',1,a.right_ear)]:
  x,y=ear;f=a.face_width
  options=[]
  for k in np.where(confidence>=.25)[0]:
   xx,yy,ww,hh=bb[0,k]*crop.width
   if not (.015*f<ww<.40*f and .05*f<hh<.65*f):continue
   if np.linalg.norm(np.array([xx+box[0],yy+box[1]])-ear)>.40*f:continue
   options.append((float(confidence[k]),xx,yy,ww,hh))
  if not options:continue
  detection_score,xx,yy,ww,hh=max(options)
  pts=np.array([[xx-ww/2,yy-hh/2],[xx+ww/2,yy+hh/2],[xx,yy]],np.float32)*1024/crop.width
  masks,scores=dec.run(None,{**feed,'point_coords':pts[None],'point_labels':np.array([[2,3,1]],np.float32),'mask_input':np.zeros((1,1,256,256),np.float32),'has_mask_input':np.zeros(1,np.float32)})
  k=int(np.argmax(scores[0]));m=cv2.resize(masks[0,k],(512,512))>0;ys,xs=np.where(m)
  if len(xs)==0:continue
  top,bottom=np.quantile(ys,[.02,.98]);level=bottom-.12*(bottom-top);band=np.abs(ys-level)<=max(2,.04*(bottom-top))
  px,py=float(np.median(xs[band])),float(np.median(ys[band]));point=[box[0]+px*crop.width/512,box[1]+py*crop.height/512]
  rows.append({'side':name,'detector_score':detection_score,'score':float(scores[0,k]),'area_fraction':len(xs)/512**2,'point':point,'baseline':list(getattr(a,name+'_lobe')),'crop_point':[px,py],'face_width':f})
  out[m]=(out[m]*.5+np.array([0,255,0])*.5).astype(np.uint8);cv2.circle(out,(round(px),round(py)),4,(255,0,0),-1)
 return out,rows
if __name__=='__main__':
 files=sorted(p for p in args.photos.iterdir() if p.suffix.lower() in {'.jpg','.jpeg','.png'})
 if not files:raise SystemExit('No input photos')
 report=[];seen=set()
 for p in files:
  digest=hashlib.sha256(p.read_bytes()).hexdigest()
  if digest in seen:continue
  seen.add(digest);start=time.perf_counter()
  out,rows=predict(Image.open(p).convert('RGB'))
  if args.debug_dir and out is not None:
   args.debug_dir.mkdir(parents=True,exist_ok=True)
   Image.fromarray(out).save(args.debug_dir/(digest+'.jpg'))
  report.append({'sample_sha256':digest,'seconds':round(time.perf_counter()-start,3),'predictions':rows})
  print('processed',len(report),'detected sides',len(rows),flush=True)
 result={'training_performed':False,'unique_images':len(report),
         'median_seconds':statistics.median(r['seconds'] for r in report),'samples':report}
 args.output.parent.mkdir(parents=True,exist_ok=True)
 args.output.write_text(json.dumps(result,indent=2)+'\n')
