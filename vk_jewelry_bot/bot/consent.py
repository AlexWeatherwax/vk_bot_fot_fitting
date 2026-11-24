"""Explicit photo-processing consent, before any catalog/try-on handler runs."""
import hashlib
import json
import logging

from .handlers.master import is_master_request
from .commands import command_key


logger = logging.getLogger("vk_jewelry_bot.consent")
VK_PRIVACY_URL = "https://vk.com/privacy"
REVOKE_COMMAND = "Отозвать согласие"
CONSENT_TEXT = """СОГЛАСИЕ НА ОБРАБОТКУ ПЕРСОНАЛЬНЫХ ДАННЫХ

Я, пользователь, действуя свободно, своей волей и в своём интересе, даю согласие самозанятому Павленко Т.В., ИНН 263207534488 (далее — Оператор), на обработку моих персональных данных на следующих условиях.

1. Какие данные обрабатываются: изображения (фотографии), которые я направляю в чат-бот для примерки, а также связанные с ними технические данные, необходимые для работы бота (идентификатор пользователя, идентификатор диалога). Для учёта согласия сохраняются эти идентификаторы, версия текста и даты предоставления и отзыва согласия.

2. Цель обработки: виртуальная примерка украшений на моих изображениях и возврат результата в этот же диалог; учёт предоставления и отзыва согласия. Изображения не используются для установления моей личности и не относятся к биометрическим персональным данным в смысле ст. 11 152-ФЗ, если иное прямо не следует из функциональности бота.

3. Как происходит обработка: изображения передаются на технические ресурсы, обеспечивающие работу бота, обрабатываются на сервере и возвращаются в диалог. Для работы бота используются платформа ВКонтакте и услуги хостинга. Внешние API обработки изображений не используются.

4. Хранение: Оператор не создаёт отдельных баз данных для долгосрочного хранения исходных изображений или результатов обработки. Изображения сохраняются в истории диалога на платформе ВКонтакте и далее обрабатываются в соответствии с её условиями и политикой конфиденциальности. Если Оператор временно сохраняет файлы для технической обработки, срок такого хранения ограничивается временем, необходимым для достижения цели обработки.

5. Отзыв согласия: я могу отозвать настоящее согласие, направив в этот чат-бот команду «Отозвать согласие». После этого бот остановит текущую примерку; для новой примерки потребуется повторное согласие. Отзыв согласия не распространяется на обработку, уже осуществлённую до момента отзыва, а также на хранение изображений в истории диалога ВКонтакте, которое регулируется платформой.

6. Политика конфиденциальности платформы: условия обработки данных платформой ВКонтакте изложены в её Политике конфиденциальности: {policy_url}.

Нажимая кнопку «Начать», я даю указанное согласие на обработку персональных данных. Настоящее согласие действует до его отзыва, но не дольше, чем этого требуют цели обработки.

Если вы не согласны, не нажимайте «Начать» и не отправляйте фотографии. Связаться с Оператором можно командой «Позови мастера»."""
FAILURE_REPLY = (
    "Не удалось сохранить или проверить согласие. Примерка остановлена. "
    "Попробуйте ещё раз позже или напишите «Позови мастера»."
)


def _normalized(text):
    return command_key(text)


def _payload(message):
    value = getattr(message, "payload", None)
    if isinstance(value, str):
        if len(value) > 2048:
            return {}
        try:
            value = json.loads(value)
        except (ValueError, TypeError):
            return {}
    return value if isinstance(value, dict) else {}


