import asyncio
import json
import os
from core.asset_administration_shell import AssetAdministrationShell
from core.interfaces import BaseSubmodel
from core.log import logger
from .mqtt_core import MqttCore
from asyncua import Node

MQTT_HOST = os.getenv("MQTT_HOST", "192.168.100.21")
MQTT_PORT = int(os.getenv("MQTT_PORT", 1883))
ASSET_ID = os.getenv("ASSET_ID", "default_id")

topic1 = f"spacexlab/AAS/{ASSET_ID}/command"
topic2 = f"spacexlab/AAS/{ASSET_ID}/state"


class SubHandler(object):
    """
    Subscription Handler. To receive events from server for a subscription
    """

    def __init__(self, server: AssetAdministrationShell):
        self.server: AssetAdministrationShell = server
        self.loop = asyncio.get_running_loop()
        self.mqtt: MqttCore = None

        # pick and place parameters
        self.xin: Node = None
        self.yin: Node = None
        self.zin: Node = None
        self.xout: Node = None
        self.yout: Node = None
        self.zout: Node = None

        # grabber parameters
        self.opening_width_node: Node = None
        self.clamping_width_node: Node = None
        self.gripper_type_node: Node = None

    async def datachange_notification(self, node, val, data):
        logger.info("Python: New data change event %s %s", node, val)
        
        if not (isinstance(val, str) and val.lower() in {"calibrate", "start", "stop", "idle"}):
            logger.info("[pick_and_place] data_change: Unknown value passed to node: %s", val)
            return
        
        message: dict = {}
        
        if val.lower() == "start":
            try:
                x_pick_value, y_pick_value, z_pick_value,  = await asyncio.gather(
                    self.xin.read_value(),
                    self.yin.read_value(),
                    self.zin.read_value(),
                )

                x_place_value, y_place_value, z_place_value = await asyncio.gather(
                    self.xout.read_value(),
                    self.yout.read_value(),
                    self.zout.read_value()
                )

                opening_width, clamping_width, gripper_type = await asyncio.gather(
                    self.opening_width_node.read_value(),
                    self.clamping_width_node.read_value(),
                    self.gripper_type_node.read_value()
                )
            
                message = {
                    "data":{
                        "cmd": "start",
                        "in_coord": {
                            "x": str(x_pick_value),
                            "y": str(y_pick_value),
                            "z": str(z_pick_value),
                        },
                        "out_coord": {
                            "x": str(x_place_value),
                            "y": str(y_place_value),
                            "z": str(z_place_value),
                        },
                        "end_effector": str(gripper_type),
                        "gripper_open": str(opening_width),
                        "gripper_close": str(clamping_width)
                    }
                }

            except Exception as e:
                logger.error(f"Erro ao obter os valores do OPC UA: {e}")
                return

        elif val.lower() == "calibrate":
            message = {
                "data":{
                    "cmd": "calibrate"
                }
            }

        elif val.lower() == "stop":
            # Interrompe o movimento em andamento (máquina de estados do gateway: estado Stopped)
            message = {
                "data":{
                    "cmd": "stop"
                }
            }

        try:
            if not message:
                return
            
            await asyncio.create_task(self.mqtt.send_message(topic1, message))
        
        except Exception as e:
            logger.error(f"Erro ao enviar mensagem em tópico: {e}")

    def event_notification(self, event):
        logger.info(f"Event {event}")


