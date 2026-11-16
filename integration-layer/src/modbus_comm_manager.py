# pymodbus 3.x (testado com 3.8.6). Na 2.x o import era pymodbus.client.sync e o
# argumento da unidade era unit=; na 3.x é slave= e count= precisa ser nomeado.
from pymodbus.client import ModbusTcpClient
import logging
import threading
import time

log = logging.getLogger(__name__)

class ModbusCommManager:
    def __init__(self, host, port=502):
        self.client = ModbusTcpClient(host, port=port)
        self.connected = False
        self.callback = None  # Callback é opcional
        self._watch_threads = []

    def set_callback(self, callback):
        """Define uma função de callback para ser chamada após leituras."""
        self.callback = callback

    def connect(self):
        self.connected = self.client.connect()
        if self.connected:
            print("✅ Conectado ao servidor Modbus.")
        else:
            print("❌ Falha ao conectar ao servidor Modbus.")

    def disconnect(self):
        self.client.close()
        print("🔌 Conexão encerrada.")

    def read_holding_register(self, address, count=1, unit=1):
        if not self.connected:
            print("⚠️ Não conectado.")
            return None

        result = self.client.read_holding_registers(address, count=count, slave=unit)
        if result.isError():
            print("❌ Erro ao ler registrador.")
            return None

        if self.callback:
            self.callback("holding_register", address, result.registers)

        return result.registers

    def write_single_register(self, address, value, unit=1):
        if not self.connected:
            print("⚠️ Não conectado.")
            return False

        result = self.client.write_register(address, value, slave=unit)
        if result.isError():
            print("❌ Erro ao escrever no registrador.")
            return False

        return True

    def read_coil(self, address, count=1, unit=1):
        if not self.connected:
            print("⚠️ Não conectado.")
            return None

        result = self.client.read_coils(address, count=count, slave=unit)
        if result.isError():
            print("❌ Erro ao ler coil.")
            return None

        if self.callback:
            self.callback("coil", address, result.bits)

        return result.bits

    def write_coil(self, address, value, unit=1):
        if not self.connected:
            print("⚠️ Não conectado.")
            return False

        result = self.client.write_coil(address, value, slave=unit)
        if result.isError():
            print("❌ Erro ao escrever na coil.")
            return False

        return True

    def read_discrete_inputs(self, address, count=1, unit=1):
        if not self.connected:
            print("⚠️ Não conectado.")
            return None

        result = self.client.read_discrete_inputs(address, count=count, slave=unit)
        if result.isError():
            print("❌ Erro ao ler entrada discreta.")
            return None

        if self.callback:
            self.callback("discrete_input", address, result.bits)

        return result.bits

    def watch_register(self, address, tipo='holding', intervalo=1.0, unit=1):
        """Inicia monitoramento de um registrador. Callback será chamado se o valor mudar."""
        def watch_loop():
            ultimo_valor = None
            while self.connected:
                if tipo == 'holding':
                    result = self.read_holding_register(address, count=1, unit=unit)
                elif tipo == 'coil':
                    result = self.read_coil(address, count=1, unit=unit)
                elif tipo == 'discrete_input':
                    result = self.read_discrete_inputs(address, count=1, unit=unit)
                else:
                    print(f"❌ Tipo de registrador '{tipo}' não suportado.")
                    return

                if result is not None:
                    valor_atual = result[0] if isinstance(result, list) and len(result) > 0 else result
                    if valor_atual != ultimo_valor:
                        if self.callback:
                            self.callback(f"{tipo}_watch", address, valor_atual)
                        ultimo_valor = valor_atual
                time.sleep(intervalo)
        

        thread = threading.Thread(target=watch_loop, daemon=True)
        thread.start()
        self._watch_threads.append(thread)
        print(f" Iniciado monitoramento de '{tipo}' no endereço {address}.")
