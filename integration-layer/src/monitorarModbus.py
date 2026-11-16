import asyncio
import os
import logging
import time
from pymodbus.server import StartAsyncTcpServer
from pymodbus.device import ModbusDeviceIdentification
from pymodbus.datastore import ModbusSequentialDataBlock, ModbusSlaveContext
from pymodbus.datastore import ModbusServerContext

# --- Configurações ---
# Endereço onde o simulador escuta. Use 0.0.0.0 para aceitar conexões de outra máquina.
HOST = os.getenv("MODBUS_SIM_HOST", "localhost")
PORT = int(os.getenv("MODBUS_SIM_PORT", 5020))
START_ADDRESS = 4000
REGISTER_COUNT = 10 # De 4000 a 4009
REG_STATUS = 4009

# Handshake do registrador STATUS (ver integration-layer/src/cr3_motion.py): o gateway escreve 1
# ao disparar um movimento; com SIM_EMULA_STATUS=1 o simulador faz o papel do programa do
# controlador e devolve 0 depois de SIM_MOVE_TIME segundos. Para simular falhas, escreva 2
# (alarme) ou 3 (parada) nesse registrador (servidor-local/testes/falha_cr3.py).
EMULA_STATUS = os.getenv("SIM_EMULA_STATUS", "0") == "1"
SIM_MOVE_TIME = float(os.getenv("SIM_MOVE_TIME", 1))
STATUS_TEXTO = {0: "pronto", 1: "em movimento", 2: "ALARME", 3: "PARADO"}

# --- Mapeamento de Registradores para Legibilidade ---
REGISTER_MAP = {
    4000: "OP_MODE",
    4001: "PICK_SIGN",
    4002: "PICK_X",
    4003: "PICK_Y",
    4004: "PICK_Z",
    4005: "PLACE_SIGN",
    4006: "PLACE_X",
    4007: "PLACE_Y",
    4008: "PLACE_Z",
    4009: "STATUS",
}

logging.basicConfig(level=logging.INFO)
_logger = logging.getLogger(__name__)

def emular_status(slave_context, pendente_desde):
    """Faz o papel do programa do controlador: STATUS 1 (movimento) vira 0 (pronto)."""
    if slave_context.getValues(3, REG_STATUS, count=1)[0] != 1:
        return None
    agora = time.monotonic()
    if pendente_desde is None:
        return agora
    if agora - pendente_desde >= SIM_MOVE_TIME:
        slave_context.setValues(3, REG_STATUS, [0])
        return None
    return pendente_desde


async def monitoring_task(context):
    """Uma tarefa que monitora e exibe os valores dos registradores periodicamente."""
    _logger.info("Iniciando tarefa de monitoramento de registradores.")
    
    # Dicionário para armazenar o último estado conhecido dos registradores
    last_values = {}
    pendente_desde = None

    while True:
        try:
            # Pega o contexto do slave (unidade 1 por padrão)
            slave_context = context[0]
            if EMULA_STATUS:
                pendente_desde = emular_status(slave_context, pendente_desde)
            
            # Lê os valores dos Holding Registers (código de função 3)
            # a partir do endereço inicial
            current_values = slave_context.getValues(3, START_ADDRESS, count=REGISTER_COUNT)
            
            # Verifica se os valores mudaram desde a última leitura
            if current_values != last_values.get('raw'):
                
                print("--- Simulador de Robô Modbus TCP ---")
                print(f"Ouvindo em: {HOST}:{PORT}\n")
                print("Estado Atual dos Registradores:")
                print("-----------------------------------")
                
                # Exibe os valores formatados
                for i, value in enumerate(current_values):
                    address = START_ADDRESS + i
                    name = REGISTER_MAP.get(address, f"REG_{address}")
                    
                    # Decodifica as coordenadas para melhor visualização
                    if "_X" in name or "_Y" in name or "_Z" in name:
                        coord_value = f"{value / 100.0:.2f}"
                        print(f"  {name:<12} (Addr: {address}): {value:<5} -> {coord_value} mm")
                    elif name == "STATUS":
                        print(f"  {name:<12} (Addr: {address}): {value:<5} -> {STATUS_TEXTO.get(value, '?')}")
                    else:
                        print(f"  {name:<12} (Addr: {address}): {value}")
                
                print("-----------------------------------\n")
                print("Aguardando comandos do cliente...")

                # Atualiza o último estado conhecido
                last_values['raw'] = current_values

            await asyncio.sleep(0.1 if EMULA_STATUS else 0.5) # Intervalo de atualização
            
        except Exception as e:
            _logger.error(f"Erro na tarefa de monitoramento: {e}")
            await asyncio.sleep(2) # Espera um pouco antes de tentar novamente


async def run_async_server():
    """Configura e executa o servidor Modbus TCP assíncrono."""
    _logger.info("Configurando o servidor Modbus...")

    # Inicializa o bloco de dados com zeros. O ModbusSlaveContext do pymodbus 3.x soma 1 ao
    # endereço pedido pelo cliente (4000 -> 4001 no bloco), por isso o bloco tem um registrador
    # a mais: sem isso a escrita em 4008 (PLACE_Z) é recusada com IllegalAddress.
    data_block = ModbusSequentialDataBlock(START_ADDRESS, [0] * (REGISTER_COUNT + 1))
    
    # Cria o contexto do slave, que armazena os dados
    # 'hr' significa 'Holding Registers'
    slave_context = ModbusSlaveContext(hr=data_block)
    
    # Cria o contexto do servidor, que pode conter múltiplos slaves
    server_context = ModbusServerContext(slaves=slave_context, single=True)

    # Informações de identificação do dispositivo (opcional)
    identity = ModbusDeviceIdentification()
    identity.VendorName = "Pymodbus"
    identity.ProductCode = "SIM"
    identity.VendorUrl = "https://github.com/riptideio/pymodbus/"
    identity.ProductName = "Modbus Robot Simulator"
    identity.ModelName = "Simulator v1.0"
    identity.MajorMinorRevision = "1.0"

    # Cria a tarefa de monitoramento para rodar em paralelo com o servidor
    asyncio.create_task(monitoring_task(server_context))

    # Inicia o servidor TCP
    _logger.info(f"Servidor Modbus TCP iniciado e escutando em {HOST}:{PORT}")
    if EMULA_STATUS:
        _logger.info(f"Emulando o handshake do STATUS ({REG_STATUS}): movimento de {SIM_MOVE_TIME:g} s")
    server = await StartAsyncTcpServer(
        context=server_context,
        identity=identity,
        address=(HOST, PORT),
    )
    return server

if __name__ == "__main__":
    try:
        # Executa a função principal do servidor
        asyncio.run(run_async_server(), debug=False)
    except KeyboardInterrupt:
        print("\nServidor encerrado pelo usuário.")
    except Exception as e:
        _logger.error(f"Não foi possível iniciar o servidor: {e}")