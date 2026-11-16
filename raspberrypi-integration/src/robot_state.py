import logging
import asyncio

from .serial_handler import SerialController
from typing import Callable, Awaitable, Any, Optional

class RobotManager:
    """
    Robot state management control
    """

    __serial: SerialController
    __is_robot_busy: bool

    def __init__(self, port, baud_rate):
        self.__is_robot_busy = False
        self.__serial = SerialController(port=port, baudrate=baud_rate)

    async def start_robot(self):
        await self.__serial.connect()

    async def calibrate_robot(self, callback: Optional[Callable[..., Awaitable[Any]]] = None):
        if self._is_busy:
            logging.info("Robot is busy, cannot send GCODE")
            return

        self._set_busy()
        await self.__serial.calibrate_robot()
        self._set_free()

        if callback is not None:
            await callback()

    async def send_gcode(self, gcode: list[str], callback: Optional[Callable[..., Awaitable[Any]]] = None):
        if self._is_busy:
            logging.info("Robot is busy, cannot send GCODE")
            return

        self._set_busy()

        for command in gcode:
            await self.__serial.send_data(f"{command}\r\n")

            # Wait for OK for each command
            await self.__serial.send_data("G4S0.5\r\n")
            await self.__serial.wait_for_message("OK")

        await asyncio.sleep(0.3)
        self._set_free()
        logging.info("[ROBOT FREE]")

        if callback is not None:
            await callback()

    def _set_busy(self):
        self.__is_robot_busy = True

    def _set_free(self):
        self.__is_robot_busy = False

    @property
    def _is_busy(self):
        return self.__is_robot_busy