class ConsentGate:
    def __init__(self, store, group_id, policy_url=VK_PRIVACY_URL):
        if policy_url != VK_PRIVACY_URL:
            raise ValueError("Use the verified VK privacy policy URL")
        self.store = store
        self.group_id = int(group_id)
        self.text = CONSENT_TEXT.format(policy_url=policy_url)
        self.version = hashlib.sha256(self.text.encode("utf-8")).hexdigest()
        self.policy_url = policy_url
        # A failed durable revocation must never fall back to an old acceptance
        # while this process is alive. A fresh button acceptance clears the block.
        self._blocked = set()

    def _subject(self, message):
        user_id = getattr(message, "from_id", None)
        peer_id = getattr(message, "peer_id", None)
        if (type(user_id) is not int or user_id <= 0
                or type(peer_id) is not int or peer_id <= 0):
            raise ValueError("Missing positive message identity")
        return self.group_id, user_id, peer_id

    def is_allowed(self, message):
        """Fail closed also between asynchronous photo-processing steps."""
        try:
            subject = self._subject(message)
            return subject not in self._blocked and self.store.has_consent(subject, self.version)
        except Exception as error:
            logger.warning("Consent check failed: type=%s", type(error).__name__)
            return False

    async def _show(self, message, subject):
        # Keep each VK message below its 4096-character limit; only the last
        # part carries the acceptance button, after the complete text was sent.
        remaining = self.text
        while len(remaining) > 3900:
            boundary = remaining.rfind("\n\n", 0, 3900)
            if boundary < 1:
                boundary = 3900
            await message.answer(remaining[:boundary])
            remaining = remaining[boundary:].lstrip("\n")
        token = self.store.issue_challenge(subject, self.version, self.text, self.policy_url)
        keyboard = {
            "inline": True,
            "buttons": [[{
                "action": {
                    "type": "text", "label": "Начать",
                    "payload": json.dumps({
                        "action": "accept_consent", "version": self.version, "token": token,
                    }, ensure_ascii=False),
                },
                "color": "positive",
            }]],
        }
        await message.answer(remaining, keyboard=json.dumps(keyboard, ensure_ascii=False))

    async def intercept(self, bot, message):
        """Return True when handled here, False when normal flow may continue."""
        # Contacting the operator remains available before agreeing or after
        # withdrawal. It does not download or process any photograph.
        if is_master_request(message.text):
            return False
        text = _normalized(message.text)
        try:
            subject = self._subject(message)
            if text == REVOKE_COMMAND.casefold():
                await self.revoke(bot, message)
                return True

            payload = _payload(message)
            if payload.get("action") == "accept_consent":
                if (payload.get("version") == self.version
                        and isinstance(payload.get("token"), str)
                        and self.store.accept(subject, self.version, payload["token"])):
                    self._blocked.discard(subject)
                    await bot.state_dispenser.delete(message.peer_id)
                    from .handlers.common import send_welcome
                    await send_welcome(message)
                elif self.is_allowed(message):
                    await message.answer(
                        "Согласие уже получено. Напишите «Каталог», чтобы выбрать украшение. "
                        "Для отзыва напишите «Отозвать согласие»."
                    )
                else:
                    await bot.state_dispenser.delete(message.peer_id)
                    await self._show(message, subject)
                return True

            if text in {"согласие", "условия", "конфиденциальность"}:
                if self.is_allowed(message):
                    await message.answer(self.text)
                else:
                    await bot.state_dispenser.delete(message.peer_id)
                    await self._show(message, subject)
                return True

            if self.is_allowed(message):
                return False
            await bot.state_dispenser.delete(message.peer_id)
            await self._show(message, subject)
            return True
        except Exception as error:
            # No exception text, IDs, payloads, photographs or VK credentials.
            logger.warning("Consent operation failed: type=%s", type(error).__name__)
            await bot.state_dispenser.delete(message.peer_id)
            await message.answer(FAILURE_REPLY)
            return True

    async def revoke(self, bot, message, *, notify=True):
        subject = self._subject(message)
        self._blocked.add(subject)
        await bot.state_dispenser.delete(message.peer_id)
        self.store.revoke(subject)
        if notify:
            await message.answer(
                'Согласие отозвано. Текущая примерка остановлена. '
                'Для новой примерки напишите «Начать» и подтвердите согласие заново. '
                'Фотографии в истории ВКонтакте удаляются средствами самой платформы.'
            )
