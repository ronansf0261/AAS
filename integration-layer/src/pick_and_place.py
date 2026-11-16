import asyncio
import os
from core.asset_administration_shell import AssetAdministrationShell
from core.interfaces import BaseSubmodel
from core.log import logger
from asyncua import Node
from .opcua_tools import SubscriptionHandler, opcuaTools
from .modbus_comm_manager import ModbusCommManager
# Registradores, validações e sequência de movimentos ficam em cr3_motion.py, compartilhados
# com o modo gateway MQTT (gateway_mqtt.py).
from .cr3_motion import (CR3Motion, DEFAULT_OBJECT_HEIGHT, FORBIDDEN_DOME_HEIGHT,
                         FORBIDDEN_DOME_RADIUS, SIMULATED_MOVE_TIME,
                         process_coordinates_for_modbus, validate_coordinates)

class PickAndPlace(BaseSubmodel):
    
    paths = {
        "OperationalState": ["AssetAdministrationShell", "PickAndPlace", "PickAndPlacePositioning", "GripperControl", "OperationalState", "Value"],
        "PickPositionX": ["AssetAdministrationShell", "PickAndPlace", "PickAndPlacePositioning", "GripperControl", "PickPosition", "XPosition", "Value"],
        "PickPositionY": ["AssetAdministrationShell", "PickAndPlace", "PickAndPlacePositioning", "GripperControl", "PickPosition", "YPosition", "Value"],
        "PickPositionZ": ["AssetAdministrationShell", "PickAndPlace", "PickAndPlacePositioning", "GripperControl", "PickPosition", "ZPosition", "Value"],
        "PlacePositionX": ["AssetAdministrationShell", "PickAndPlace", "PickAndPlacePositioning", "GripperControl", "PlacePosition", "XPosition", "Value"],
        "PlacePositionY": ["AssetAdministrationShell", "PickAndPlace", "PickAndPlacePositioning", "GripperControl", "PlacePosition", "YPosition", "Value"],
        "PlacePositionZ": ["AssetAdministrationShell", "PickAndPlace", "PickAndPlacePositioning", "GripperControl", "PlacePosition", "ZPosition", "Value"],
        "MaxLimitX": ["AssetAdministrationShell", "TechnicalData", "TechnicalProperties", "CoordinateLimits", "MaxLimitX", "Value"],
        "MinLimitX": ["AssetAdministrationShell", "TechnicalData", "TechnicalProperties", "CoordinateLimits", "MinLimitX", "Value"],
        "MaxLimitY": ["AssetAdministrationShell", "TechnicalData", "TechnicalProperties", "CoordinateLimits", "MaxLimitY", "Value"],
        "MinLimitY": ["AssetAdministrationShell", "TechnicalData", "TechnicalProperties", "CoordinateLimits", "MinLimitY", "Value"],
        "MaxLimitZ": ["AssetAdministrationShell", "TechnicalData", "TechnicalProperties", "CoordinateLimits", "MaxLimitZ", "Value"],
        "MinLimitZ": ["AssetAdministrationShell", "TechnicalData", "TechnicalProperties", "CoordinateLimits", "MinLimitZ", "Value"],
        "HomePositionX": ["AssetAdministrationShell", "PickAndPlace", "ArmWorkspace", "HomePosition", "XPosition", "Value"],
        "HomePositionY": ["AssetAdministrationShell", "PickAndPlace", "ArmWorkspace", "HomePosition", "YPosition", "Value"],
        "HomePositionZ": ["AssetAdministrationShell", "PickAndPlace", "ArmWorkspace", "HomePosition", "ZPosition", "Value"],
    }

    def __init__(self, server: AssetAdministrationShell):
        self.server = server
        self.opcua_tools = opcuaTools()
        self.nodes_to_read = {}
        self.coord_limits = {}
        
        ### ADICIONADO: Parâmetros da zona proibida (cúpula) ###
        self.forbidden_dome_radius = FORBIDDEN_DOME_RADIUS
        self.forbidden_dome_height = FORBIDDEN_DOME_HEIGHT
        logger.info(f"Zona de exclusão em formato de cúpula ativada com R={self.forbidden_dome_radius} e Altura Máx.={self.forbidden_dome_height}")
        
        modbus_host = os.getenv('MODBUS_HOST', 'localhost')
        modbus_port = int(os.getenv('MODBUS_PORT', 5020))
        self.modbus_client = ModbusCommManager(host=modbus_host, port=modbus_port)
        self.modbus_client.connect()
        if not self.modbus_client.connected:
            logger.error("Falha ao conectar ao simulador Modbus.")
        self.motion = CR3Motion(self.modbus_client, self.coord_limits, SIMULATED_MOVE_TIME, logger)
        logger.info(f"Submodelo {self.__class__.__name__} criado e pronto para operar.")

    async def init(self, node, *args, **kwargs):
        self.subscription_handler = SubscriptionHandler(self.opcua_callback)
        try:
            for key, path in self.paths.items():
                if "Limit" not in key and key != "OperationalState":
                    self.nodes_to_read[key] = await self.opcua_tools.find_value_node(self.server, path)
            logger.info("Lendo os limites de coordenadas do robô...")
            limit_keys = [k for k in self.paths if "Limit" in k]
            for key in limit_keys:
                limit_node = await self.opcua_tools.find_value_node(self.server, self.paths[key])
                if limit_node:
                    self.coord_limits[key] = float(await limit_node.read_value())
                    logger.info(f"  -> Limite '{key}' carregado: {self.coord_limits[key]}")
                else:
                    logger.warning(f"Nó de limite '{key}' não encontrado. A validação pode falhar.")
            op_state_node = await self.opcua_tools.find_value_node(self.server, self.paths['OperationalState'])
            if op_state_node:
                await self.opcua_tools.subscribe_to_datachange(self.server, [op_state_node], self.subscription_handler)
                logger.info(f"✅ Inscrição no nó 'OperationalState' realizada com sucesso. Aguardando comandos...")
            else:
                logger.error("❌ Não foi possível encontrar o nó 'OperationalState' para se inscrever.")
        except Exception as e:
            logger.error(f"Erro durante a inicialização do submodelo PickAndPlace: {e}")

    # --- FUNÇÃO return_to_home com simulação de tempo ---
    async def return_to_home(self):
        try:
            home_x = float(await self.nodes_to_read['HomePositionX'].read_value())
            home_y = float(await self.nodes_to_read['HomePositionY'].read_value())
            home_z = float(await self.nodes_to_read['HomePositionZ'].read_value())

            if not await self.motion.go_home((home_x, home_y, home_z)):
                return False

            logger.info("Sincronizando Gêmeo Digital com a Home Position...")
            for grupo in ("PickPosition", "PlacePosition"):
                for eixo, valor in zip("XYZ", (home_x, home_y, home_z)):
                    await self.opcua_tools.write_keeping_type(self.nodes_to_read[f"{grupo}{eixo}"], valor)
            return True

        except Exception as e:
            logger.error(f"Falha ao executar a rotina de retorno à Home: {e}")
            return False

    # --- FUNÇÃO opcua_callback ---
    async def opcua_callback(self, node: Node, val, data):
        logger.info(f"Comando recebido! Novo estado operacional: {val}")

        # Lógica para START / ACTIVE
        if isinstance(val, str) and val.lower() in ["active", "start"]:
            logger.info("--- INICIANDO CICLO COMPLETO DE PICK & PLACE ---")
            try:
                # ETAPA DE LEITURA E VALIDAÇÃO
                pick_x = float(await self.nodes_to_read['PickPositionX'].read_value())
                pick_y = float(await self.nodes_to_read['PickPositionY'].read_value())
                pick_z = float(await self.nodes_to_read['PickPositionZ'].read_value())
                place_x = float(await self.nodes_to_read['PlacePositionX'].read_value())
                place_y = float(await self.nodes_to_read['PlacePositionY'].read_value())
                place_z = float(await self.nodes_to_read['PlacePositionZ'].read_value())
                
                object_height = DEFAULT_OBJECT_HEIGHT
                pick_z_robot = pick_z + object_height
                place_z_robot = place_z + object_height

                if not (self.validate_coordinates(pick_x, pick_y, pick_z_robot, "PickPosition (Robô)") and 
                        self.validate_coordinates(place_x, place_y, place_z_robot, "PlacePosition (Robô)")):
                    await node.write_value("Error: Coordinates Out of Bounds")
                    return

                # FASE 1 e FASE 2 (sequência de registradores em cr3_motion.py)
                await self.motion.move_to_pick([pick_x, pick_y, pick_z_robot])
                await self.motion.move_to_place([place_x, place_y, place_z_robot])

                # FASE 3: RETORNAR À HOME
                
                await self.return_to_home()
                
                # FINALIZAÇÃO
                
                await node.write_value("Idle")
                logger.info("--- CICLO COMPLETO. Robô na Home Position e estado 'Idle'. ---")

            except Exception as e:
                logger.error(f"Falha ao executar a operação de Pick and Place: {e}")
                await node.write_value("Error")
        
        # Lógica para CALIBRATE
        elif isinstance(val, str) and val.lower() == "calibrate":
            if await self.return_to_home():
                await node.write_value("Idle")
            else:
                await node.write_value("Error: Calibration Failed")
    
    # Validação (caixa + cúpula) e conversão para Modbus: implementadas em cr3_motion.py
    def validate_coordinates(self, x, y, z, point_name="Ponto"):
        return validate_coordinates(x, y, z, self.coord_limits, point_name, logger,
                                    self.forbidden_dome_radius, self.forbidden_dome_height)

    def process_coordinates_for_modbus(self, coords: list):
        return process_coordinates_for_modbus(coords)
