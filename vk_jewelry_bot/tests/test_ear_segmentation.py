from types import SimpleNamespace
import numpy as np
import pytest
from bot.tryon.ear_segmentation import points_from_logits


def anchors():
    return SimpleNamespace(left_ear=(60,100), right_ear=(140,100),
                           chin=(100,170),forehead_top=(100,30),face_width=80)


def logits():
    a=np.full((200,200,19),-8,dtype=np.float32)
    a[:,:,0]=8
    return a


def paint(a,box,label):
    x0,y0,x1,y1=box
    a[y0:y1,x0:x1,:]=-8
    a[y0:y1,x0:x1,label]=8


def test_two_ears_assigned_by_image_position_not_class_name():
    a=logits();paint(a,(50,80,65,120),8);paint(a,(135,80,150,120),9)
    result=points_from_logits(a,(0,0,200,200),(200,200),anchors())
    assert set(result)=={'left','right'}
    assert result['left'].point[0]==pytest.approx(57.5)
    assert 112<result['left'].point[1]<117
    assert result['right'].point[0]==pytest.approx(142.5)


def test_hidden_side_is_not_invented():
    a=logits();paint(a,(135,80,150,120),8)
    assert set(points_from_logits(a,(0,0,200,200),(200,200),anchors()))=={'right'}


def test_noise_and_low_confidence_rejected():
    a=logits();paint(a,(55,100,58,103),8)
    assert not points_from_logits(a,(0,0,200,200),(200,200),anchors())
    assert not points_from_logits(np.zeros_like(a),(0,0,200,200),(200,200),anchors())


def test_far_away_component_rejected():
    a=logits();paint(a,(5,5,20,40),8)
    assert not points_from_logits(a,(0,0,200,200),(200,200),anchors())


def test_crop_coordinates_scale_back_to_photo():
    a=logits();paint(a,(50,80,65,120),8)
    b=anchors()
    b.left_ear=(130,220);b.right_ear=(290,220)
    b.chin=(210,360);b.forehead_top=(210,80);b.face_width=160
    result=points_from_logits(a,(10,20,410,420),(500,500),b)
    assert result['left'].point[0]==pytest.approx(125)


def test_nonfinite_model_output_rejected():
    a=logits();a[0,0,0]=np.nan
    with pytest.raises(ValueError):
        points_from_logits(a,(0,0,200,200),(200,200),anchors())


def test_default_path_does_not_load_onnx(monkeypatch):
    from bot.tryon import ear_segmentation as m
    monkeypatch.delenv('EAR_PARSER_MODEL', raising=False)
    def unexpected(*args):
        raise AssertionError('default mode must not load a parser')
    monkeypatch.setattr(m,'_parser_for',unexpected)
    a=SimpleNamespace(left_lobe=(10,20),right_lobe=(30,20))
    assert m.earring_points(None,a)=={'left':(10,20),'right':(30,20)}


def test_configured_parser_keeps_only_detected_ear(monkeypatch):
    from bot.tryon import ear_segmentation as m
    monkeypatch.setenv('EAR_PARSER_MODEL','models/approved.onnx')
    parser=SimpleNamespace(predict=lambda image,a:{'right':m.EarPoint((30,20),.9,100)})
    monkeypatch.setattr(m,'_parser_for',lambda path: parser)
    assert m.earring_points(None,None)=={'right':(30,20)}


def test_ort_telemetry_disabled_before_session(monkeypatch):
    import os
    import sys
    from bot.tryon.ear_segmentation import EarParser
    calls=[]
    def disable():
        assert os.environ['ORT_DISABLE_TELEMETRY']=='1'
        calls.append('disable')
    def session(*args,**kwargs):
        assert calls==['disable']
        return object()
    monkeypatch.delenv('ORT_DISABLE_TELEMETRY',raising=False)
    monkeypatch.setitem(sys.modules,'onnxruntime',SimpleNamespace(
        SessionOptions=lambda:SimpleNamespace(),disable_telemetry_events=disable,
        InferenceSession=session))
    EarParser('unused.onnx')
