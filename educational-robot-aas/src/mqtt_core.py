import asyncio
import json
import uuid

from gmqtt import Client as MQTTClient
from core.log import logger


class MqttCore:
    def __init__(self, broker_host="192.168.100.21", broker_port=1883):
        self.broker_host = broker_host
        self.broker_port = broker_port
        self.client = MQTTClient(str(uuid.uuid4()))
        self.callbacks = {}
        self.client.on_connect = self.on_connect
        self.client.on_message = self.on_message
        self.client.on_disconnect = self.on_disconnect
        self.client.on_subscribe = self.on_subscribe

        self.event = asyncio.Event()
        self._message_client = None
        logger.info('MQTT CORE INITIALIZED')

        self.connected = False

    def on_connect(self, client, flags, rc, properties):
        logger.info(f'MQTT CONNECTED TO {self.broker_host}:{self.broker_port}')
        for key in self.callbacks.keys():
            client.subscribe(key, qos=0)

    def on_disconnect(self, client, packet, exc=None):
        logger.info('MQTT DISCONNECTED')

    def on_subscribe(self, client, mid, qos, properties):
        logger.info('MQTT SUBSCRIBED')

    async def on_message(self, client, topic, payload, qos, properties):
        for key in self.callbacks.keys():
            if key == topic:
                loop = asyncio.get_running_loop()
                loop.create_task(self.callbacks[key](client, topic, payload, qos, properties))

    def add_subscribe(self, topic, callback):
        self.callbacks[topic] = callback
        logger.info(f'Callback added to topic: {topic}')

    async def send_message(self, topic, message):
        payload = json.dumps(message)
        self.client.publish(topic, payload)
        # logger.debug(f'Message sent to {topic}: {payload}')

    async def init(self):
        logger.info(f'CONNECTING TO BROKER: {self.broker_host}:{self.broker_port}')
        await self.client.connect(self.broker_host, self.broker_port)
        while True:
            await asyncio.sleep(1)
