from bot.telegram_bot import BotRuler


def test_long_telegram_report_is_split_without_losing_blocks():
    text = "\n\n".join(["a" * 1500, "b" * 1500, "c" * 1500])
    chunks = BotRuler._split_message(text, limit=3100)
    assert len(chunks) == 2
    assert all(len(chunk) <= 3100 for chunk in chunks)
    assert "".join(chunks).replace("\n", "") == text.replace("\n", "")
