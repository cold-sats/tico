from clients import hubtools
from clients.tico import APIError


class _Api:
    """The Assistant's snapshot refuses anyone else; the fleet check answers."""
    def __init__(self):
        self.calls = []

    def get(self, path, **query):
        self.calls.append(path)
        if path == "tico/fleet":
            raise APIError("forbidden", "This endpoint is available only to people and Assistant", 403)
        if path == "me":
            return {"actor": "human:ana"}
        if path == "fleet/check":
            return {"issues": []}
        raise AssertionError(path)


def test_the_fleet_for_anyone_but_the_assistant_is_the_fleet_check():
    api = _Api()
    assert hubtools.BY_NAME["hub_fleet"]["fn"](api, {}) == {"issues": []}
    assert api.calls[0] == "tico/fleet" and "fleet/check" in api.calls
