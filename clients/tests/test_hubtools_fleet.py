from clients import hubtools


class _Api:
    """One route answers `hub_health_check` for everyone: the server picks what the caller gets."""
    def __init__(self):
        self.calls = []

    def get(self, path, **query):
        self.calls.append(path)
        if path == "me":
            return {"actor": "human:ana"}
        if path == "health/issues":
            return {"issues": []}
        raise AssertionError(path)


def test_health_check_reads_the_one_health_route():
    api = _Api()
    assert hubtools.BY_NAME["hub_health_check"]["fn"](api, {}) == {"issues": []}
    assert "health/issues" in api.calls
