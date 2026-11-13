"""PitResolutionError names the last failing date so the operator knows which --start avoids the gap (#190)."""
from helpers.point_in_time import PitResolutionError


def test_message_names_last_failing_date():
    err = PitResolutionError([("ATGE", "2009-06-09", []), ("ATGE", "2012-09-05", []), ("XYZ", "2010-01-04", ["XYZ-201001"])])
    msg = str(err)
    assert "falls on or before 2012-09-05" in msg
    assert "a later --start avoids them" in msg
    assert "ATGE @ 2009-06-09" in msg  # existing per-ticker listing is unchanged
