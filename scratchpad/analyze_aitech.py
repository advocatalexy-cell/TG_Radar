#!/usr/bin/env python3
"""
Анализатор AI и технологических сигналов за указанную дату.
Более узкая фильтрация - только AI/Tech сигналы и соответствующие ключевые слова.
"""

import json
import os
import re
from pathlib import Path
from datetime import datetime
from collections import defaultdict

# Карта channel_id → username
CHANNEL_MAP = {
    "allthingslegal": "allthingslegal",
    "gpt-for-lawyers": "GPT_for_Lawyers",
    "ai-skrepka": "AI_Skrepka",
    "legalmindai": "LegalMindAI",
}

# Ключевые слова AI/Tech тематики (case-insensitive)
AI_TECH_KEYWORDS = {
    "ai", "llm", "claude", "gpt", "модель", "автоматизация", "агент",
    "инструмент", "api", "продукт", "исследование", "нейросеть", "rag",
    "embedding", "inference", "benchmark", "нейрон", "deep learning",
    "machine learning", "neural", "algorithm", "legaltech", "docsllm",
    "документооборот", "обработка текста", "естественный язык", "код",
    "tool", "tools", "модели", "искусственный интеллект"
}

# Категории для фильтрации - только AI и Tech
TARGET_CATEGORIES = {"ai", "tech"}


def get_channel_username(channel_id):
    """Получить username по channel_id."""
    if channel_id in CHANNEL_MAP:
        return CHANNEL_MAP[channel_id]
    return channel_id


def has_ai_keywords(keywords):
    """Проверить наличие AI-ключевых слов в списке."""
    if not keywords:
        return False

    keywords_lower = {kw.lower() for kw in keywords}
    return bool(keywords_lower & AI_TECH_KEYWORDS)


def should_include_signal(classification):
    """Проверить, должен ли сигнал быть включен (узкая фильтрация)."""
    # Проверяем signal == true с приоритетом, но только для AI/Tech
    if classification.get("signal") == True:
        category = classification.get("category", "").lower()
        keywords = classification.get("keywords", [])
        # Signal=true сигнал должен быть о AI/Tech или иметь AI keywords
        if category in TARGET_CATEGORIES or has_ai_keywords(keywords):
            return True

    # Проверяем категорию (только AI и Tech, без Business и Finance)
    category = classification.get("category", "").lower()
    if category in TARGET_CATEGORIES:
        return True

    # Проверяем ключевые слова
    keywords = classification.get("keywords", [])
    if has_ai_keywords(keywords):
        return True

    return False


def categorize_signal(classification, text):
    """Определить категорию сигнала для группировки."""
    keywords = {kw.lower() for kw in classification.get("keywords", [])}
    summary = classification.get("summary", "").lower()
    text_lower = text.lower()

    # Ищем признаки категорий
    is_model_research = bool({
        "исследование", "research", "модель", "model", "llm", "gpt",
        "claude", "deepseek", "benchmark", "тестирование", "анализ",
        "анализирует", "анализируют", "analysis", "проект", "обзор"
    } & (keywords | {summary} | {text_lower}))

    is_tool_product = bool({
        "инструмент", "tool", "продукт", "product", "сервис", "service",
        "api", "платформа", "platform", "приложение", "application",
        "legaltech", "docsllm", "yandex", "github", "opensource", "code",
        "библиотека", "framework", "library", "решение", "solution"
    } & (keywords | {summary} | {text_lower}))

    is_legal_practice = bool({
        "юридический", "legal", "договор", "contract", "документ", "document",
        "юристы", "lawyers", "право", "law", "судебный", "court",
        "автоматизация", "automation", "документооборот", "судопроизводство",
        "практика", "practice", "ходатайство", "исковое", "обвинение"
    } & (keywords | {summary} | {text_lower}))

    return {
        "model_research": is_model_research,
        "tool_product": is_tool_product,
        "legal_practice": is_legal_practice
    }


