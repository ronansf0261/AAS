import asyncio
import logging
import serial_asyncio
import serial.tools.list_ports


async def find_acm_and_usb_devices():
    """
    Busca dispositivos do tipo ACM e USB disponíveis no sistema.

    Retorna:
        List[str]: Uma lista de caminhos de dispositivos (ex.: '/dev/ttyACM0', '/dev/ttyUSB0').
    """
    devices = []

    # Listando portas disponíveis
    ports = serial.tools.list_ports.comports()
    for port in ports:
        # Filtrando portas que contenham 'ACM' ou 'USB' no nome
        if 'ACM' in port.device or 'USB' in port.device:
            devices.append(port.device)
    print(devices)
    return devices


async def validate_device(device, message=None, expected_response="ROBOT ONLINE"):
    """
    Valida se um dispositivo responde conforme esperado.

    Args:
        device (str): Caminho do dispositivo (ex.: '/dev/ttyACM0').
        message (str): Mensagem a ser enviada ao dispositivo.
        expected_response (str): Resposta esperada do dispositivo.

    Retorna:
        bool: True se o dispositivo respondeu conforme esperado, False caso contrário.
    """
    try:
        reader, writer = await serial_asyncio.open_serial_connection(
            url=device,
            baudrate=1000000
        )
        if message:
            writer.write(message.encode("utf-8"))
            await writer.drain()
        data = await asyncio.wait_for(reader.readuntil(separator=b"\n"), timeout=5)
        data = data.decode("utf-8").strip()
        if expected_response in data:
            return True
        else:
            return False
    except asyncio.TimeoutError:
        return False
    except Exception as e:
        return False
    finally:
        if 'writer' in locals():
            writer.close()
            await writer.wait_closed()


async def find_robot():
    devices = await find_acm_and_usb_devices()
    if not devices:
        logging.error("Nenhum dispositivo ACM ou USB encontrado.")
        return

    for device in devices:
        is_valid = await validate_device(device)
        if is_valid:
            logging.info(f"Dispositivo válido encontrado: {device}")
            return device

async def main():
    port = await find_robot()
    print("port", port)


if __name__ == "__main__":
    asyncio.run(main())
