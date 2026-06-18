import json

import pytest

import app


# ── Pure helpers ──────────────────────────────────────────────────────────────

def test_fmt_time_pads_and_formats():
    assert app.fmt_time(0) == "00:00"
    assert app.fmt_time(65) == "01:05"
    assert app.fmt_time(1199) == "19:59"


@pytest.mark.parametrize("text,expected", [
    ("hello world", 2),
    ("hello    world", 2),       # multiple consecutive spaces collapse to one word boundary
    ("  hello world  ", 2),      # leading/trailing whitespace ignored
    ("hello\tworld\nfoo", 3),    # tabs/newlines treated as whitespace
    ("", 0),
    ("   ", 0),
])
def test_count_words(text, expected):
    assert app.count_words(text) == expected


@pytest.mark.parametrize("usn,expected", [
    ("1CR21CS001", True),
    ("1cr21cs001", True),        # case-insensitive
    ("  1CR21CS001  ", True),    # surrounding whitespace stripped
    ("2CR21CS001", False),
    ("", False),
    ("1C R21CS001", False),
])
def test_is_valid_usn(usn, expected):
    assert app.is_valid_usn(usn) is expected


@pytest.mark.parametrize("words,expected_color", [
    (150, "#1a7f37"),
    (200, "#1a7f37"),
    (175, "#1a7f37"),
    (149, "#9a6700"),
    (130, "#9a6700"),
    (201, "#9a6700"),
    (220, "#9a6700"),
    (129, "#bc4c00"),
    (221, "#bc4c00"),
    (0, "#bc4c00"),
])
def test_word_count_color_bands(words, expected_color):
    assert app.word_count_color(words) == expected_color


# ── Storage layer (Supabase) ────────────────────────────────────────────────

def test_save_and_load_submissions_roundtrip(fake_supabase):
    app.save_submission("1cr21cs001", {"name": "Alice", "status": "started"})
    subs = app.load_submissions()
    assert subs == {"1CR21CS001": {"name": "Alice", "status": "started"}}


def test_save_submission_upserts_same_usn(fake_supabase):
    app.save_submission("1CR21CS001", {"status": "started"})
    app.save_submission("1cr21cs001", {"status": "completed", "total_score": 90})
    subs = app.load_submissions()
    assert len(subs) == 1
    assert subs["1CR21CS001"]["status"] == "completed"


def test_already_submitted(fake_supabase):
    assert app.already_submitted("1CR21CS001") is False
    app.save_submission("1CR21CS001", {"status": "started"})
    assert app.already_submitted("1cr21cs001") is True


def test_clear_all_submissions(fake_supabase):
    app.save_submission("1CR21CS001", {"status": "started"})
    app.save_submission("1CR21CS002", {"status": "started"})
    app.clear_all_submissions()
    assert app.load_submissions() == {}


def test_paste_enabled_defaults_false_when_unset(fake_supabase):
    assert app.paste_enabled() is False


def test_paste_enabled_reflects_saved_config(fake_supabase):
    app.save_config({"paste_enabled": True})
    assert app.paste_enabled() is True
    app.save_config({"paste_enabled": False})
    assert app.paste_enabled() is False


# ── grade_essay (mocked Groq, no real API calls) ────────────────────────────

class _FakeMessage:
    def __init__(self, content):
        self.content = content


class _FakeChoice:
    def __init__(self, content):
        self.message = _FakeMessage(content)


class _FakeCompletion:
    def __init__(self, content):
        self.choices = [_FakeChoice(content)]


class _FakeGroqClient:
    last_kwargs = None

    def __init__(self, api_key=None):
        self.chat = self
        self.completions = self

    def create(self, **kwargs):
        _FakeGroqClient.last_kwargs = kwargs
        payload = {
            "content_score": 28, "critical_thinking_score": 20,
            "organization_score": 18, "evidence_score": 4,
            "language_score": 18, "total_score": 88,
            "grade": "B", "grade_label": "Good",
            "strengths": "Clear writing.",
            "improvements": "More examples.",
            "overall_feedback": "Solid effort overall.",
        }
        return _FakeCompletion("```json\n" + json.dumps(payload) + "\n```")


@pytest.fixture
def fake_groq(monkeypatch):
    monkeypatch.setattr(app, "Groq", _FakeGroqClient)
    return _FakeGroqClient


def test_grade_essay_strips_markdown_fences_and_parses_json(fake_groq):
    result = app.grade_essay("Alice", "Some topic", "word " * 10)
    assert result["grade"] == "B"
    assert result["total_score"] == 88


def test_grade_essay_truncates_essay_to_200_words(fake_groq):
    long_essay = " ".join(f"word{i}" for i in range(500))
    app.grade_essay("Alice", "Some topic", long_essay)
    prompt = fake_groq.last_kwargs["messages"][0]["content"]
    assert "word199" in prompt
    assert "word200" not in prompt


def test_grade_essay_reports_actual_word_count_even_when_truncated(fake_groq):
    long_essay = " ".join(f"word{i}" for i in range(500))
    app.grade_essay("Alice", "Some topic", long_essay)
    prompt = fake_groq.last_kwargs["messages"][0]["content"]
    assert "Word count   : 500" in prompt


def test_grade_essay_embeds_assigned_topic_for_relevance_check(fake_groq):
    app.grade_essay("Alice", "Remote Work vs. Office Collaboration", "word " * 10)
    prompt = fake_groq.last_kwargs["messages"][0]["content"]
    assert "Remote Work vs. Office Collaboration" in prompt
