"""
tests/test_ibmmq_sidecar.py — TDD Tests for IBM MQ Sidecar Connector
=====================================================================

Tests for IBM MQ read-only sidecar using browse mode.

Core principle: NEVER touch or modify messages. NEVER alter queue state.
- Uses MQOO_BROWSE (browse mode)
- Uses MQGMO_BROWSE_FIRST / MQGMO_BROWSE_NEXT
- NEVER uses MQGMO_MSG_UNDER_CURSOR (destructive read)

Phase 4: IBM MQ Sidecar Connector
"""

import pytest
import json
from datetime import datetime, UTC
from unittest.mock import MagicMock, patch


class TestIBMMQSidecarInit:
    """Tests for IBM MQ sidecar initialization."""

    def test_sidecar_requires_config(self):
        """Sidecar must require valid config."""
        from streamforge.sidecar.ibmmq import IBMMQSidecar
        from streamforge.sidecar.models import IBMMQConfig

        config = IBMMQConfig(
            host="mq.company.com",
            port=1414,
            queue_manager="QM1",
            queue_name="DEV.QUEUE.1",
            channel="DEV.APP.SVRCONN",
        )
        sidecar = IBMMQSidecar(config)

        assert sidecar.queue_name == "DEV.QUEUE.1"
        assert sidecar.queue_type == "ibm_mq"

    def test_sidecar_enforces_browse_mode(self):
        """Sidecar must enforce browse mode."""
        from streamforge.sidecar.ibmmq import IBMMQSidecar
        from streamforge.sidecar.models import IBMMQConfig

        config = IBMMQConfig(
            host="mq.company.com",
            port=1414,
            queue_manager="QM1",
            queue_name="DEV.QUEUE.1",
            channel="DEV.APP.SVRCONN",
        )
        sidecar = IBMMQSidecar(config)

        # Internal browse mode must be True
        assert sidecar._browse_mode is True


class TestIBMMQSidecarPeek:
    """Tests for IBM MQ peek (browse without consume)."""

    @pytest.mark.asyncio
    async def test_peek_returns_observation_batch(self):
        """Peek must return an ObservationBatch."""
        from streamforge.sidecar.ibmmq import IBMMQSidecar
        from streamforge.sidecar.models import IBMMQConfig, ObservationBatch

        config = IBMMQConfig(
            host="mq.company.com",
            port=1414,
            queue_manager="QM1",
            queue_name="DEV.QUEUE.1",
            channel="DEV.APP.SVRCONN",
        )

        sidecar = IBMMQSidecar(config)

        # Mock the queue directly
        mock_queue = MagicMock()
        mock_md = MagicMock()
        mock_md.MsgId = b"msg-001"
        mock_md.CorrelId = b"corr-001"

        # First call returns message, second raises to signal end
        mock_queue.get.side_effect = [
            (mock_md, b'{"order_id": "123"}'),
            Exception("2033"),  # MQRC_NO_MSG_AVAILABLE
        ]

        sidecar._connection = MagicMock()
        sidecar._queue = mock_queue

        batch = await sidecar.peek(max_messages=10)

        assert isinstance(batch, ObservationBatch)
        assert batch.message_count == 1

    @pytest.mark.asyncio
    async def test_peek_uses_browse_option(self):
        """Peek must use MQOO_BROWSE open option."""
        from streamforge.sidecar.ibmmq import IBMMQSidecar
        from streamforge.sidecar.models import IBMMQConfig

        config = IBMMQConfig(
            host="mq.company.com",
            port=1414,
            queue_manager="QM1",
            queue_name="DEV.QUEUE.1",
            channel="DEV.APP.SVRCONN",
        )

        sidecar = IBMMQSidecar(config)

        # Verify the sidecar will use browse mode
        assert sidecar._get_open_options() & 0x00000008 != 0  # MQOO_BROWSE = 0x00000008

    @pytest.mark.asyncio
    async def test_peek_emits_telemetry(self):
        """Peek must emit telemetry events."""
        from streamforge.sidecar.ibmmq import IBMMQSidecar
        from streamforge.sidecar.models import IBMMQConfig
        from io import StringIO
        import json

        config = IBMMQConfig(
            host="mq.company.com",
            port=1414,
            queue_manager="QM1",
            queue_name="DEV.QUEUE.1",
            channel="DEV.APP.SVRCONN",
        )

        telemetry_output = StringIO()
        sidecar = IBMMQSidecar(config, telemetry_stream=telemetry_output)

        mock_queue = MagicMock()
        mock_queue.get.side_effect = Exception("2033")  # No messages
        sidecar._connection = MagicMock()
        sidecar._queue = mock_queue

        await sidecar.peek()

        telemetry_output.seek(0)
        lines = telemetry_output.readlines()
        assert len(lines) >= 1


