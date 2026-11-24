"""Совместная примерка разрешена только внутри одного готового набора."""
import pytest

from bot.jewelry.models import Category, JewelryItem, PHOTO_INSTRUCTIONS
from bot.jewelry.selection import (
    current_photo_step, expand_selection, photo_instructions, photo_steps,
    validate_components, validate_selection,
)


def item(category, item_id=None):
    return JewelryItem(item_id or category.value, category.value, category, "test.png")


def jewelry_set(*categories):
    return JewelryItem(
        "set", "Набор", Category.SET, "set.png",
        components=[item(category, f"part-{i}") for i, category in enumerate(categories)],
    )


@pytest.mark.parametrize("category", [category for category in Category if category != Category.SET])
def test_individual_jewelry_is_still_allowed(category):
    validate_selection([item(category)])
    assert photo_instructions([item(category)]) == PHOTO_INSTRUCTIONS[category]


@pytest.mark.parametrize("categories", [
    (Category.EARRINGS, Category.PENDANT),
    (Category.EARRINGS, Category.DIADEM),
    (Category.EARRINGS, Category.PENDANT, Category.DIADEM),
    (Category.PENDANT, Category.BEADS),
    (Category.DIADEM, Category.HAIRPIN),
])
def test_front_categories_can_be_tried_together_inside_a_set(categories):
    selected = jewelry_set(*categories)
    validate_selection([selected])
    assert expand_selection([selected]) == selected.components


@pytest.mark.parametrize("categories", [
    (Category.EARRINGS, Category.PENDANT),
    (Category.EARRINGS, Category.DIADEM),
    (Category.RING, Category.BRACELET),
])
def test_independent_products_cannot_be_combined(categories):
    with pytest.raises(ValueError, match="только для готовых наборов"):
        validate_selection([item(category) for category in categories])


@pytest.mark.parametrize("category", [Category.KAFFY, Category.RING, Category.BRACELET])
def test_set_rejects_components_requiring_another_view(category):
    with pytest.raises(ValueError):
        validate_selection([jewelry_set(Category.EARRINGS, category)])


def test_empty_selection_is_rejected():
    with pytest.raises(ValueError):
        validate_selection([])


def test_set_cannot_be_combined_with_another_product_or_set():
    selected = jewelry_set(Category.EARRINGS, Category.DIADEM)
    for extra in [item(Category.PENDANT), jewelry_set(Category.PENDANT, Category.BROOCH)]:
        with pytest.raises(ValueError, match="только для готовых наборов"):
            validate_selection([selected, extra])


def test_set_cannot_have_two_pieces_of_one_category():
    with pytest.raises(ValueError):
        validate_selection([jewelry_set(Category.EARRINGS, Category.EARRINGS)])


def test_set_cannot_have_duplicate_component_ids():
    selected = jewelry_set(Category.EARRINGS, Category.DIADEM)
    selected.components[1].id = selected.components[0].id
    with pytest.raises(ValueError):
        validate_selection([selected])


def test_set_without_components_cannot_be_rendered_as_one_diadem():
    with pytest.raises(ValueError):
        validate_selection([item(Category.SET)])


def test_nested_sets_are_rejected():
    selected = jewelry_set(Category.EARRINGS, Category.DIADEM)
    selected.components[0] = jewelry_set(Category.EARRINGS, Category.PENDANT)
    with pytest.raises(ValueError):
        validate_selection([selected])


def test_set_photo_instructions_come_from_actual_components():
    selected = jewelry_set(Category.EARRINGS, Category.DIADEM)
    instructions = photo_instructions([selected])
    assert PHOTO_INSTRUCTIONS[Category.EARRINGS] in instructions
    assert PHOTO_INSTRUCTIONS[Category.DIADEM] in instructions


