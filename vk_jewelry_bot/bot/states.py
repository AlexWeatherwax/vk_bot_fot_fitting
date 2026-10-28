"""
Состояния диалога (FSM) для vkbottle.

Пока пользователь находится в состоянии WAITING_PHOTO, следующее его сообщение
(с фото или без) перехватывается обработчиком из bot/handlers/photo.py —
это позволяет вести пошаговый диалог "выбрали украшение -> прислали фото".
"""
from vkbottle import BaseStateGroup


class TryOnStates(BaseStateGroup):
    WAITING_PHOTO = "waiting_photo"
