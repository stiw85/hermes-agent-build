"""Webhook ``headers.<Name>`` filter fields match header names case-insensitively."""

import pytest

from gateway.platforms.webhook_filters import WebhookRouteProcessor

_ROUTE = {"filters": [{"field": "headers.X-GitHub-Event", "equals": "push"}]}


@pytest.mark.parametrize("wire_name", ["X-GitHub-Event", "X-Github-Event", "x-github-event"])
def test_header_filter_matches_any_wire_casing(wire_name):
    processor = WebhookRouteProcessor()
    assert processor.route_filters_match(_ROUTE, {}, "push", {wire_name: "push"})
    assert not processor.route_filters_match(_ROUTE, {}, "push", {wire_name: "issues"})


def test_missing_header_filter_sees_a_differently_cased_header():
    processor = WebhookRouteProcessor()
    route = {"filters": [{"field": "headers.X-Hub-Signature", "missing": True}]}
    assert not processor.route_filters_match(route, {}, "push", {"x-hub-signature": "sha1=abc"})
    assert processor.route_filters_match(route, {}, "push", {"x-other": "1"})


def test_payload_fields_stay_case_sensitive():
    processor = WebhookRouteProcessor()
    route = {"filters": [{"field": "payload.Action", "equals": "opened"}]}
    assert processor.route_filters_match(route, {"Action": "opened"}, "x", {})
    assert not processor.route_filters_match(route, {"action": "opened"}, "x", {})
