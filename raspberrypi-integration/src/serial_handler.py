import sys
import logging
import asyncio
import serial_asyncio
import serial.tools.list_ports


class SerialController:

    _port: str
    _baudrate: int

    _reader: asyncio.StreamReader | None
    _writer: asyncio.StreamWriter | None

    def __init__(self, port: str | None = None, baudrate: int = 115200):
        self._port = port if port else self.find_serial_port()
        self._baudrate = baudrate
        self._reader = None
        self._writer = None

    def find_serial_port(self):
        ports = serial.tools.list_ports.comports()

        for port in ports:
            print("Port description:", port.description, "Port device:", port.device)
            if 'Arduino' in port.description or 'ttyACM' in port.device or 'ttyUSB' in port.device:
                return port.device  #'/dev/ttyACM0' or '/dev/ttyUSB0'

        raise IOError("No Arduino or relevant device found")

    async def connect(self):
        try:
            self._reader, self._writer = await serial_asyncio.open_serial_connection(url=self._port, baudrate=self._baudrate)

            await self.wait_for_message("INFO: ROBOT ONLINE")
            await self.calibrate_robot()

        except Exception as e:
            logging.error(f"Error while connecting to serial port: {e}")
            # Exit with error code
            sys.exit(-1)

    async def calibrate_robot(self):
        if self._writer is None:
            raise ValueError("Serial connection is not established")

        await self.send_data("G28\r\n")
        await self.wait_for_message("INFO: HOMING COMPLETE")

    async def send_data(self, data: str):
        if self._writer is None:
            raise ValueError("Serial connection is not established")

        self._writer.write(data.encode("utf-8"))

        await self._writer.drain()

    async def wait_for_message(self, message: str):
        if self._reader is None:
            raise ValueError("Serial connection is not established")

        retry_count = 0
        max_retries = 3

        while retry_count < max_retries:
            try:
                data = await asyncio.wait_for(self._reader.readuntil(separator=b"\r\n"), timeout=5)
                data = data.decode("utf-8").strip()

                if message in data:
                    print(f"RECEIVED -> {message}")
                    return
            except asyncio.TimeoutError:
                retry_count += 1
                print(f"Timeout waiting for message, retry {retry_count}/{max_retries}")
                if retry_count < max_retries:
                    await self.send_data("G4S0.5\r\n")
                else:
                    raise TimeoutError("Timed out while waiting for message")

