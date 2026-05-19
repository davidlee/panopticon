from panopticon import schema


def test_schema_version_is_one():
    assert schema.SCHEMA_VERSION == 1
