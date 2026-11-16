"""Movimentos do Dobot CR3 por Modbus TCP: lógica comum aos dois modos da camada.

- Modo OPC UA (pick_and_place.py): roda dentro do servidor AAS (aas_core ou aas_local.py).
- Modo gateway MQTT (gateway_mqtt.py): contrato Hermes, com máquina de estados.

Não depende de core/ nem de OPC UA. O mapa de registradores e a sequência de escrita são os
mesmos do pick_and_place.py original, porque o programa do controlador do CR3 depende deles:
  - pick:  escreve PICK_SIGN/X/Y/Z, espera o movimento, OP_MODE = 0
  - place: escreve PLACE_SIGN/X/Y/Z, OP_MODE = 1, espera, OP_MODE = 0
  - home:  escreve a home nos registradores de PLACE, OP_MODE = 1, espera, OP_MODE = 0
Coordenadas em mm; no Modbus vão como |valor| x 100 e o sinal de X/Y vai no registrador SIGN
(bit 0 = X negativo, bit 1 = Y negativo).

Fim do movimento, em dois modos:
  - tempo fixo (padrão): espera MOVE_TIME segundos;
  - registrador de status (status_reg, ex.: 4009): handshake com o programa do controlador.
    O gateway escreve 1 (PENDENTE) ao disparar o movimento; o controlador escreve 0 (PRONTO)
    ao terminar, 2 (ALARME) em alarme/colisão ou 3 (PARADO) em pausa/parada/emergência.
Nos dois modos, um pedido de parada (pedir_parada) interrompe a espera em até 0,1 s.
"""
import asyncio
import logging
import time

log = logging.getLogger("cr3_motion")

DEFAULT_OBJECT_HEIGHT = 0
# Tempo de espera de cada movimento no modo de tempo fixo.
SIMULATED_MOVE_TIME = 1  # segundos

MODBUS_REG_OP_MODE = 4000
MODBUS_REG_PICK_SIGN = 4001
MODBUS_REG_PICK_X = 4002
MODBUS_REG_PICK_Y = 4003
MODBUS_REG_PICK_Z = 4004
MODBUS_REG_PLACE_SIGN = 4005
MODBUS_REG_PLACE_X = 4006
MODBUS_REG_PLACE_Y = 4007
MODBUS_REG_PLACE_Z = 4008
MODBUS_REG_STATUS = 4009  # proposta de handshake com o programa do controlador (opcional)

STATUS_PRONTO = 0    # escrito pelo controlador: movimento concluído / robô pronto
STATUS_PENDENTE = 1  # escrito pelo gateway: movimento disparado
STATUS_ALARME = 2    # escrito pelo controlador: alarme ou colisão
STATUS_PARADO = 3    # escrito pelo controlador: pausa, botão de parada ou emergência

PICK_REGS = (MODBUS_REG_PICK_SIGN, MODBUS_REG_PICK_X, MODBUS_REG_PICK_Y, MODBUS_REG_PICK_Z)
PLACE_REGS = (MODBUS_REG_PLACE_SIGN, MODBUS_REG_PLACE_X, MODBUS_REG_PLACE_Y, MODBUS_REG_PLACE_Z)

# Zona proibida em forma de cúpula ao redor da base
FORBIDDEN_DOME_RADIUS = 220
FORBIDDEN_DOME_HEIGHT = 180

LIMIT_KEYS = ("MaxLimitX", "MinLimitX", "MaxLimitY", "MinLimitY", "MaxLimitZ", "MinLimitZ")


class MovimentoInterrompido(Exception):
    """Parada pedida pelo operador (comando Stop) ou informada pelo robô (STATUS = 3)."""

    def __init__(self, motivo):
        super().__init__(motivo)
        self.motivo = motivo


class FalhaMovimento(Exception):
    """Falha durante o movimento; `codigo` vai para o OperationalState como "Error: <codigo>"."""

    def __init__(self, codigo):
        super().__init__(codigo)
        self.codigo = codigo


def validate_coordinates(x, y, z, limits, point_name="Ponto", logger=log,
                         dome_radius=FORBIDDEN_DOME_RADIUS, dome_height=FORBIDDEN_DOME_HEIGHT):
    """Limites retangulares (CoordinateLimits da AAS) + zona de exclusão em cúpula."""
    x, y, z = float(x), float(y), float(z)

    # 1. Validação dos limites retangulares (caixa)
    if not (limits.get("MinLimitX", -float("inf")) <= x <= limits.get("MaxLimitX", float("inf"))):
        logger.error(f"Validação falhou! {point_name} X ({x}) está fora dos limites retangulares.")
        return False
    if not (limits.get("MinLimitY", -float("inf")) <= y <= limits.get("MaxLimitY", float("inf"))):
        logger.error(f"Validação falhou! {point_name} Y ({y}) está fora dos limites retangulares.")
        return False
    if not (limits.get("MinLimitZ", -float("inf")) <= z <= limits.get("MaxLimitZ", float("inf"))):
        logger.error(f"Validação falhou! {point_name} Z ({z}) está fora dos limites retangulares.")
        return False

    # 2. Zona proibida (cúpula): dentro do raio, y >= 0 e 0 <= z <= altura da cúpula
    is_in_forbidden_zone = (
        (x**2 + y**2 + z**2 <= dome_radius**2) and
        (y >= 0) and
        (0 <= z <= dome_height)
    )
    if is_in_forbidden_zone:
        logger.error(f"Validação falhou! {point_name} ({x:.1f}, {y:.1f}, {z:.1f}) está dentro da zona de exclusão da cúpula.")
        return False

    logger.info(f"Validação de coordenadas para '{point_name}' passou com sucesso.")
    return True


