import asyncio
import os
from asyncua import Node, ua
from core.log import logger
    
class SubscriptionHandler():

    def __init__(self, callback):
        self.callback = callback

    # Essa função é executada quando uma mudança é detectada em algum nó OPC UA ela é responsável por escrever os dados do sumbmodelo em um tópico MQTT
    async def datachange_notification(self, node: Node, val, data):
        '''
        Callback para a subscrição do asyncua.
        O metodo será chamado quando o cliente receber uma mudança nos dados do servidor OPCUA
        '''

        #logger.info("new opc UA datachange notification %r %s", node, val)
        await self.callback(node, val, data)

class opcuaTools():
    # Metodo que busca um nó no servidor OPC UA com base no caminho passado como parametro
    async def find_value_node(self, server, path):
        self.server = server
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
    
    # Escreve mantendo o tipo atual do nó. Na AAS do CR3 as posições são String ("0.0"):
    # escrever um float nelas dá BadTypeMismatch.
    async def write_keeping_type(self, node, value):
        vtype = (await node.read_data_value()).Value.VariantType
        if vtype == ua.VariantType.String:
            value = str(value)
        elif vtype in (ua.VariantType.Float, ua.VariantType.Double):
            value = float(value)
        elif vtype in (ua.VariantType.Int16, ua.VariantType.Int32, ua.VariantType.Int64,
                       ua.VariantType.UInt16, ua.VariantType.UInt32, ua.VariantType.UInt64):
            value = int(round(float(value)))
        await node.write_value(ua.Variant(value, vtype))

    # Metodo que escreve um valor em um nó do servidor OPC UA
    async def write_to_opcua(self, node, value):
        try:
            await node.write_value(value)
        except Exception as e:
            logger.error(f"Erro ao escrever no OPC UA: {e}")

    # Metodo que se inscreve em um nó do servidor OPC UA para receber notificações de mudanças
    async def subscribe_to_datachange(self, server, node, subscription_handler):

        # Create a subscription using the existing server/client
        subscription = await self.server.create_subscription(500, subscription_handler)

        # Subscribe to the node
        handle = await subscription.subscribe_data_change(node)

        # Store subscription information for later use
        self.subscription_handler_interface = subscription

        logger.info(f"Subscribed to node: {node}, handle: {handle}")

        # Keep the task running to maintain the subscription
        while True:
            await asyncio.sleep(1)
    
