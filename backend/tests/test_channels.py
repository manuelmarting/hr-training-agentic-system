from app.channels import TELEGRAM, VOICE, RenderIntent, render


def test_telegram_keeps_markdown_and_buttons():
    intent = RenderIntent(text="**Bold** question?", options=["A", "B"])
    rendered = render(intent, TELEGRAM)
    assert rendered.text == "**Bold** question?"
    assert rendered.buttons == ["A", "B"]


def test_telegram_truncates_at_4096_chars():
    intent = RenderIntent(text="x" * 5000)
    rendered = render(intent, TELEGRAM)
    assert len(rendered.text) == 4096
    assert rendered.truncated is True


def test_voice_strips_markdown():
    intent = RenderIntent(text="Check the **manual** and `SKU-123` before picking.")
    rendered = render(intent, VOICE)
    assert "**" not in rendered.text
    assert "`" not in rendered.text
    assert "manual" in rendered.text
    assert "SKU-123" in rendered.text


def test_voice_caps_at_two_sentences():
    intent = RenderIntent(text="One. Two. Three. Four.")
    rendered = render(intent, VOICE)
    assert rendered.text == "One. Two."


def test_voice_has_no_inline_buttons():
    intent = RenderIntent(text="Pick one.", options=["A", "B"])
    rendered = render(intent, VOICE)
    assert rendered.buttons is None


def test_voice_digit_confirmation_present_when_required():
    intent = RenderIntent(text="Confirm.", options=["Yes", "No"], requires_confirmation=True)
    rendered = render(intent, VOICE)
    assert "1 for Yes" in rendered.text
    assert "2 for No" in rendered.text


def test_telegram_no_digit_confirmation():
    intent = RenderIntent(text="Confirm.", options=["Yes", "No"], requires_confirmation=True)
    rendered = render(intent, TELEGRAM)
    assert "1 for" not in rendered.text
