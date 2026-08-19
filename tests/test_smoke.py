from coldstart import SCHEMA_VERSION


def test_schema_version_is_an_int():
    assert isinstance(SCHEMA_VERSION, int)
