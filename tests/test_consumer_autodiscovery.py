"""
tests/test_consumer_autodiscovery.py — Phase 1: Tests for consumer auto-discovery from Kafka.

TDD cycle: these tests are written FIRST and must FAIL before implementation.
All tests mock the kafka-python AdminClient — no live Kafka required.
"""
from unittest.mock import MagicMock, patch

from streamforge.consumer_registry import discover_consumers_from_kafka


# ── Helpers ────────────────────────────────────────────────────────────────────

def _make_member(topic: str) -> MagicMock:
    """Build a mock Kafka group member assigned to a given topic."""
    tp = MagicMock()
    tp.topic = topic

    assignment = MagicMock()
    assignment.assignment = [tp]

    member = MagicMock()
    member.member_assignment = assignment
    return member


def _make_group_description(group_id: str, members: list) -> MagicMock:
    desc = MagicMock()
    desc.group_id = group_id
    desc.members = members
    return desc


# ── Tests ──────────────────────────────────────────────────────────────────────

def test_discover_consumers_returns_list_of_consumer_groups():
    """discover_consumers_from_kafka returns a list of dicts with group_id, member_count, lag, team."""
    member = _make_member("payments.stream_v1")
    group_desc = _make_group_description("fraud-detector", [member])

    with patch("streamforge.consumer_registry.KafkaAdminClient") as MockAdmin:
        instance = MockAdmin.return_value
        instance.list_consumer_groups.return_value = [("fraud-detector", "Stable")]
        instance.describe_consumer_groups.return_value = [group_desc]

        result = discover_consumers_from_kafka("payments.stream_v1", "localhost:9092")

    assert isinstance(result, list), "Result must be a list"
    assert len(result) == 1, "Expected one consumer group"
    group = result[0]
    assert "group_id" in group, "Result dict must have 'group_id'"
    assert "member_count" in group, "Result dict must have 'member_count'"
    assert "lag" in group, "Result dict must have 'lag'"
    assert "team" in group, "Result dict must have 'team'"


def test_discover_consumers_group_id_matches():
    """Returned consumer group must have the correct group_id."""
    member = _make_member("payments.stream_v1")
    group_desc = _make_group_description("fraud-detector", [member])

    with patch("streamforge.consumer_registry.KafkaAdminClient") as MockAdmin:
        instance = MockAdmin.return_value
        instance.list_consumer_groups.return_value = [("fraud-detector", "Stable")]
        instance.describe_consumer_groups.return_value = [group_desc]

        result = discover_consumers_from_kafka("payments.stream_v1", "localhost:9092")

    assert result[0]["group_id"] == "fraud-detector"


def test_discover_consumers_member_count_is_correct():
    """member_count must equal the number of members subscribed to the topic."""
    member1 = _make_member("payments.stream_v1")
    member2 = _make_member("payments.stream_v1")
    group_desc = _make_group_description("analytics-group", [member1, member2])

    with patch("streamforge.consumer_registry.KafkaAdminClient") as MockAdmin:
        instance = MockAdmin.return_value
        instance.list_consumer_groups.return_value = [("analytics-group", "Stable")]
        instance.describe_consumer_groups.return_value = [group_desc]

        result = discover_consumers_from_kafka("payments.stream_v1", "localhost:9092")

    assert len(result) == 1
    assert result[0]["member_count"] == 2


def test_discover_consumers_filters_by_topic():
    """Only consumer groups subscribed to the given topic are returned."""
    member_on_topic = _make_member("payments.stream_v1")
    member_other_topic = _make_member("flights.stream")

    # Group 1: subscribed to the target topic
    group_desc_1 = _make_group_description("fraud-detector", [member_on_topic])
    # Group 2: subscribed to a DIFFERENT topic — must be excluded
    group_desc_2 = _make_group_description("flight-monitor", [member_other_topic])

    with patch("streamforge.consumer_registry.KafkaAdminClient") as MockAdmin:
        instance = MockAdmin.return_value
        instance.list_consumer_groups.return_value = [
            ("fraud-detector", "Stable"),
            ("flight-monitor", "Stable"),
        ]
        instance.describe_consumer_groups.side_effect = [
            [group_desc_1],
            [group_desc_2],
        ]

        result = discover_consumers_from_kafka("payments.stream_v1", "localhost:9092")

    assert len(result) == 1, "Only the group subscribed to the target topic should be returned"
    assert result[0]["group_id"] == "fraud-detector"


def test_discover_consumers_handles_kafka_unavailable():
    """When Kafka is unreachable, returns empty list (no exception raised)."""
    with patch("streamforge.consumer_registry.KafkaAdminClient") as MockAdmin:
        MockAdmin.side_effect = Exception("Connection refused: localhost:9092")

        result = discover_consumers_from_kafka("payments.stream_v1", "localhost:9092")

    assert result == [], "Must return empty list when Kafka is unavailable"


def test_discover_consumers_handles_empty_cluster():
    """When no consumer groups exist, returns empty list."""
    with patch("streamforge.consumer_registry.KafkaAdminClient") as MockAdmin:
        instance = MockAdmin.return_value
        instance.list_consumer_groups.return_value = []

        result = discover_consumers_from_kafka("payments.stream_v1", "localhost:9092")

    assert result == [], "Must return empty list when no consumer groups exist"


def test_discover_consumers_skips_group_on_describe_error():
    """If describe_consumer_groups raises for one group, it is skipped (others processed)."""
    member = _make_member("payments.stream_v1")
    group_desc_ok = _make_group_description("good-group", [member])

    with patch("streamforge.consumer_registry.KafkaAdminClient") as MockAdmin:
        instance = MockAdmin.return_value
        instance.list_consumer_groups.return_value = [
            ("bad-group", "Stable"),
            ("good-group", "Stable"),
        ]
        instance.describe_consumer_groups.side_effect = [
            Exception("describe failed for bad-group"),
            [group_desc_ok],
        ]

        result = discover_consumers_from_kafka("payments.stream_v1", "localhost:9092")

    assert len(result) == 1
    assert result[0]["group_id"] == "good-group"
