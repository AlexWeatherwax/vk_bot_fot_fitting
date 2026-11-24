"""Highlight a buyer's request in the community inbox without personal DMs."""
import asyncio
import logging

from ..commands import command_key


logger = logging.getLogger("vk_jewelry_bot.master")
MASTER_COMMAND = "Позови мастера"
MARKED_REPLY = (
    "Диалог отмечен для мастера ✨ Он сможет ответить вам здесь. "
    "Примерку можно продолжить."
)
RECEIVED_REPLY = "Запрос мастеру получен. Оставьте свой вопрос в этом диалоге."
FAILED_REPLY = (
    "Не получилось выделить диалог для мастера автоматически. "
    "Пожалуйста, повторите «Позови мастера» чуть позже."
)


def is_master_request(text):
    return command_key(text) == "позови мастера"


async def _mark(bot, message, method, **flag):
    params = {"peer_id": message.peer_id, **flag}
    group_id = getattr(getattr(bot, "polling", None), "group_id", None)
    if group_id is not None:
        params["group_id"] = group_id
    try:
        response = await asyncio.wait_for(bot.api.request(method, params), timeout=10)
        if not isinstance(response, dict) or response.get("response") != 1:
            logger.warning("Master request marker returned an unexpected result: %s", method)
            return False
        return True
    except Exception as error:
        # SDK exceptions can contain request URLs or parameters. Log only
        # their type and numeric code, never the original exception text.
        code = getattr(error, "code", None)
        logger.warning("Master request marker failed: method=%s type=%s code=%s",
                       method, type(error).__name__, code if isinstance(code, int) else "unknown")
        return False


async def _answer(message, text):
    try:
        await message.answer(text)
    except Exception as error:
        logger.warning("Master request acknowledgement failed: type=%s", type(error).__name__)


async def request_master(bot, message):
    # Keep the selected item and any running try-on. The important flag is
    # persistent until community staff clear it, even if the bot replies later.
    important = await _mark(bot, message, "messages.markAsImportantConversation", important=1)
    await _answer(message, MARKED_REPLY if important else RECEIVED_REPLY)
    # Apply this after the outgoing acknowledgement, so that reply cannot
    # immediately classify the request as already answered.
    unanswered = await _mark(bot, message, "messages.markAsAnsweredConversation", answered=0)
    if not important and not unanswered:
        await _answer(message, FAILED_REPLY)
    return important or unanswered
