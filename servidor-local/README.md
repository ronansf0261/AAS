# Servidor AAS local — OPC UA + MQTT sem o hub do laboratório

Roda a AAS do Dobot CR3 nesta máquina só com software aberto: **asyncua** (servidor OPC UA),
**Eclipse Mosquitto** (broker MQTT) e **pymodbus** (simulador do CR3). Não usa a imagem
`aas_core_v1.1.2`, o MongoDB/discovery (192.168.100.21) nem o broker do laboratório.

```
 Orquestrador / UaExpert
        │ OPC UA (4886)
        ▼
 aas_local.py  ── AAS DobotCR3_1 + ponte do laboratório (educational-robot-aas/src)
        │ MQTT spacexlab/AAS/dobot_cr3/command        ▲ .../state {"operational_state": "Idle"}
        ▼                                             │
 Mosquitto (1883) ──────────► gateway_mqtt.py (integration-layer) ──Modbus TCP──► CR3 (ou simulador 5020)
```

É o **contrato Hermes**: servidor AAS, ponte OPC UA ↔ MQTT e mensagens são os mesmos do Robô
Educacional. Só o gateway muda (Raspberry Pi + G-code no Robô B; Modbus TCP no CR3).

O Robô Educacional roda do mesmo jeito: `aas_local.py` carrega `EducationalRobot_V2.aasx.xml`
(porta 4885), com a mesma ponte. O gateway é o da Raspberry (`raspberrypi-integration/main.py`,
sem alteração), e no lugar do Arduino entra `testes/simulador_arduino.py`.

## O que tem nesta pasta

| Arquivo | Para que serve |
| --- | --- |
| `aas_local.py` | Servidor OPC UA que substitui o `aas_core`: carrega o NodeSet2 e roda a pasta `src/` da camada de integração. |
| `core/` | Imitação do pacote `core` do `aas_core` (`logger`, `Entrypoint`, `BaseSubmodel`). Por isso o `src/` roda sem alteração. |
| `mosquitto.conf` | Configuração do broker para acesso pela rede. |
| `iniciar_teste.ps1` | Abre cada componente numa janela. |
| `testes/cliente_orquestrador.py` | Faz o papel do orquestrador: escreve posições e Start, espera Idle ou Error. `--robo cr3` ou `--robo educacional`. |
| `testes/simulador_arduino.py` | Simula o Arduino do Robô Educacional (firmware RobotArm_V3) por TCP e mostra o G-code recebido. |
| `testes/gateway_robo_b.py` | Roda o gateway da Raspberry neste PC sem alterar o código dele (porta serial por `SERIAL_PORT`). |
| `testes/falha_cr3.py` | Injeta parada ou alarme no simulador do CR3 (registrador STATUS 4009), para ensaiar o CA-07. |

O orquestrador de verdade, com sequências de 20 ciclos e evidências do FAT, fica em
`C:\AAS\orquestrador` (veja o README de lá). O `cliente_orquestrador.py` continua como teste
rápido de um ciclo.
| `ferramentas/adiciona_grabber.py` | Acrescenta o submodelo Grabber na AAS do CR3 (já foi rodado). |
| `requirements.txt` | Bibliotecas Python com versão fixa. |
| `Dockerfile`, `docker-compose.yaml`, `.dockerignore` | Deploy em Docker dos dois robôs (seção 3.1). |

## 1. Instalação (uma vez)

Pré-requisito: Python 3.9 ou mais novo. Em PowerShell, a partir de `C:\AAS`:

```powershell
# Ambiente Python isolado
python -m venv .venv
.venv\Scripts\python -m pip install -r servidor-local\requirements.txt

# Broker MQTT (pede permissão de administrador). O instalador cria o serviço "mosquitto".
winget install -e --id EclipseFoundation.Mosquitto

# Robô Educacional: o gateway da Raspberry usa sintaxe do Python 3.10+ (roda em python:3.11 no Docker)
winget install -e --id Python.Python.3.11 --scope user
& "$env:LOCALAPPDATA\Programs\Python\Python311\python.exe" -m venv .venv-robo-b
.venv-robo-b\Scripts\python -m pip install -r raspberrypi-integration\requirements.txt

# Para ver o MQTT fora do terminal (opcional)
winget install -e --id thomasnordquist.MQTT-Explorer
```

Cliente OPC UA: **UaExpert** (gratuito, com cadastro, em unified-automation.com) ou o
**opcua-client**, aberto: `.venv\Scripts\pip install opcua-client`, depois `.venv\Scripts\opcua-client`.

