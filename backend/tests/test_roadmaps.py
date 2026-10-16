"""Roadmap privacy boundaries and the existing parent/child flow."""

from backend import hubdb as H
from backend.tests.test_tasks_board import api, get, post


def test_engineering_children_drive_approved_roadmap_and_reopen(api):
    roadmap = post(api, 'tasks', {'owner': 'cpo', 'title': 'Improve exports', 'body': 'Research exports.',
                                 'type': 'Product roadmap', 'step': 'Approved'})
    child = post(api, 'tasks', {'owner': 'ops', 'title': 'Build exports', 'body': 'Implement exports.',
                               'type': 'Engineering', 'relations': [{'task': roadmap['id'], 'kind': 'parent'}]})
    assert get(api, 'tasks/' + roadmap['id'])['task']['step']['name'] == 'Building'
    child = post(api, 'tasks/' + child['id'], {'version': child['version'], 'status': 'done'})
    assert get(api, 'tasks/' + roadmap['id'])['task']['step']['name'] == 'Shipped'
    post(api, 'tasks/' + child['id'], {'version': child['version'], 'status': 'open'})
    assert get(api, 'tasks/' + roadmap['id'])['task']['step']['name'] == 'Building'
