"""The forced dark palette must stay readable: WCAG contrast, not eyeballing.

theme.py is plain RGB data (no wx) precisely so these checks can run headless.
"""
from claude_usage.ui.app import theme


def _linear(channel: int) -> float:
    c = channel / 255
    return c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4


def _luminance(rgb: tuple[int, int, int]) -> float:
    r, g, b = rgb
    return 0.2126 * _linear(r) + 0.7152 * _linear(g) + 0.0722 * _linear(b)


def _contrast(a: tuple[int, int, int], b: tuple[int, int, int]) -> float:
    lighter, darker = sorted((_luminance(a), _luminance(b)), reverse=True)
    return (lighter + 0.05) / (darker + 0.05)


def _all_colors():
    return [
        theme.BACKGROUND,
        theme.TEXT_PRIMARY,
        theme.TEXT_SECONDARY,
        theme.TRACK,
        theme.STALE_FILL,
        *theme.SEVERITY_FILLS.values(),
    ]


def test_colors_are_rgb_triples():
    for color in _all_colors():
        assert len(color) == 3
        assert all(isinstance(c, int) and 0 <= c <= 255 for c in color)


def test_background_is_dark():
    assert _luminance(theme.BACKGROUND) < 0.1


def test_primary_text_has_aaa_contrast_on_background():
    assert _contrast(theme.TEXT_PRIMARY, theme.BACKGROUND) >= 7.0


def test_secondary_text_has_aa_contrast_on_background():
    assert _contrast(theme.TEXT_SECONDARY, theme.BACKGROUND) >= 4.5


def test_severity_fills_cover_all_presenter_severities():
    assert set(theme.SEVERITY_FILLS) == {"normal", "warning", "critical"}


def test_theme_is_pure_data_without_wx():
    import inspect

    assert "import wx" not in inspect.getsource(theme)
