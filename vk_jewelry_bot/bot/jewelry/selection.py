"""Совместимость украшений и шаги примерки готового набора."""
from .models import Category, JewelryItem, item_photo_instruction


FRONT_CATEGORIES = frozenset({
    Category.EARRINGS, Category.PENDANT, Category.BEADS,
    Category.DIADEM, Category.HAIRPIN, Category.BROOCH,
})

def expand_selection(items: list[JewelryItem]) -> list[JewelryItem]:
    """Раскрывает наборы в отдельные изделия с собственными точками крепления."""
    expanded = []
    for item in items:
        if item.category == Category.SET:
            if len(item.components) < 2:
                raise ValueError(f"У набора «{item.name}» ещё не подготовлены изделия для примерки.")
            if any(part.category == Category.SET for part in item.components):
                raise ValueError("В наборе должны быть отдельные украшения, а не другие наборы.")
            expanded.extend(item.components)
        else:
            expanded.append(item)
    return expanded


def validate_selection(items: list[JewelryItem]) -> None:
    if not items:
        raise ValueError("Выберите украшение или набор.")
    if len(items) != 1:
        raise ValueError("Совместная примерка доступна только для готовых наборов. Напишите «наборы» и выберите один комплект.")
    photo_steps(items[0])


def _validate_unique_components(items: list[JewelryItem]) -> None:
    ids = set()
    slots = {}
    for item in items:
        if item.id in ids:
            raise ValueError(f"«{item.name}» уже есть в примерке, в том числе в составе набора.")
        ids.add(item.id)
        if item.category in slots:
            raise ValueError(
                f"«{slots[item.category].name}» и «{item.name}» относятся к одной категории. "
                "Для набора нужны изделия разных категорий."
            )
        slots[item.category] = item


def photo_steps(item: JewelryItem) -> list[list[JewelryItem]]:
    """Возвращает изделия для каждого фото, не смешивая разные снимки в overlay."""
    expanded = expand_selection([item])
    mode = item.tryon_mode
    if mode not in {"combined", "sequential"} or (mode == "sequential" and item.category != Category.SET):
        raise ValueError("Режим примерки украшения не поддерживается. Выберите его заново.")
    _validate_unique_components(expanded)
    steps = [[part] for part in expanded] if mode == "sequential" else [expanded]
    for step in steps:
        validate_components(step)
    return steps


def current_photo_step(items: list[JewelryItem], step_index: int = 0) -> list[JewelryItem]:
    validate_selection(items)
    steps = photo_steps(items[0])
    if type(step_index) is not int or not 0 <= step_index < len(steps):
        raise ValueError("Шаг примерки устарел. Выберите украшение или набор заново.")
    return steps[step_index]


def validate_components(items: list[JewelryItem]) -> None:
    """Проверяет отдельные изделия, передаваемые во внутренний конвейер набора."""
    expanded = expand_selection(items)
    if not expanded:
        raise ValueError("Выберите хотя бы одно украшение.")
    if len(expanded) > 1 and any(
        item.category not in FRONT_CATEGORIES
        or (item.category == Category.HAIRPIN and item.hairpin_style in {"bun", "side"})
        for item in expanded
    ):
        raise ValueError(
            "На одном фото можно примерить украшения для фото в фас: серьги, кулон или бусы, "
            "диадему, заколку над лбом или брошь. Каффы, кольца, браслеты и шпильки "
            "для бокового пучка или виска требуют другого фото."
        )
    _validate_unique_components(expanded)


def photo_instructions(items: list[JewelryItem], step_index: int = 0) -> str:
    expanded = current_photo_step(items, step_index)
    steps = photo_steps(items[0])
    instructions = list(dict.fromkeys(item_photo_instruction(item) for item in expanded))
    if len(steps) > 1:
        names = " + ".join(f"«{item.name}»" for item in expanded)
        return f"Фото {step_index + 1} из {len(steps)} — {names}.\n" + "\n".join(instructions)
    if len(expanded) == 1:
        return instructions[0]
    return "Пришлите одно общее фото в фас для всех выбранных украшений.\n" + "\n".join(instructions)
