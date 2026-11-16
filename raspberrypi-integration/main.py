import json
import aiomqtt
import asyncio
import logging

from src.robot_state import RobotManager
from src.env import get_env_variables
from src.gcode import convert_to_gcode
from src.serial_finder import find_robot

logging.basicConfig(level=logging.INFO)

async def start_mqtt_client(broker: str, port: int, topic_command: str, topic_feedback: str, robot_manager: RobotManager):
    async with aiomqtt.Client(broker, port) as client:
        logging.info(f"[CONNECTED TO MQTT BROKER {broker}:{port}]")

        await client.subscribe(topic_command)

        async def send_feedback():
            await client.publish(topic_feedback, payload=json.dumps({ "operational_state": "Idle" }))

        async for message in client.messages:
            try:
                payload = json.loads(message.payload)
                data = payload.get("data", {})
                command = data.get("cmd", {})
                end_effector = data.get("end_effector", "")
                gripper_open = data.get("gripper_open", "")
                gripper_close = data.get("gripper_close", "")

                # Retrocompatibilidade com a v1
                if not isinstance(end_effector, str) or end_effector == "":
                    end_effector = "Electromagnet"

                if not isinstance(command, str):
                    logging.error(f"Unknown data structure: {payload}")
                    continue

                if command.lower() == "start":
                    gcode_sequence = convert_to_gcode(data, end_effector, gripper_open, gripper_close)
                    if gcode_sequence:
                        asyncio.create_task(robot_manager.send_gcode(gcode_sequence, send_feedback))
                elif command.lower() == "calibrate":
                    asyncio.create_task(robot_manager.calibrate_robot(send_feedback))
                else:
                    logging.info(f"Command '{command}' not recognized.")

            except json.JSONDecodeError:
                logging.error("Error while decoding JSON payload")

            except Exception as e:
                logging.error(f"Error while processing message: {e}")


async def main():
    # serial_port, serial_baudrate = "/dev/ttyACM0", 115200
    broker, port, topic_command, topic_feedback, baud_rate = get_env_variables()

    serial_port = await find_robot()

    robot = RobotManager(serial_port, baud_rate)

    await robot.start_robot()
    await start_mqtt_client(broker, port, topic_command, topic_feedback, robot)


if __name__ == "__main__":
    asyncio.run(main())

