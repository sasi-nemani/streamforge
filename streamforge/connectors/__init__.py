"""
Stream source connectors.

Every source — files, Redis Streams, Kafka, SQS — implements StreamConnector.
Nothing above this package knows what the source is.
"""
from .base import ConnectorError, StreamConnector
from .file import FileConnector
from .mock import DriftPhase, MockConnector

__all__ = [
    "StreamConnector",
    "ConnectorError",
    "FileConnector",
    "MockConnector",
    "DriftPhase",
]
