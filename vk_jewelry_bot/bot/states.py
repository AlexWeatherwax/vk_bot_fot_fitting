"""
Состояния диалога (FSM) для vkbottle.

Пока пользователь находится в состоянии WAITING_PHOTO, следующее его сообщение
(с фото или без) перехватывается обработчиком из bot/handlers/photo.py.
В payload хранится item_ids с одним ID: украшения или готового набора.
Пока фото не отправлено, выбор можно заменить другим украшением или набором.
"""
from vkbottle import BaseStateGroup


class TryOnStates(BaseStateGroup):
    WAITING_PHOTO = "waiting_photo"