Conferência:

```powershell
Get-Service mosquitto                       # Status: Running
.venv\Scripts\python -c "import asyncua, aiomqtt, gmqtt, pymodbus; print('ok')"
```

## 2. Configuração

**Portas:** OPC UA **4886** (a 4840 desta máquina é do `opcualds`, o Local Discovery Server),
MQTT **1883**, simulador Modbus **5020** (no CR3 real é a 502).

**Broker só nesta máquina** (padrão): o serviço `mosquitto` já escuta em `127.0.0.1:1883`, sem
senha. Não precisa configurar nada.

**Broker para a rede** (quando a Raspberry Pi ou o PC do CR3 precisarem acessar). Em PowerShell
como administrador:

```powershell
Stop-Service mosquitto
& "C:\Program Files\mosquitto\mosquitto.exe" -c C:\AAS\servidor-local\mosquitto.conf -v
New-NetFirewallRule -DisplayName "Mosquitto 1883" -Direction Inbound -Protocol TCP -LocalPort 1883 -Action Allow
New-NetFirewallRule -DisplayName "AAS OPC UA 4886" -Direction Inbound -Protocol TCP -LocalPort 4886 -Action Allow
```

Para deixar fixo no serviço, copie `mosquitto.conf` por cima de
`C:\Program Files\mosquitto\mosquitto.conf` e rode `Restart-Service mosquitto`.

**Brokers públicos** (test.mosquitto.org, broker.hivemq.com, porta 1883) servem como plano B
**só com o simulador**: qualquer pessoa pode publicar nos tópicos. Nunca use com o CR3 real.

**Variáveis** (todas têm padrão local):

| Onde | Variável | Padrão |
| --- | --- | --- |
| `aas_local.py` | `MQTT_HOST`, `MQTT_PORT`, `ASSET_ID` (ou `--mqtt-host`, `--mqtt-port`, `--asset-id`) | localhost, 1883, dobot_cr3 |
| `gateway_mqtt.py` | `MQTT_HOST`, `MQTT_PORT`, `ASSET_ID` | localhost, 1883, dobot_cr3 |
|  | `MODBUS_HOST`, `MODBUS_PORT` | localhost, 5020 |
|  | `AAS_OPCUA_URL`, `MOVE_TIME` | opc.tcp://127.0.0.1:4886, 1 s |
| `monitorarModbus.py` | `MODBUS_SIM_HOST`, `MODBUS_SIM_PORT` | localhost, 5020 |

Use `127.0.0.1` e não `localhost` nas URLs OPC UA. No Windows, `localhost` tenta IPv6 antes e
cada conexão custa cerca de 2 s.

## 3. Teste de ponta a ponta (contrato Hermes)

Atalho que abre tudo (`-Robo Ambos` abre os dois robôs, veja "Teste de troca" abaixo):

```powershell
powershell -ExecutionPolicy Bypass -File servidor-local\iniciar_teste.ps1
```

Ou à mão, um terminal por linha (a partir de `C:\AAS`):

```powershell
mosquitto_sub -h localhost -t "spacexlab/AAS/#" -v                                 # monitor (em C:\Program Files\mosquitto)
cd integration-layer; ..\.venv\Scripts\python src\monitorarModbus.py              # simulador do CR3
.venv\Scripts\python servidor-local\aas_local.py -f DobotCR3_1.aasx.xml --resources integration-layer\resources --src educational-robot-aas\src --asset-id dobot_cr3
cd integration-layer; ..\.venv\Scripts\python -m src.gateway_mqtt                 # gateway CR3
```

Espere uns 15 s (a ponte do laboratório só assina o `OperationalState` 10 s depois de subir) e:

```powershell
.venv\Scripts\python servidor-local\testes\cliente_orquestrador.py                       # ciclo válido
.venv\Scripts\python servidor-local\testes\cliente_orquestrador.py --pick 100 50 50      # dentro da cúpula
.venv\Scripts\python servidor-local\testes\cliente_orquestrador.py --calibrate           # só home
```

Resultado obtido em 04/11/2026:

| Teste | Resultado |
| --- | --- |
| pick (200, 150, 100), place (−200, 150, 100) | `Idle` em 3,6 s (3 movimentos × 1 s). Simulador: PICK_X 20000, PLACE_SIGN 1, PLACE_Z gravado em 4008. |
| pick (100, 50, 50) — dentro da cúpula | `Error: Coordinates Out of Bounds` |
| pick (300, 150, 100) — fora da caixa | `Error: Coordinates Out of Bounds` |
| `--calibrate` | `Idle` em 1,2 s |

