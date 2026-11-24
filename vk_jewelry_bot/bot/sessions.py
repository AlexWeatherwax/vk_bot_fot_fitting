"""Explicit start/finish boundary so ordinary community conversations stay quiet."""
import json
import logging

from .commands import SESSION_FINISH_COMMAND, SESSION_START_WORDS, command_key

logger = logging.getLogger('vk_jewelry_bot.sessions')


def session_keyboard(active):
    return json.dumps({'one_time': False, 'buttons': [[{
        'action': {'type': 'text', 'label': 'Завершить примерку' if active else 'Начать'},
        'color': 'secondary' if active else 'positive',
    }]]}, ensure_ascii=False)


class SessionGate:
    def __init__(self, store, group_id):
        self.store = store
        self.group_id = int(group_id)
        self._blocked = set()

    def _subject(self, message):
        subject = self.group_id, getattr(message, 'from_id', None), getattr(message, 'peer_id', None)
        if any(type(value) is not int or value <= 0 for value in subject):
            raise ValueError('Missing positive message identity')
        return subject

    def current_token(self, message):
        try:
            subject = self._subject(message)
            return None if subject in self._blocked else self.store.get_token(subject)
        except Exception as error:
            logger.warning('Session check failed: type=%s', type(error).__name__)
            return None

    def is_current(self, message, token):
        return token is not None and self.current_token(message) == token

    async def intercept(self, bot, message, consent_gate):
        """True consumes the message, including quiet messages outside a session."""
        key = command_key(message.text)
        explicit = key in SESSION_START_WORDS or key == SESSION_FINISH_COMMAND
        was_active = False
        try:
            subject = self._subject(message)
            token = self.current_token(message)
            was_active = token is not None
            if key == 'отозвать согласие':
                # Withdrawal is honoured even outside a session, silently. It
                # must never require starting the bot or accepting again first.
                self._blocked.add(subject)
                await consent_gate.revoke(bot, message, notify=was_active)
                self.store.finish(subject)
                return True
            if key == SESSION_FINISH_COMMAND:
                # Block in-flight replies before the first await.
                self._blocked.add(subject)
                self.store.finish(subject)
                await bot.state_dispenser.delete(message.peer_id)
                if was_active:
                    await message.answer(
                        'Примерка завершена. Бот больше не отвечает на обычные сообщения — '
                        'можно общаться с владельцем мастерской. '
                        'Чтобы снова включить примерочную, напишите «Начать».',
                        keyboard=session_keyboard(False),
                    )
                return True
            if key in SESSION_START_WORDS:
                if not was_active:
                    # Clear old tokens left by a failed finish before reopening.
                    if subject in self._blocked:
                        self.store.finish(subject)
                    self.store.start(subject)
                    self._blocked.discard(subject)
                    await bot.state_dispenser.delete(message.peer_id)
                return False
            return not was_active
        except Exception as error:
            logger.warning('Session operation failed: type=%s', type(error).__name__)
            if explicit:
                await message.answer('Не удалось переключить примерочную. Повторите команду чуть позже.')
            return True
