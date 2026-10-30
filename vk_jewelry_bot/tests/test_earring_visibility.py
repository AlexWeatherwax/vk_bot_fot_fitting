from types import SimpleNamespace
import numpy as np
import pytest
from PIL import Image

pytest.importorskip('mediapipe')
from bot.tryon import pipeline as p
from bot.jewelry.models import Category, JewelryItem


@pytest.mark.parametrize('pair,single', [(False,False),(True,False),(False,True)])
def test_only_visible_ear_is_rendered(monkeypatch,pair,single):
    a=SimpleNamespace(face_width=100,tilt_angle=0,left_lobe=(20,50),right_lobe=(80,50))
    monkeypatch.setattr(p.face_mod,'get_face_anchors',lambda image,**kw:a)
    monkeypatch.setattr(p,'earring_points',lambda image,anchors:{'right':(82,55)})
    overlay=Image.new('RGBA',(20,60),(255,0,0,255))
    if pair:monkeypatch.setattr(p,'split_pair',lambda *args:(overlay,overlay))
    calls=[]
    def record(base,image,point,*args,**kwargs):
        calls.append(point)
        return base
    monkeypatch.setattr(p,'overlay_image',record)
    item=JewelryItem('test','test',Category.EARRINGS,'test.png',pair_image=pair,single_ear=single)
    p._apply_earrings(Image.new('RGB',(100,100)),overlay,np.zeros((100,100,3),dtype=np.uint8),item)
    assert calls==[(82,55)]


def test_no_detected_ears_does_not_guess(monkeypatch):
    monkeypatch.setattr(p.face_mod,'get_face_anchors',lambda image,**kw:object())
    monkeypatch.setattr(p,'earring_points',lambda image,anchors:{})
    item=JewelryItem('test','test',Category.EARRINGS,'test.png')
    with pytest.raises(p.TryOnError,match='открытое ухо'):
        p._apply_earrings(None,None,None,item)