Mensagens vistas no monitor MQTT:

```
spacexlab/AAS/dobot_cr3/command {"data": {"cmd": "start", "in_coord": {"x": "200.0", "y": "150.0", "z": "100.0"}, "out_coord": {"x": "-200.0", "y": "150.0", "z": "100.0"}, "end_effector": "Magnetic", "gripper_open": "0", "gripper_close": "0"}}
spacexlab/AAS/dobot_cr3/state {"operational_state": "Idle"}
```

**UaExpert:** *Add Server → Advanced*, Endpoint URL `opc.tcp://127.0.0.1:4886`, Security
Policy **None**, autenticação **Anonymous**. A AAS aparece em
`Objects/AASAssetAdministrationShell:DobotCR3`. Para comandar à mão, escreva os valores em
`PickAndPlace/PickAndPlacePositioning/GripperControl/PickPosition/XPosition/Value` (texto, em
mm) e depois `Start` em `.../OperationalState/Value`.

### Robô Educacional (Robô B)

```powershell
powershell -ExecutionPolicy Bypass -File servidor-local\iniciar_teste.ps1 -Robo Educacional
```

Ou à mão (a partir de `C:\AAS`):

```powershell
mosquitto_sub -h localhost -t "spacexlab/AAS/0000_0000_0000_0000/#" -v
.venv-robo-b\Scripts\python servidor-local\testes\simulador_arduino.py                  # Arduino simulado (TCP 7777)
.venv\Scripts\python servidor-local\aas_local.py -f EducationalRobot_V2.aasx.xml --resources educational-robot-aas\resources --src educational-robot-aas\src --asset-id 0000_0000_0000_0000 --porta 4885
.venv-robo-b\Scripts\python servidor-local\testes\gateway_robo_b.py                     # gateway da Raspberry
```

Espere uns 15 s e rode:

```powershell
.venv\Scripts\python servidor-local\testes\cliente_orquestrador.py --robo educacional
.venv\Scripts\python servidor-local\testes\cliente_orquestrador.py --robo educacional --calibrate
```

O perfil `educacional` usa os valores de `raspberrypi-integration/payload_template.json`: pick
(140, 120, −62), place (−140, 120, −62), garra abre 180 e fecha 45. O ASSET_ID
`0000_0000_0000_0000` é o mesmo do docker-compose do laboratório.

Resultado obtido em 04/11/2026:

| Teste | Resultado |
| --- | --- |
| Ciclo pick → place, garra paralela | `Idle` em 23 s. 11 comandos G-code: M3S180, desce em F20, M3S45, sobe, ponto intermediário X0 Y180 (cruzou a base), place, M3S180, home G0 X0 Y185 Z120. |
| `--calibrate` | `G28` → `INFO: HOMING COMPLETE` → `Idle` em 1,7 s |

Diferenças entre os gateways que aparecem no teste:
- O gateway do Robô B **não valida coordenadas** (o do CR3 recusa pontos fora dos limites e da
  cúpula). A AAS do Robô Educacional também não tem `TechnicalData/CoordinateLimits`.
- O gateway do Robô B usa a home fixa **(0, 185, 120)**; a HomePosition da AAS é (0, 147, 120)
  e não é lida (pendência já anotada no projeto).

Com o Arduino real ligado no USB deste PC: `iniciar_teste.ps1 -Robo Educacional -SerialPort COM3`
(veja a porta no Gerenciador de Dispositivos).

### Teste de troca (os dois robôs ao mesmo tempo)

```powershell
powershell -ExecutionPolicy Bypass -File servidor-local\iniciar_teste.ps1 -Robo Ambos
```

Abre 8 janelas, com prefixo `[CR3]` ou `[Robô B]` no título. Ficam dois servidores AAS (4886 e
4885) com **o mesmo código** (`aas_local.py` + `educational-robot-aas/src`), o mesmo broker e o
mesmo contrato de mensagem. Só o gateway muda. O mesmo cliente comanda os dois:

```powershell
.venv\Scripts\python servidor-local\testes\cliente_orquestrador.py --robo cr3
.venv\Scripts\python servidor-local\testes\cliente_orquestrador.py --robo educacional
```

Os dois rodam juntos sem conflito: portas próprias (OPC UA 4886/4885, Modbus 5020, serial
TCP 7777), tópicos próprios e `ApplicationUri` próprio em cada servidor
(`urn:hermes:aas:<ASSET_ID>:<porta>`). Assim o UaExpert não confunde um servidor com o outro.
Teste feito em 04/11/2026: 3 rodadas com ciclos **simultâneos** nos dois robôs (CR3 `Idle` em
cerca de 3,3 s, Robô B em cerca de 23 s), com sessões OPC UA abertas nos dois servidores o tempo
todo.

