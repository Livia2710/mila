import pytest

from mila.services.safety import is_crisis, is_only_symbols, is_simple_greeting


@pytest.mark.parametrize(
    "message",
    ["QUERO MORRER", "não quero mais viver", "Queria desaparecer", "me cortar", "tirar a minha vida"],
)
def test_crisis_patterns_are_normalized(message):
    assert is_crisis(message)


@pytest.mark.parametrize("message", ["não aguento mais esperar", "a senha está bloqueada", "como faço login?"])
def test_ambiguous_or_normal_messages_do_not_trigger_crisis(message):
    assert not is_crisis(message)


@pytest.mark.parametrize("message", ["Oi!", "oii tudo bem?", "obrigada! 😊", "Bom dia"])
def test_simple_greetings_allow_punctuation_and_emoji(message):
    assert is_simple_greeting(message)


def test_messages_with_a_question_are_not_simple_greetings():
    assert not is_simple_greeting("Oi, como faço meu cadastro?")


def test_emoji_only_message_is_detected():
    assert is_only_symbols("😊🙏")

