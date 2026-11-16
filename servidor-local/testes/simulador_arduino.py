"""Simulador do Arduino do Robô Educacional (firmware RobotArm_V3) para testes sem hardware.

Faz o papel da placa Arduino + RAMPS na porta serial, só que por TCP: o gateway da Raspberry
abre a URL pyserial `socket://127.0.0.1:7777` como se fosse a porta serial.

Responde como o firmware (educational-robot-arduino-firmware/RobotArm_V3):
  - ao conectar:  INFO: ROBOT ONLINE  /  INFO: SEND G28 TO CALIBRATE   (HOME_ON_BOOT = false)
  - G28:          homing -> INFO: HOMING COMPLETE, posição (0, 185, 120) = INITIAL_X/Y/Z
  - G0 / G1:      INFO: LINEAR MOVE: [X:.. Y:.. Z:.. E:0.00] e o "movimento" (tempo pela distância e F)
  - G4 S<s>:      espera os movimentos anteriores terminarem, espera <s> segundos e responde OK
  - M3 S<ang>:    garra paralela (servo) no ângulo; M5 solta
  - M6 / M7:      eletroímã liga / desliga
Os comandos ficam numa fila e são executados um depois do outro, como no firmware.

Uso:
    python simulador_arduino.py --porta 7777 --vel 150
"""
import argparse
import asyncio
import math
import re
import time

HOME = (0.0, 185.0, 120.0)  # INITIAL_X, HIGH_SHANK_LENGTH + END_EFFECTOR_OFFSET, LOW_SHANK_LENGTH
CMD = re.compile(r"^([GM])(\d+)(.*)$")
PARAM = re.compile(r"([XYZEFSP])\s*(-?\d+(?:\.\d+)?)")


def agora():
    return time.strftime("%H:%M:%S")


class Robo:
    def __init__(self, vel, max_mov):
        self.vel, self.max_mov = vel, max_mov
        self.pos = list(HOME)
        self.servo = None
        self.ima = False
        self.calibrado = False
        self.comandos = 0

    def estado(self):
        garra = f"{self.servo:g}°" if self.servo is not None else "-"
        x, y, z = self.pos
        return (f"posição (X {x:7.1f}, Y {y:7.1f}, Z {z:7.1f}) mm | garra (servo) {garra:>5} | "
                f"eletroímã {'LIGADO' if self.ima else 'desligado'}")


async def atender(reader, writer, args):
    robo = Robo(args.vel, args.max_mov)
    fila: asyncio.Queue = asyncio.Queue()

    async def enviar(linha):
        writer.write((linha + "\r\n").encode())
        await writer.drain()
        print(f"{agora()}   -> {linha}")

    async def executar(linha):
        m = CMD.match(linha.replace(" ", "").upper()) if linha else None
        if not m:
            print(f"{agora()} ?? comando não reconhecido: {linha!r}")
            return
        letra, num, resto = m.group(1), int(m.group(2)), m.group(3)
        p = {k: float(v) for k, v in PARAM.findall(resto)}
        robo.comandos += 1
        print(f"{agora()} <- {linha}")

        if letra == "G" and num in (0, 1):
            alvo = [p.get("X", robo.pos[0]), p.get("Y", robo.pos[1]), p.get("Z", robo.pos[2])]
            dist = math.dist(robo.pos, alvo)
            vel = robo.vel * p.get("F", 300.0) / 300.0  # F300 = velocidade de referência
            t = min(max(dist / vel, 0.05), robo.max_mov) if vel > 0 else 0.05
            await enviar(f"INFO: LINEAR MOVE: [X:{alvo[0]:.2f} Y:{alvo[1]:.2f} Z:{alvo[2]:.2f} E:0.00]")
            await asyncio.sleep(t)
            robo.pos = alvo
            print(f"{agora()}    movimento de {dist:.1f} mm em {t:.2f} s -> {robo.estado()}")
        elif letra == "G" and num == 4:
            await asyncio.sleep(p.get("S", p.get("P", 0) / 1000))
            await enviar("OK")
        elif letra == "G" and num == 28:
            print(f"{agora()}    homing...")
            await asyncio.sleep(1.5)
            robo.pos, robo.calibrado = list(HOME), True
            await enviar("INFO: HOMING COMPLETE")
            print(f"{agora()}    {robo.estado()}")
        elif letra == "M" and num == 3:
            robo.servo = p.get("S", 180.0)
            print(f"{agora()}    garra paralela -> {robo.servo:g}°")
        elif letra == "M" and num == 5:
            robo.servo = p.get("S", 0.0)
            print(f"{agora()}    garra paralela solta -> {robo.servo:g}°")
        elif letra == "M" and num in (6, 7):
            robo.ima = num == 6
            print(f"{agora()}    eletroímã {'LIGADO' if robo.ima else 'desligado'}")
        else:
            print(f"{agora()}    (sem efeito no simulador)")

    async def executor():
        while True:
            await executar(await fila.get())

    print(f"\n{agora()} === Gateway conectado ({writer.get_extra_info('peername')}) ===")
    tarefa = asyncio.create_task(executor())
    await enviar("INFO: ROBOT ONLINE")
    await enviar("INFO: SEND G28 TO CALIBRATE")
    try:
        while True:
            dados = await reader.readline()
            if not dados:
                break
            linha = dados.decode(errors="replace").strip()
            if linha:
                fila.put_nowait(linha)
            else:
                print(f"{agora()} <- (linha vazia, ignorada pelo firmware)")
    except ConnectionError:
        pass
    finally:
        tarefa.cancel()
        writer.close()
        print(f"{agora()} === Gateway desconectado ({robo.comandos} comandos executados) ===")


async def main():
    ap = argparse.ArgumentParser(description="Simulador do Arduino do Robô Educacional")
    ap.add_argument("--host", default="127.0.0.1")
    ap.add_argument("--porta", type=int, default=7777)
    ap.add_argument("--vel", type=float, default=150.0, help="velocidade em mm/s com F300")
    ap.add_argument("--max-mov", type=float, default=3.0,
                    help="tempo máximo de um movimento, em s (o gateway desiste do OK após 5 s)")
    a = ap.parse_args()
    srv = await asyncio.start_server(lambda r, w: atender(r, w, a), a.host, a.porta)
    print("--- Simulador do Arduino do Robô Educacional (firmware RobotArm_V3) ---")
    print(f"Escutando em {a.host}:{a.porta}  ->  no gateway: SERIAL_PORT=socket://{a.host}:{a.porta}")
    print(f"Home após G28: {HOME}   velocidade de referência: {a.vel:g} mm/s em F300")
    print("Aguardando o gateway...")
    async with srv:
        await srv.serve_forever()


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\nSimulador encerrado.")