@pytest.mark.parametrize("side,ear,position,other", [
    ("right", "правое", "справа", "левое"),
    ("left", "левое", "слева", "правое"),
])
def test_kaffy_instructions_identify_the_rendered_ear_in_the_sent_photo(side, ear, position, other):
    selected = item(Category.KAFFY)
    selected.kaffy_side = side
    instructions = photo_instructions([selected])
    assert f"{ear} по кадру ухо" in instructions
    assert f"{position} на отправляемом фото" in instructions
    assert other not in instructions
    assert "Уберите волосы" in instructions
    assert "три четверти" in instructions
    assert "не чистый профиль" in instructions


def test_sequential_set_requests_the_ear_of_its_kaffy_component():
    selected = jewelry_set(Category.EARRINGS, Category.KAFFY)
    selected.tryon_mode = "sequential"
    selected.components[1].kaffy_side = "right"
    assert "правое по кадру ухо" not in photo_instructions([selected])
    second = photo_instructions([selected], 1)
    assert "Фото 2 из 2" in second
    assert "правое по кадру ухо" in second
    assert "справа на отправляемом фото" in second


def sequential_set():
    selected = jewelry_set(Category.EARRINGS, Category.BRACELET)
    selected.tryon_mode = "sequential"
    return selected


def test_sequential_set_validates_and_renders_each_photo_separately():
    selected = sequential_set()
    validate_selection([selected])
    assert photo_steps(selected) == [[selected.components[0]], [selected.components[1]]]
    assert current_photo_step([selected]) == [selected.components[0]]
    assert current_photo_step([selected], 1) == [selected.components[1]]
    with pytest.raises(ValueError):
        validate_components([selected])
    with pytest.raises(ValueError):
        validate_components(selected.components)


def test_combined_set_still_uses_one_photo():
    selected = jewelry_set(Category.EARRINGS, Category.PENDANT)
    assert photo_steps(selected) == [selected.components]


def test_sequential_instructions_only_request_current_photo():
    selected = sequential_set()
    first = photo_instructions([selected])
    second = photo_instructions([selected], 1)
    assert "Фото 1 из 2" in first
    assert PHOTO_INSTRUCTIONS[Category.EARRINGS] in first
    assert PHOTO_INSTRUCTIONS[Category.BRACELET] not in first
    assert "Фото 2 из 2" in second
    assert PHOTO_INSTRUCTIONS[Category.BRACELET] in second
    assert PHOTO_INSTRUCTIONS[Category.EARRINGS] not in second


@pytest.mark.parametrize("step", [-1, 2, "1", None, True])
def test_invalid_sequential_step_is_rejected(step):
    with pytest.raises(ValueError, match="Шаг примерки устарел"):
        current_photo_step([sequential_set()], step)


@pytest.mark.parametrize("invalid", ["same-id", "same-category", "nested-set"])
def test_sequential_mode_does_not_bypass_component_validation(invalid):
    selected = sequential_set()
    if invalid == "same-id":
        selected.components[1].id = selected.components[0].id
    elif invalid == "same-category":
        selected.components[1].category = selected.components[0].category
    else:
        selected.components[1] = jewelry_set(Category.EARRINGS, Category.PENDANT)
    with pytest.raises(ValueError):
        validate_selection([selected])


def test_sequential_mode_is_only_for_a_declared_set():
    selected = item(Category.BRACELET)
    selected.tryon_mode = "sequential"
    with pytest.raises(ValueError):
        validate_selection([selected])


@pytest.mark.parametrize("style", ["bun", "side"])
def test_side_hairpin_has_its_own_view_and_cannot_share_a_front_photo(style):
    selected = item(Category.HAIRPIN)
    selected.hairpin_style = style
    instruction = photo_instructions([selected])
    assert "пуч" in instruction if style == "bun" else "висок" in instruction
    assert "три четверти" in instruction or "3/4" in instruction
    combined = jewelry_set(Category.EARRINGS, Category.HAIRPIN)
    combined.components[1].hairpin_style = style
    with pytest.raises(ValueError):
        validate_selection([combined])
    combined.tryon_mode = "sequential"
    validate_selection([combined])