class TestIBMMQSidecarBrowse:
    """Tests for IBM MQ browse (cursor-based iteration)."""

    @pytest.mark.asyncio
    async def test_browse_returns_batch_and_cursor(self):
        """Browse must return batch and next cursor."""
        from streamforge.sidecar.ibmmq import IBMMQSidecar
        from streamforge.sidecar.models import IBMMQConfig

        config = IBMMQConfig(
            host="mq.company.com",
            port=1414,
            queue_manager="QM1",
            queue_name="DEV.QUEUE.1",
            channel="DEV.APP.SVRCONN",
        )

        sidecar = IBMMQSidecar(config)

        mock_queue = MagicMock()
        mock_md = MagicMock()
        mock_md.MsgId = b"msg-001"
        mock_md.CorrelId = b"corr-001"
        mock_queue.get.side_effect = [
            (mock_md, b'{}'),
            Exception("2033"),
        ]
        sidecar._connection = MagicMock()
        sidecar._queue = mock_queue

        batch, cursor = await sidecar.browse()

        # IBM MQ supports cursor-based browsing
        assert batch is not None


class TestIBMMQSidecarQueueDepth:
    """Tests for queue depth check."""

    @pytest.mark.asyncio
    async def test_get_queue_depth_returns_count(self):
        """get_queue_depth must return message count."""
        from streamforge.sidecar.ibmmq import IBMMQSidecar
        from streamforge.sidecar.models import IBMMQConfig

        config = IBMMQConfig(
            host="mq.company.com",
            port=1414,
            queue_manager="QM1",
            queue_name="DEV.QUEUE.1",
            channel="DEV.APP.SVRCONN",
        )

        with patch("streamforge.sidecar.ibmmq.IBMMQSidecar._get_connection") as mock_conn:
            mock_queue = MagicMock()
            mock_queue.inquire.return_value = 42
            mock_conn.return_value = (MagicMock(), mock_queue)

            sidecar = IBMMQSidecar(config)
            depth = await sidecar.get_queue_depth()

            assert depth == 42


class TestIBMMQSidecarSafety:
    """Tests for safety guarantees."""

    def test_sidecar_has_no_destructive_methods(self):
        """Sidecar must NOT have destructive capabilities."""
        from streamforge.sidecar.ibmmq import IBMMQSidecar

        # These must NOT exist
        assert not hasattr(IBMMQSidecar, "put")
        assert not hasattr(IBMMQSidecar, "delete")
        assert not hasattr(IBMMQSidecar, "commit")
        assert not hasattr(IBMMQSidecar, "backout")

    def test_open_options_exclude_input(self):
        """Open options must NOT include MQOO_INPUT_*."""
        from streamforge.sidecar.ibmmq import IBMMQSidecar
        from streamforge.sidecar.models import IBMMQConfig

        config = IBMMQConfig(
            host="mq.company.com",
            port=1414,
            queue_manager="QM1",
            queue_name="DEV.QUEUE.1",
            channel="DEV.APP.SVRCONN",
        )

        sidecar = IBMMQSidecar(config)
        options = sidecar._get_open_options()

        # MQOO_INPUT_SHARED = 0x00000002
        # MQOO_INPUT_EXCLUSIVE = 0x00000004
        assert options & 0x00000002 == 0  # No INPUT_SHARED
        assert options & 0x00000004 == 0  # No INPUT_EXCLUSIVE

    def test_get_options_use_browse(self):
        """Get options must use MQGMO_BROWSE_*, not destructive read."""
        from streamforge.sidecar.ibmmq import IBMMQSidecar
        from streamforge.sidecar.models import IBMMQConfig

        config = IBMMQConfig(
            host="mq.company.com",
            port=1414,
            queue_manager="QM1",
            queue_name="DEV.QUEUE.1",
            channel="DEV.APP.SVRCONN",
        )

        sidecar = IBMMQSidecar(config)
        options = sidecar._get_browse_options(first=True)

        # MQGMO_BROWSE_FIRST = 0x00000010
        assert options & 0x00000010 != 0