def process_coordinates_for_modbus(coords):
    x, y, z = float(coords[0]), float(coords[1]), float(coords[2])
    signs_value = 0
    if x < 0:
        signs_value += 1
    if y < 0:
        signs_value += 2
    return {"signs_value": signs_value,
            "x": int(abs(x) * 100),
            "y": int(abs(y) * 100),
            "z": int(abs(z) * 100)}


class CR3Motion:
    """Executa os movimentos escrevendo nos registradores 4000-4008 do controlador."""

    def __init__(self, modbus_client, limits=None, move_time=SIMULATED_MOVE_TIME, logger=log,
                 status_reg=None, move_timeout=30.0):
        self.modbus = modbus_client
        self.limits = limits if limits is not None else {}  # dict compartilhado com quem lê a AAS
        self.move_time = move_time
        self.log = logger
        self.status_reg = status_reg      # None = modo de tempo fixo
        self.move_timeout = move_timeout  # só no modo de status
        self._parada = None               # motivo da parada pedida, ou None

    # ------------------------------------------------------------------ parada
    def pedir_parada(self, motivo="Stop Requested"):
        self._parada = motivo

    def limpar_parada(self):
        self._parada = None

    def _checar_parada(self):
        if self._parada:
            raise MovimentoInterrompido(self._parada)

    def parar_robo(self):
        """Melhor esforço: OP_MODE = 0 (para o movimento). Não levanta exceção."""
        try:
            return bool(self.modbus.write_single_register(MODBUS_REG_OP_MODE, 0))
        except Exception as e:  # conexão já caída
            self.log.warning(f"Não foi possível escrever OP_MODE = 0: {e}")
            return False

    # ------------------------------------------------------------------ Modbus
    def validate(self, x, y, z, point_name="Ponto"):
        return validate_coordinates(x, y, z, self.limits, point_name, self.log)

    def _write(self, address, value):
        if not self.modbus.write_single_register(address, value):
            raise FalhaMovimento("Modbus Communication Failed")

    def _write_point(self, regs, coords):
        data = process_coordinates_for_modbus(coords)
        for reg, key in zip(regs, ("signs_value", "x", "y", "z")):
            self._write(reg, data[key])
        return data

    def _ler_status(self):
        regs = self.modbus.read_holding_register(self.status_reg, count=1)
        if not regs:
            raise FalhaMovimento("Modbus Communication Failed")
        return regs[0]

    def ler_status(self):
        """Status atual do robô (só no modo de status); None no modo de tempo fixo."""
        return None if self.status_reg is None else self._ler_status()

    def _marcar_pendente(self):
        if self.status_reg is not None:
            self._write(self.status_reg, STATUS_PENDENTE)

    async def _esperar_movimento(self):
        inicio = time.monotonic()
        if self.status_reg is None:
            while time.monotonic() - inicio < self.move_time:
                self._checar_parada()
                await asyncio.sleep(min(0.1, self.move_time))
            self._checar_parada()
            return
        while True:
            self._checar_parada()
            status = self._ler_status()
            if status == STATUS_PRONTO:
                return
            if status == STATUS_ALARME:
                raise FalhaMovimento("Robot Alarm")
            if status == STATUS_PARADO:
                raise MovimentoInterrompido("Robot Stopped")
            if time.monotonic() - inicio > self.move_timeout:
                raise FalhaMovimento("Motion Timeout")
            await asyncio.sleep(0.1)

    # ------------------------------------------------------------------ movimentos
    async def move_to_pick(self, pick):
        self._checar_parada()
        self.log.info(f"--- FASE 1: MOVENDO PARA A POSIÇÃO DE PICK ---")
        data = self._write_point(PICK_REGS, pick)
        self.log.info(f"Dados de PICK enviados ao robô (Modbus): {data}")
        self._marcar_pendente()
        await self._esperar_movimento()
        self._write(MODBUS_REG_OP_MODE, 0)
        self.log.info("✅ Robô na posição de PICK.")

    async def move_to_place(self, place):
        self._checar_parada()
        self.log.info(f"--- FASE 2: MOVENDO PARA A POSIÇÃO DE PLACE ---")
        data = self._write_point(PLACE_REGS, place)
        self.log.info(f"Dados de PLACE enviados ao robô (Modbus): {data}")
        self._marcar_pendente()
        self._write(MODBUS_REG_OP_MODE, 1)
        await self._esperar_movimento()
        self._write(MODBUS_REG_OP_MODE, 0)
        self.log.info("✅ Robô na posição de PLACE.")

    async def go_home(self, home):
        """Valida e move para a home (usa os registradores de PLACE). False se a home for inválida."""
        self._checar_parada()
        self.log.info(f"--- FASE 3: RETORNANDO À HOME POSITION ---")
        self.log.info(f"Home Position alvo: (X:{home[0]}, Y:{home[1]}, Z:{home[2]})")
        if not self.validate(*home, point_name="Home Position"):
            return False
        self._write_point(PLACE_REGS, home)
        self._marcar_pendente()
        self._write(MODBUS_REG_OP_MODE, 1)
        await self._esperar_movimento()
        self._write(MODBUS_REG_OP_MODE, 0)
        self.log.info("✅ Robô na Home Position.")
        return True