O lançador pode ser rodado de novo a qualquer momento. Ele **mantém** o que já está rodando e
reabre só o que estiver fechado; não duplica nem disputa portas.

**Cuidado nas janelas:** `Ctrl+C` **sem texto selecionado encerra o programa** daquela janela.
Para copiar, selecione o texto antes ou use o botão direito. Se fechar uma janela sem querer,
rode o lançador de novo.

### Modo antigo (OPC UA → Modbus no mesmo processo, sem MQTT)

O `src/` do integration-layer continua funcionando dentro do servidor:

```powershell
cd integration-layer
..\.venv\Scripts\python ..\servidor-local\aas_local.py -f DobotCR3_1.aasx.xml --porta 4893
..\.venv\Scripts\python ..\servidor-local\testes\cliente_orquestrador.py --url opc.tcp://127.0.0.1:4893
```

Resultado: ciclo `Idle` em 3,4 s, recusa na cúpula e `--calibrate` → `Idle`.

## 3.1 Deploy em Docker (os dois robôs em contêineres)

Substitui as janelas do `iniciar_teste.ps1`: o mesmo ambiente, em 7 contêineres que sobem com um
comando e voltam sozinhos se caírem. Usa as mesmas portas, então **rode um ou outro**.

| Contêiner | Papel | Porta no Windows |
| --- | --- | --- |
| `hermes-mosquitto` | broker MQTT (Eclipse Mosquitto 2.0.20) | 1883 |
| `hermes-aas-cr3` | servidor AAS do CR3 + ponte OPC UA ↔ MQTT | 4886 |
| `hermes-gateway-cr3` | gateway MQTT → Modbus TCP do CR3 | — |
| `hermes-sim-cr3` | simulador Modbus do controlador do CR3 | — |
| `hermes-aas-robo-b` | servidor AAS do Robô Educacional + ponte | 4885 |
| `hermes-gateway-robo-b` | gateway da Raspberry (imagem do próprio `raspberrypi-integration`) | — |
| `hermes-sim-arduino-b` | simulador do Arduino do Robô Educacional | — |

Arquivos: `Dockerfile` (imagem Python com as bibliotecas), `docker-compose.yaml` e `.dockerignore`.
O código entra por volume (só leitura); mudou o código, basta `docker compose restart <serviço>`.

**Uma vez:** o serviço `mosquitto` do Windows ocupa a porta 1883. Em PowerShell como administrador:

```powershell
Stop-Service mosquitto
Set-Service mosquitto -StartupType Manual        # não volta a subir sozinho com o Windows
```

**Subir** (o Docker Desktop precisa estar aberto; ele não abre sozinho com o Windows):

```powershell
cd C:\AAS\servidor-local
docker compose up -d --build        # --build só na primeira vez ou se mudar o Dockerfile
docker compose ps                   # os dois aas-* e o mosquitto aparecem como (healthy)
```

**Testar** (espere uns 15 s depois de subir):

```powershell
cd C:\AAS
.venv\Scripts\python servidor-local\testes\cliente_orquestrador.py --robo cr3
.venv\Scripts\python servidor-local\testes\cliente_orquestrador.py --robo educacional

cd C:\AAS\orquestrador                                   # sequência completa, com evidências
..\.venv\Scripts\python orquestrador.py sequencias\cr3.json
```

**Acompanhar** (um terminal por comando, a partir de `C:\AAS\servidor-local`):

```powershell
docker compose logs -f aas-cr3 gateway-cr3                 # servidor e gateway do CR3
docker compose logs -f sim-cr3                             # registradores Modbus
docker compose logs -f aas-robo-b gateway-robo-b           # servidor e gateway do Robô B
docker compose logs -f sim-arduino-b                       # G-code recebido
docker exec -it hermes-mosquitto mosquitto_sub -t "spacexlab/#" -v    # mensagens MQTT
```

UaExpert e MQTT Explorer continuam nos mesmos endereços: `opc.tcp://127.0.0.1:4886`,
`opc.tcp://127.0.0.1:4885` e `127.0.0.1:1883`.

**Parar e reiniciar:**

```powershell
docker compose stop                 # para, mantém os contêineres
docker compose start                # sobe de novo
docker compose restart gateway-cr3  # reinicia um serviço (ex.: depois de editar o código)
docker compose down                 # remove os contêineres (as imagens ficam)
```

