#!/usr/bin/env python3
"""
Точка входа: и для локального теста (`python run.py`), и для запуска на
сервере (например, через systemd — см. systemd/vk-jewelry-bot.service).
"""
from bot.app import run

if __name__ == "__main__":
    run()
