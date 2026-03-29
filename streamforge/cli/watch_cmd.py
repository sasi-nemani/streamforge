"""Command: watch."""

from pathlib import Path

import typer

from ._helpers import _auto_detect_schema, console


def watch(
    stream_path: str = typer.Argument(..., help="Folder path or kafka://topic URI"),
    schema_path: str | None = typer.Option(None, "--schema", help="Path to schema.yaml (auto-detected if not set)"),
    interval: int = typer.Option(0, "--interval", "-i", help="Poll interval in seconds (0 = use config)"),
    sample_size: int = typer.Option(0, "--sample-size", "-n", help="Events to sample per cycle (0 = use config)"),
    window_capacity: int = typer.Option(0, "--window", help="Rolling event window size (0 = use config)"),
    webhook: str | None = typer.Option(None, "--webhook", "-w", help="Webhook URL for drift notifications"),
    brokers: str | None = typer.Option(
        None, "--brokers",
        help="Comma-separated Kafka broker list (e.g. broker-1:9092,broker-2:9092). "
             "Only used when stream_path is a kafka:// URI. "
             "Overrides KAFKA_BOOTSTRAP_SERVERS env var.",
        envvar="KAFKA_BOOTSTRAP_SERVERS",
    ),
    env: str | None = typer.Option(
        None, "--env",
        help="Config environment to use (dev/staging/prod). "
             "Overrides STREAMFORGE_ENV env var.",
    ),
):
    """Watch stream for schema drift. Runs continuously until Ctrl+C.

    Supports two sources:

    \b
      streamforge watch events/payments/stream_v1               # file-based
      streamforge watch kafka://events.payments --brokers b:9092  # Kafka topic
      streamforge watch kafka://events.payments --env prod        # with env config

    Config is loaded from config/topics/<topic>.yaml -> config/<env>.yaml -> config/default.yaml.
    CLI flags override config file values when explicitly provided.
    """
    from ..topic_config import load_topic_config

    is_kafka = stream_path.startswith("kafka://")

    # Schema auto-detection uses the topic name for kafka:// URIs
    schema_stream_path = stream_path[len("kafka://"):] if is_kafka else stream_path
    resolved_schema = schema_path or _auto_detect_schema(schema_stream_path, "schemas")
    if not resolved_schema:
        console.print(
            f"[red]No schema.yaml found for {schema_stream_path}. "
            "Run 'streamforge init' first or pass --schema.[/red]"
        )
        raise typer.Exit(1)

    # Load resolved config for this topic + env
    stream_name = schema_stream_path if is_kafka else Path(stream_path).name
    tc = load_topic_config(stream_name, env)

    # CLI flags take priority over config; 0 means "use config"
    effective_interval  = interval       if interval       > 0 else tc.poll_interval_seconds
    effective_sample    = sample_size    if sample_size    > 0 else tc.sample_size
    effective_window    = window_capacity if window_capacity > 0 else tc.window_capacity
    effective_webhook   = webhook or tc.webhook_url

    if is_kafka:
        topic = stream_path[len("kafka://"):]
        from ..config import KafkaConfig
        from ..drift_detector import watch_stream_kafka

        # Brokers: CLI flag -> env var (inside tc via KAFKA_BOOTSTRAP_SERVERS) -> topic config
        effective_brokers = (
            [b.strip() for b in brokers.split(",") if b.strip()]
            if brokers
            else tc.kafka_broker_list
        )
        if not effective_brokers:
            console.print(
                "[red]No Kafka brokers configured. "
                "Pass --brokers, set KAFKA_BOOTSTRAP_SERVERS, or add kafka.brokers to config/.[/red]"
            )
            raise typer.Exit(1)

        kafka_cfg = KafkaConfig(
            bootstrap_servers=effective_brokers,
            security_protocol=tc.kafka_security_protocol,
            consumer_group=tc.kafka_consumer_group,
            auto_offset_reset=tc.kafka_auto_offset_reset,
            session_timeout_ms=tc.kafka_session_timeout_ms,
            request_timeout_ms=tc.kafka_request_timeout_ms,
        )

        watch_stream_kafka(
            topic, kafka_cfg, resolved_schema,
            effective_interval, effective_sample, effective_window, effective_webhook,
        )
    else:
        from ..drift_detector import watch_stream
        watch_stream(stream_path, resolved_schema, effective_interval, effective_sample, effective_window, effective_webhook)
