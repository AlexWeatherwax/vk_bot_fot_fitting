"""Commands use whole messages; spelling tolerance never grants consent."""
import pytest

from bot.commands import (CANCEL_WORDS, CATALOG_WORDS, CATEGORY_COMMANDS,
                          RESET_WORDS, START_WORDS, command_key)


ALL_COMMANDS = sorted(set(START_WORDS) | set(CATALOG_WORDS) | set(CATEGORY_COMMANDS)
                      | CANCEL_WORDS | RESET_WORDS
                      | {'добавить', 'убрать', 'примерить', 'позови мастера',
                         'согласие', 'условия', 'конфиденциальность', 'отозвать согласие'})


@pytest.mark.parametrize('command', ALL_COMMANDS)
def test_all_commands_accept_case_spacing_and_decoration(command):
    for variant in (command.upper(), command.title(), '  «'+command.upper()+'!»  ',
                    '/'+command.upper(), '\u00a0'+command.replace(' ', '\n\t')+'?'):
        assert command_key(variant) == command


@pytest.mark.parametrize('text', ['КАТАЛОГ', 'КатАлОг!', 'католог', 'каталок',
                                 'Каталлог', 'КАТАЛОГИ', 'Покажи каталог!',
                                 '/CATALOG', 'ＣＡＴＡＬＯＧ', 'RFnFKJu', 'меню'])
def test_catalog_variants(text):
    assert command_key(text) == 'каталог'


@pytest.mark.parametrize('text,expected', [('CTHMUB', 'серьги'), (',ECS', 'бусы'),
                                        ('JNVТYF'.replace('Т', 'T'), 'отмена'),
                                        ('  GJPJDB   VFСNTHF  '.replace('С', 'C'), 'позови мастера')])
def test_wrong_layout_only_recovers_known_commands(text, expected):
    assert command_key(text) == expected


@pytest.mark.parametrize('text', ['Серьги Луна', 'Кулон Каталог', 'Привет Луна',
                                 'Позови мастера завтра', 'не согласен',
                                 'не отозвать согласие', 'хочу каталог и кольцо'])
def test_product_names_and_longer_phrases_are_not_commands(text):
    assert command_key(text) not in ALL_COMMANDS