**Máquina de estados e falhas.** No Docker, o gateway do CR3 usa o registrador de status
(4009) para saber quando o movimento termina, e o simulador faz o papel do programa do
controlador. A porta do simulador fica aberta só nesta máquina (`127.0.0.1:5020`) para ensaiar
falhas:

```powershell
cd C:\AAS
.venv\Scripts\python servidor-local\testes\falha_cr3.py --parada     # robô parado -> Stopped
.venv\Scripts\python servidor-local\testes\falha_cr3.py --alarme     # alarme -> Error: Robot Alarm
docker stop hermes-sim-cr3                                           # perda de conexão -> Error
```

Depois de uma falha, `Calibrate` (pela AAS ou `orquestrador.py --robo cr3 --calibrar`) leva o
robô de volta a `Idle`.

**CR3 real** no lugar do simulador (o contêiner alcança a rede local pelo Windows).
`CR3_REG_STATUS = "0"` volta ao tempo fixo enquanto o programa do controlador não tiver o
handshake do registrador 4009 (README do `integration-layer`):

```powershell
$env:CR3_MODBUS_HOST = "192.168.5.1"; $env:CR3_MODBUS_PORT = "502"; $env:CR3_REG_STATUS = "0"
docker compose up -d gateway-cr3
```

O Arduino real do Robô B não entra no Docker do Windows (o Docker Desktop não repassa portas
COM). Para o robô físico, o gateway roda na Raspberry Pi, como no README de `raspberrypi-integration`,
apontando para o broker desta máquina.

**Voltar para o modo janelas:** `docker compose down`, `Start-Service mosquitto` (como
administrador) e `iniciar_teste.ps1`. O lançador se recusa a abrir com os contêineres no ar.

Resultado obtido: partida limpa dos 7 contêineres (gateway do CR3 só sobe depois de o servidor AAS
responder); ciclo do CR3 `Idle` em 3,2 s, do Robô B em 23,2 s; pick na cúpula recusado com
`Error: Coordinates Out of Bounds`; calibração dos dois robôs `Idle` em 1,3 s e 1,8 s.

## 4. AAS do CR3: o que mudou

`ferramentas/adiciona_grabber.py --home 200 150 150` foi rodado uma vez e alterou
`integration-layer/resources/DobotCR3_1.aasx.xml` e `CR3.aasx` (dá para voltar com `git restore`):

- **Grabber** copiado do Robô Educacional V2 (id `https://example.com/ids/sm/4310_6032_2611_0426`,
  sem "Grabber" no texto do id). GripperType = `Magnetic`, o mesmo de PickAndPlace/Gripper.
  OpeningWidth e ClampingWidth vieram com 0: preencha com os valores da garra do CR3.
- **HomePosition** foi de (120, 80, 40), que fica **dentro da cúpula proibida** (raio 220 mm),
  para **(200, 150, 150)**, um valor provisório. Confirme na célula.

Para editar no AASX Package Explorer, abra `CR3.aasx`, ajuste os valores e exporte o NodeSet2
(I4AAS) por cima de `DobotCR3_1.aasx.xml`, como antes.

## 5. Notas técnicas

- **Enums do export I4AAS.** O AASX Package Explorer grava `<Type>20</Type>`, mas a asyncua 1.1.x
  espera `Submodel_20` e aborta a carga. O `aas_local.py` aceita os dois formatos em memória,
  sem alterar o arquivo. O mesmo vale para o namespace 3 não declarado.
- **Avisos na carga** (`AASMimeDataType`, referências `HasEncoding`) vêm do export original e
  ficam ocultos. Não afetam a AAS.
- **OPC UA em contêiner.** O servidor asyncua devolve ao cliente o mesmo endereço que ele usou
  para conectar (`match_discovery_endpoint_url`), então o UaExpert funciona pela porta mapeada
  sem configuração extra.

## 6. Próximos passos

- **CR3 real:** `iniciar_teste.ps1 -ModbusHost 192.168.5.1 -ModbusPort 502`. O programa do
  controlador precisa ler os registradores 4000–4008. Confira com ele a sequência do OP_MODE
  (hoje ele só vai a 1 na fase de place e na home) e troque o `MOVE_TIME` fixo pela leitura de
  um registrador de status.
- **Garra:** o contrato já leva `end_effector`, `gripper_open` e `gripper_close`, mas o mapa
  Modbus ainda não tem registrador para a garra.
- **Servidor do laboratório:** Dockerfile/compose para o gateway.
