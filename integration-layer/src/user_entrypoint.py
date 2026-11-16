import logging # biblioteca de logging
from asyncua import Node
from core.interfaces import Entrypoint
from core.log import logger
from .opcua_tools import opcuaTools

class UserEntrypoint(Entrypoint):

    def __init__(self, server):
        super().__init__(server)
        
        # Define o nível de log para as bibliotecas mais "barulhentas" como WARNING.
        # Isso significa que só veremos mensagens de aviso ou erro delas.
        logging.getLogger('asyncua').setLevel(logging.WARNING)
        logging.getLogger('aas_creation').setLevel(logging.WARNING)
        # -----------------------------------------------------------------

        logger.info('UserEntrypoint initialized for PickAndPlace')
        self.opcuaTools = opcuaTools()

    async def init(self):
        
        paths = {
            "OperationalState": ["AssetAdministrationShell", "PickAndPlace", "PickAndPlacePositioning", "GripperControl", "OperationalState", "Value"],
            "PickPositionX": ["AssetAdministrationShell", "PickAndPlace", "PickAndPlacePositioning", "GripperControl", "PickPosition", "XPosition", "Value"],
            "PickPositionY": ["AssetAdministrationShell", "PickAndPlace", "PickAndPlacePositioning", "GripperControl", "PickPosition", "YPosition", "Value"],
            "PickPositionZ": ["AssetAdministrationShell", "PickAndPlace", "PickAndPlacePositioning", "GripperControl", "PickPosition", "ZPosition", "Value"],
            "PlacePositionX": ["AssetAdministrationShell", "PickAndPlace", "PickAndPlacePositioning", "GripperControl", "PlacePosition", "XPosition", "Value"],
            "PlacePositionY": ["AssetAdministrationShell", "PickAndPlace", "PickAndPlacePositioning", "GripperControl", "PlacePosition", "YPosition", "Value"],
            "PlacePositionZ": ["AssetAdministrationShell", "PickAndPlace", "PickAndPlacePositioning", "GripperControl", "PlacePosition", "ZPosition", "Value"],
        }

        logger.info("Setting PickAndPlace nodes as writable...")
        for key, path in paths.items():
            try:
                node: Node = await self.opcuaTools.find_value_node(self.server, path)
                if node:
                    await node.set_writable()
                    logger.info(f"Node '{key}' set as writable.")
                else:
                    logger.warning(f"Node '{key}' not found at path: {path}")
            except Exception as e:
                logger.error(f"Error setting node '{key}' as writable: {e}")