"""QuotaFrame startup-size tests.

Constructing a frame needs a wx.App — conftest's shared `wx_app`, never a
local one: a same-named module fixture is a *distinct* fixture and would
build a second app in the process. The frame is never Show()n, so nothing
appears on screen. The expected size is asserted against literals
rather than the module's own constant — importing the constant would make
the assertion agree with any value frame.py happens to hold.
"""

import pytest

from claude_usage.ui.app.frame import QuotaFrame
from claude_usage.ui.app.presenter import BarView, QuotaView

# The window is a glanceable side panel, not a document window: it opens
# narrow enough to park beside real work.
EXPECTED_SIZE = (377, 216)


def make_view(bars=3):
    return QuotaView(
        headline="66% used",
        age_text="as of 7m ago",
        stale=False,
        bars=tuple(
            BarView(
                label=f"Limit {index}",
                percent=10,
                used=10,
                severity="normal",
                active=index == 0,
                resets_text=None,
            )
            for index in range(bars)
        ),
        notices=("+50% weekly limits promo through Sep 13",),
        message=None,
        message_detail=None,
    )


@pytest.fixture
def frame(wx_app):
    frame = QuotaFrame(on_close=lambda: None, on_refresh=lambda: None)
    yield frame
    frame.Destroy()


def test_opens_at_the_narrow_default_size(frame):
    assert tuple(frame.GetSize()) == EXPECTED_SIZE


def test_rendering_a_view_never_widens_the_window(frame):
    # _fit_to_content grows height only; a view must not undo the narrow
    # opening width by pushing the window back out.
    frame.show_view(make_view())
    assert frame.GetSize().width == EXPECTED_SIZE[0]
