"""Pure-logic helpers: prompt assembly, response text extraction, configuration.

`_extract_code` takes an anthropic Message, but only ever reads `.content` and
each block's `.type` / `.text`. The stubs below are plain value objects standing
in for that shape -- no HTTP, no client, no network. A real fake Anthropic client
(and therefore the live fix_code path) is Phase 2 by the Phase 1 scope rules.
"""

from types import SimpleNamespace

import pytest

from src.core.fixer import DEFAULT_MODEL, MAX_TOKENS, SYSTEM_PROMPT, CodeFixer

pytestmark = pytest.mark.unit


def text_block(text):
    return SimpleNamespace(type="text", text=text)


def thinking_block(text):
    return SimpleNamespace(type="thinking", text=text)


def message(*blocks, stop_reason="end_turn"):
    return SimpleNamespace(content=list(blocks), stop_reason=stop_reason)


@pytest.fixture
def fixer():
    return CodeFixer(demo_mode=True)


# --- _build_prompt --------------------------------------------------------


def test_prompt_contains_the_code_and_the_change(fixer):
    prompt = fixer._build_prompt("x = 1", "Charge was removed.", "")

    assert "x = 1" in prompt
    assert "Charge was removed." in prompt
    assert "<breaking_change>" in prompt
    assert "<code>" in prompt


def test_prompt_includes_the_file_path_when_given(fixer):
    prompt = fixer._build_prompt("x = 1", "c", "src/payments/charge.py")

    assert "This code lives in: src/payments/charge.py" in prompt


def test_prompt_omits_the_location_line_when_path_is_empty(fixer):
    prompt = fixer._build_prompt("x = 1", "c", "")

    assert "This code lives in" not in prompt


# --- _extract_code --------------------------------------------------------


def test_extract_returns_the_text_block(fixer):
    assert fixer._extract_code(message(text_block("x = 1"))) == "x = 1"


def test_extract_skips_thinking_blocks(fixer):
    reply = message(thinking_block("Let me consider..."), text_block("x = 1"))

    assert fixer._extract_code(reply) == "x = 1"


def test_extract_joins_multiple_text_blocks(fixer):
    reply = message(text_block("line one"), text_block("line two"))

    assert fixer._extract_code(reply) == "line one\nline two"


def test_extract_strips_surrounding_whitespace(fixer):
    assert fixer._extract_code(message(text_block("\n\n  x = 1  \n\n"))) == "x = 1"


def test_extract_removes_markdown_fences(fixer):
    reply = message(text_block("```python\nx = 1\n```"))

    assert fixer._extract_code(reply) == "x = 1"


def test_extract_removes_fences_without_a_language_label(fixer):
    assert fixer._extract_code(message(text_block("```\nx = 1\n```"))) == "x = 1"


def test_extract_handles_an_unclosed_fence(fixer):
    """Characterization: only the opening fence is dropped when there is no closer."""
    assert fixer._extract_code(message(text_block("```python\nx = 1"))) == "x = 1"


def test_extract_returns_empty_string_for_no_text_blocks(fixer):
    assert fixer._extract_code(message(thinking_block("only thinking"))) == ""


# --- configuration --------------------------------------------------------


def test_an_explicit_api_key_leaves_demo_mode_off():
    """Constructing a client makes no request; nothing here touches the network."""
    built = CodeFixer(api_key="sk-ant-not-a-real-key")

    assert built.demo_mode is False
    assert built.demo_reason is None
    assert built._client is not None


def test_an_explicit_key_is_stored(monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)

    assert CodeFixer(api_key="sk-ant-xyz").api_key == "sk-ant-xyz"


def test_an_environment_key_is_picked_up(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-from-env")

    built = CodeFixer()

    assert built.api_key == "sk-ant-from-env"
    assert built.demo_mode is False


def test_demo_mode_wins_even_when_a_key_is_present():
    built = CodeFixer(api_key="sk-ant-xyz", demo_mode=True)

    assert built.demo_mode is True
    assert built._client is None
    assert built.demo_reason == "demo_mode=True was requested"


def test_the_model_defaults_and_can_be_overridden():
    assert CodeFixer(demo_mode=True).model == DEFAULT_MODEL
    assert CodeFixer(demo_mode=True, model="claude-opus-5").model == "claude-opus-5"


def test_module_constants_are_what_the_request_layer_expects():
    assert DEFAULT_MODEL == "claude-sonnet-5"
    assert MAX_TOKENS == 16000
    assert "Return ONLY the updated code" in SYSTEM_PROMPT