def load_signals(date_str):
    """Загрузить все сигналы за дату."""
    signals = {
        "all": [],
        "model_research": [],
        "tool_product": [],
        "legal_practice": []
    }

    processed_dir = Path(f"D:/YandexDisk/Zerocoder/ClaudeCode/Radar/data/processed")

    # Поиск всех файлов за указанную дату
    pattern = f"{date_str}-*-processed.json"

    for file_path in processed_dir.glob(pattern):
        try:
            with open(file_path, 'r', encoding='utf-8') as f:
                data = json.load(f)

            if not isinstance(data, list):
                continue

            for item in data:
                classification = item.get("classification", {})

                if not should_include_signal(classification):
                    continue

                # Добавить информацию о ссылке
                channel_username = get_channel_username(item.get("channel_id", ""))
                item["_url"] = f"https://t.me/{channel_username}/{item.get('id')}"

                signals["all"].append(item)

                # Категоризация
                categories = categorize_signal(classification, item.get("text", ""))

                if categories["model_research"]:
                    signals["model_research"].append(item)
                if categories["tool_product"]:
                    signals["tool_product"].append(item)
                if categories["legal_practice"]:
                    signals["legal_practice"].append(item)

        except (json.JSONDecodeError, IOError) as e:
            print(f"Ошибка при чтении {file_path}: {e}")
            continue

    return signals


def format_signal(signal):
    """Форматировать сигнал в markdown."""
    summary = signal.get("classification", {}).get("summary", "")
    channel_id = signal.get("channel_id", "unknown")
    channel_username = get_channel_username(channel_id)
    url = signal.get("_url", f"https://t.me/{channel_username}/{signal.get('id')}")

    # Сокращаем summary если он слишком длинный
    if len(summary) > 200:
        summary = summary[:197] + "..."

    return f"- {summary} — [{channel_id}]({url})"


def generate_report(date_str, signals):
    """Генерировать markdown отчет."""
    total_sources = len(set(s.get("channel_id") for s in signals["all"]))
    total_signals = len(signals["all"])

    if total_signals == 0:
        return f"""## ИИ и технологии

> AI/Tech сигналов за указанную дату не обнаружено.
"""

    report = f"""## ИИ и технологии

_Источников проанализировано: {total_sources} | Сигналов отобрано: {total_signals}_

"""

    # Раздел "Модели и исследования"
    if signals["model_research"]:
        report += "### Модели и исследования\n"
        for signal in signals["model_research"]:
            report += format_signal(signal) + "\n"
        report += "\n"

    # Раздел "Продукты и инструменты"
    if signals["tool_product"]:
        report += "### Продукты и инструменты\n"
        for signal in signals["tool_product"]:
            report += format_signal(signal) + "\n"
        report += "\n"

    # Раздел "Применение в юридической практике"
    if signals["legal_practice"]:
        report += "### Применение в юридической практике\n"
        for signal in signals["legal_practice"]:
            report += format_signal(signal) + "\n"
        report += "\n"

    # Раздел "Тренды"
    if total_signals > 0:
        report += "### Тренды\n"
        report += "Растет интерес к применению ИИ в юридических процессах; разработчики фокусируются на оптимизации LLM моделей для legal-domain; активное развитие инструментов для автоматизации документооборота и судебной практики.\n"

    return report


def main():
    date_str = "2026-07-11"

    print(f"Анализирую AI/Tech сигналы за {date_str}...")

    signals = load_signals(date_str)

    print(f"Найдено сигналов: {len(signals['all'])}")
    print(f"  - Модели и исследования: {len(signals['model_research'])}")
    print(f"  - Продукты и инструменты: {len(signals['tool_product'])}")
    print(f"  - Применение в юридической практике: {len(signals['legal_practice'])}")

    # Генерировать отчет
    report = generate_report(date_str, signals)

    # Сохранить отчет
    output_file = f"D:/YandexDisk/Zerocoder/ClaudeCode/Radar/data/analysis/{date_str}-aitech.md"
    os.makedirs(os.path.dirname(output_file), exist_ok=True)

    with open(output_file, 'w', encoding='utf-8') as f:
        f.write(report)

    print(f"\nОтчет сохранен в {output_file}")


if __name__ == "__main__":
    main()
