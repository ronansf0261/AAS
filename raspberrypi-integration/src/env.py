import os


def get_env_variables() -> tuple[str, int, str, str, int]:
    """
    :str: MQTT broker address
    :int: MQTT broker port
    :str: Communication topic
    :rtype: tuple[str, int, str, str]
    """
    broker: str | None = os.environ.get("MQTT_BROKER")
    port: str | None = os.environ.get("MQTT_PORT")
    topic_command: str | None = os.environ.get("MQTT_TOPIC_COMMAND")
    topic_feedback: str | None = os.environ.get("MQTT_TOPIC_FEEDBACK")
    baud_rate: str | None = os.environ.get("BAUD_RATE")

    if broker is None:
        raise ValueError("MQTT_BROKER environment variable not defined")

    if port is None:
        raise ValueError("MQTT_PORT environment variable not defined")

    if topic_command is None:
        raise ValueError("MQTT_TOPIC_COMMAND environment variable not defined")

    if topic_feedback is None:
        raise ValueError("MQTT_TOPIC_FEEDBACK environment variable not defined")

    if baud_rate is None:
        raise ValueError("BAUD_RATE environment variable not defined")

    return broker, int(port), topic_command, topic_feedback, int(baud_rate)