class PickAndPlace(BaseSubmodel):
    __paths = {
        "operational_state": ["AssetAdministrationShell", "PickAndPlace", "PickAndPlacePositioning", "GripperControl", "OperationalState", "Value"],
        
        "x_pick_position": ["AssetAdministrationShell", "PickAndPlace", "PickAndPlacePositioning", "GripperControl", "PickPosition", "XPosition", "Value"],
        "y_pick_position": ["AssetAdministrationShell", "PickAndPlace", "PickAndPlacePositioning", "GripperControl", "PickPosition", "YPosition", "Value"],
        "z_pick_position": ["AssetAdministrationShell", "PickAndPlace", "PickAndPlacePositioning", "GripperControl", "PickPosition", "ZPosition", "Value"],

        "x_place_position": ["AssetAdministrationShell", "PickAndPlace", "PickAndPlacePositioning", "GripperControl", "PlacePosition", "XPosition", "Value"],
        "y_place_position": ["AssetAdministrationShell", "PickAndPlace", "PickAndPlacePositioning", "GripperControl", "PlacePosition", "YPosition", "Value"],
        "z_place_position": ["AssetAdministrationShell", "PickAndPlace", "PickAndPlacePositioning", "GripperControl", "PlacePosition", "ZPosition", "Value"],

        "opening_width": ["AssetAdministrationShell", "Grabber", "ParallelGripping", "OpeningWidth", "Value"],
        "clamping_width": ["AssetAdministrationShell", "Grabber", "ParallelGripping", "ClampingWidth", "Value"],
        "gripper_type": ["AssetAdministrationShell", "Grabber", "GripperType", "Value"]
    }

    def __init__(self, server: AssetAdministrationShell):
        self.server = server
        self.loop = asyncio.get_running_loop()
        self.last_status = "stop"
        self.pick_and_place_submodel = None
        self.subscription_handler_interface = None
        self.subscription_handler = None
        self.mqtt = MqttCore(broker_host=MQTT_HOST, broker_port=MQTT_PORT)
        self.mqtt.add_subscribe(topic2, self.mqtt_callback)
        self.loop.create_task(self.mqtt.init())

    async def mqtt_callback(self, client, topic, payload: bytes, qos, properties):
        logger.info("Topic received: " + topic)
        try:
            data = json.loads(payload.decode())
            if data is None:
                return

            await self.process_property(data,
                                        "operational_state",
                                        self.__paths["operational_state"],
                                        topic)

        except Exception as e:
            logger.info(f"[ERROR] Payload conversion error: {e}")

    async def process_property(self, data, propriedade, path, topico):
        value = data.get(propriedade)
        
        if value is None:
            logger.warning(f"Chave '{propriedade}' não encontrada no tópico: {topico}")

        elif not isinstance(value, str):
            logger.warning(f"Valor de '{propriedade}' no tópico '{topico}' não é uma string válida: {value}")

        else:
            try:
                node: Node = await self.find_value_node(path)
                if node:
                    logger.info(f"Escrevendo valor '{value}' no nó: {await node.read_display_name()}")
                    await self.write_to_opcua(node, value)

            except Exception as e:
                logger.error(f"Erro ao processar a propriedade '{propriedade}' no tópico '{topico}': {e}")

    async def init(self, node, *args, **kwargs):
        self.subscription_handler = SubHandler(self.server)

        self.subscription_handler.xin = await self.find_value_node(self.__paths["x_pick_position"])
        self.subscription_handler.yin = await self.find_value_node(self.__paths["y_pick_position"])
        self.subscription_handler.zin = await self.find_value_node(self.__paths["z_pick_position"])
        
        self.subscription_handler.xout = await self.find_value_node(self.__paths["x_place_position"])
        self.subscription_handler.yout = await self.find_value_node(self.__paths["y_place_position"])
        self.subscription_handler.zout = await self.find_value_node(self.__paths["z_place_position"])

        self.subscription_handler.opening_width_node = await self.find_value_node(self.__paths["opening_width"])
        self.subscription_handler.clamping_width_node = await self.find_value_node(self.__paths["clamping_width"])
        self.subscription_handler.gripper_type_node = await self.find_value_node(self.__paths["gripper_type"])

        self.subscription_handler.mqtt = self.mqtt

        await asyncio.sleep(10)
        await self.subscribe_to_data_change(self.__paths["operational_state"])
        while True:
           await asyncio.sleep(10)

    async def find_value_node(self, path):
        try:
            root_node = self.server.get_root_node()
            objects_node = await root_node.get_child(["0:Objects"])
            current_node = objects_node

            for level in path:
                children = await current_node.get_children()
                next_node = None

                for child in children:
                    display_name = await child.read_display_name()
                    if level in display_name.Text:
                        next_node = child
                        break

                if next_node is None:
                    logger.error(f"Nó com o nome contendo '{level}' não encontrado.")
                    return None
                current_node = next_node

            return current_node

        except Exception as e:
            logger.error(f"Erro ao buscar o nó com o caminho {path}: {e}")
            return None
    
    async def write_to_opcua(self, node, value):
        try:
            await node.write_value(value)
        except Exception as e:
            logger.error(f"Erro ao escrever no OPC UA: {e}")

    async def subscribe_to_data_change(self, path):
        node = await self.find_value_node(path)

        # Create a subscription using the existing server/client
        subscription = await self.server.create_subscription(500, self.subscription_handler)

        # Subscribe to the node
        handle = await subscription.subscribe_data_change(node)

        # Store subscription information for later use
        self.subscription_handler_interface = subscription

        print(f"Subscribed to node: {node}, handle: {handle}")

        # Keep the task running to maintain the subscription
        while True:
            await asyncio.sleep(1)
