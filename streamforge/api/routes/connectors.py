"""Connectors endpoint — list available source connectors."""
from __future__ import annotations

from fastapi import APIRouter

from streamforge.connectors import supported_extensions

router = APIRouter(prefix="/api/connectors", tags=["connectors"])


@router.get("")
def list_connectors() -> list[dict]:
    """List available connectors and their capabilities."""
    return [
        {
            "type": "kafka",
            "name": "Apache Kafka",
            "description": "Real-time event streaming",
            "available": True,
            "configured": True,
            "formats": ["json", "avro", "protobuf"],
        },
        {
            "type": "file",
            "name": "File System",
            "description": "Local or mounted directories",
            "available": True,
            "configured": True,
            "formats": list(supported_extensions()),
        },
        {
            "type": "kinesis",
            "name": "AWS Kinesis",
            "description": "AWS managed streaming",
            "available": True,
            "configured": False,
            "formats": ["json"],
        },
        {
            "type": "pubsub",
            "name": "Google Pub/Sub",
            "description": "GCP managed messaging",
            "available": True,
            "configured": False,
            "formats": ["json", "avro"],
        },
        {
            "type": "sftp",
            "name": "SFTP",
            "description": "Remote file transfer",
            "available": False,
            "configured": False,
            "formats": list(supported_extensions()),
        },
    ]
