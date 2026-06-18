"""
Integration test fixtures using Testcontainers.

Requires Docker to be running. Tests skip gracefully if:
- Docker is not installed
- Docker daemon is not running
- testcontainers package is not installed

Run with: pytest tests/integration/ -v
"""

from __future__ import annotations

import contextlib
import os
import subprocess

import pytest


# Check Docker availability before importing testcontainers
def _docker_available() -> bool:
    """Check if Docker is available and running."""
    try:
        result = subprocess.run(
            ["docker", "info"],
            capture_output=True,
            timeout=5,
        )
        return result.returncode == 0
    except (subprocess.TimeoutExpired, FileNotFoundError):
        return False


DOCKER_AVAILABLE = _docker_available()
SKIP_REASON = "Docker not available - skipping integration tests"

# Conditional imports
if DOCKER_AVAILABLE:
    try:
        from testcontainers.kafka import KafkaContainer
        from testcontainers.localstack import LocalStackContainer
        TESTCONTAINERS_AVAILABLE = True
    except ImportError:
        TESTCONTAINERS_AVAILABLE = False
        SKIP_REASON = "testcontainers not installed - run: pip install streamforge-cli[integration]"
else:
    TESTCONTAINERS_AVAILABLE = False


requires_docker = pytest.mark.skipif(
    not DOCKER_AVAILABLE or not TESTCONTAINERS_AVAILABLE,
    reason=SKIP_REASON,
)


@pytest.fixture(scope="session")
def localstack_container():
    """
    Start LocalStack container for SQS testing.

    LocalStack provides a fully functional local AWS cloud stack.
    Services enabled: SQS
    """
    if not DOCKER_AVAILABLE or not TESTCONTAINERS_AVAILABLE:
        pytest.skip(SKIP_REASON)

    container = LocalStackContainer(image="localstack/localstack:3.0")
    container.with_services("sqs")
    container.start()

    yield container

    container.stop()


@pytest.fixture(scope="session")
def kafka_container():
    """
    Start Kafka container for Kafka connector testing.

    Uses Confluent's Kafka image with KRaft (no ZooKeeper required).
    """
    if not DOCKER_AVAILABLE or not TESTCONTAINERS_AVAILABLE:
        pytest.skip(SKIP_REASON)

    container = KafkaContainer(image="confluentinc/cp-kafka:7.5.0")
    container.start()

    yield container

    container.stop()


@pytest.fixture
def sqs_queue_url(localstack_container):
    """Create a test SQS queue and return its URL."""
    import boto3

    endpoint_url = localstack_container.get_url()
    client = boto3.client(
        "sqs",
        endpoint_url=endpoint_url,
        region_name="us-east-1",
        aws_access_key_id="test",
        aws_secret_access_key="test",
    )

    queue_name = f"test-queue-{os.getpid()}"
    response = client.create_queue(QueueName=queue_name)
    queue_url = response["QueueUrl"]

    yield queue_url

    # Cleanup
    with contextlib.suppress(Exception):
        client.delete_queue(QueueUrl=queue_url)


@pytest.fixture
def kafka_bootstrap_servers(kafka_container) -> str:
    """Return Kafka bootstrap servers connection string."""
    return kafka_container.get_bootstrap_server()


@pytest.fixture
def kafka_topic(kafka_container) -> str:
    """Create a test Kafka topic and return its name."""
    from kafka.admin import KafkaAdminClient, NewTopic

    topic_name = f"test-topic-{os.getpid()}"
    bootstrap = kafka_container.get_bootstrap_server()

    admin = KafkaAdminClient(bootstrap_servers=bootstrap)
    topic = NewTopic(name=topic_name, num_partitions=2, replication_factor=1)

    # Topic may already exist
    with contextlib.suppress(Exception):
        admin.create_topics([topic])

    admin.close()

    return topic_name
