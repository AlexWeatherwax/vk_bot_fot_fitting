"""
Загрузка конфигурации бота из переменных окружения (.env файл или окружение сервера).
"""
import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent.parent
load_dotenv(BASE_DIR / ".env")


@dataclass
class Config:
    vk_token: str
    group_id: int
    tmp_dir: Path
    log_level: str


def load_config() -> Config:
    token = os.getenv("VK_TOKEN")
    if not token:
        raise RuntimeError(
            "Не задана переменная окружения VK_TOKEN. "
            "Скопируйте .env.example в .env и заполните токен сообщества ВК."
        )

    group_id_raw = os.getenv("VK_GROUP_ID")
    if not group_id_raw:
        raise RuntimeError(
            "Не задана переменная окружения VK_GROUP_ID. "
            "Укажите числовой ID сообщества в .env."
        )

    tmp_dir_raw = os.getenv("TMP_DIR")
    tmp_dir = Path(tmp_dir_raw) if tmp_dir_raw else (BASE_DIR / "data" / "tmp")
    if not tmp_dir.is_absolute():
        tmp_dir = BASE_DIR / tmp_dir
    tmp_dir.mkdir(parents=True, exist_ok=True)

    return Config(
        vk_token=token,
        group_id=int(group_id_raw),
        tmp_dir=tmp_dir,
        log_level=os.getenv("LOG_LEVEL", "INFO"),
    )


config = load_config()
