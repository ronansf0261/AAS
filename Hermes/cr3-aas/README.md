# AAS do Dobot CR3 (Robô A) e servidor OPC UA

## O que tem nesta pasta

| Caminho | Para que serve |
| --- | --- |
| `aas/DobotCR3AAS.aasx` | AAS do CR3 para abrir e editar no AASX Package Explorer (metamodelo AAS V2.0, mesmo formato do Robô Educacional). |
| `resources/DobotCR3AAS.aasx.xml` | A mesma AAS em NodeSet2 (I4AAS). É o arquivo que o servidor OPC UA carrega. |
| `docker-compose.cr3.yaml` e `.env.example` | Sobem a AAS do CR3 com a imagem `aas_core` do laboratório, na porta 4886. |
| `teste/` | Servidor de teste (substitui o `aas_core` no seu PC), gateway simulado e cliente no papel do orquestrador. |
| `ferramentas/` | Scripts que geram o AASX e o NodeSet2 a partir dos arquivos do Robô Educacional. |

## Estrutura da AAS

| Submodelo | Conteúdo |
| --- | --- |
| Nameplate | Fabricante DOBOT (Shenzhen Yuejiang Technology Co., Ltd.), produto CR3 Collaborative Robot, país CN. |
| PickAndPlace | **Mesma estrutura do Robô Educacional**: ArmWorkspace, PickAndPlacePositioning/GripperControl (PickPosition, PlacePosition, OperationalState) e Gripper. |
| Grabber | **Mesma estrutura do Robô Educacional**: GripperType, ParallelGripping (OpeningWidth, ClampingWidth) e Limits. |
| TechnicalData (novo) | RobotType, NumberOfAxes (6), Payload (3 kg), WorkingRadius (620 mm), Repeatability (0,02 mm), Weight (16,5 kg), MaxTCPSpeed (2 m/s) e a coleção Communication (Modbus TCP, IP 192.168.5.1, porta 502). |

PickAndPlace e Grabber têm exatamente os mesmos nomes do Robô Educacional porque a camada
de integração (`educational-robot-aas/src`) acha os nós pelo nome. Assim o mesmo código
serve aos dois robôs e só o `ASSET_ID` muda. É isso que sustenta o teste de troca.

## Campos a preencher ou validar

- **Etiqueta/manual do robô:** SerialNumber, YearOfConstruction, Street e Zipcode estão vazios.
- **Célula (Fase 6.1):** HomePosition está em (0, 0, 0) provisório. WorkspaceLimits está em
  620 mm, que é o raio máximo do CR3; ajuste para os limites reais da célula.
- **Garra do CR3:** GripperType, RatedLoad, StrokeLength e MaxHoldingWeight estão com valores
  provisórios.
- **Rede:** IPAddress está com o padrão de fábrica da LAN1; confirme no robô.

Há dois jeitos de editar, e os dois mantêm AASX e NodeSet2 iguais:

1. **No AASX Package Explorer:** abra `aas/DobotCR3AAS.aasx`, edite e exporte o NodeSet2
   (I4AAS) do mesmo jeito que foi feito para o Robô Educacional. Substitua
   `resources/DobotCR3AAS.aasx.xml` pelo arquivo exportado.
2. **Pelos scripts:** edite o dicionário `VALORES` em `ferramentas/gera_nodeset_cr3.py` e rode,
   a partir de `ferramentas/`:
   ```bash
   python gera_nodeset_cr3.py <caminho>/EducationalRobot_V2.aasx.xml ../resources/DobotCR3AAS.aasx.xml
   python gera_aasx_cr3.py <caminho>/EducationalRobotAAS_V2.aasx ../aas/DobotCR3AAS.aasx
   ```
   Os dois arquivos de entrada estão em `AAS_HERMES/instance-aas/`.

## 1. Teste local, sem o aas_core

Valida a AAS, o servidor OPC UA e a ponte MQTT no seu computador.

```bash
cd teste
pip install -r requirements.txt
docker run -d --name mosquitto -p 1883:1883 eclipse-mosquitto:2 mosquitto -c /mosquitto-no-auth.conf
```

Abra três terminais na pasta `teste/`:

```bash
python servidor_teste.py          # terminal 1 — AAS em opc.tcp://localhost:4886
python gateway_simulado.py        # terminal 2 — responde como a camada do CR3 responderá
python cliente_orquestrador.py    # terminal 3 — comanda um ciclo de pick-and-place
```

Saída esperada no terminal 3 (resultado do teste feito com estes arquivos):

```
TechnicalData:
  RobotType      = Collaborative robot (cobot)
  NumberOfAxes   = 6
  Payload        = 3
  WorkingRadius  = 620
  Repeatability  = 0.02
  Protocol       = Modbus TCP

Posições escritas: pick=[300.0, -150.0, 50.0] place=[300.0, 150.0, 50.0]
OperationalState = Start  (aguardando Idle...)

Ciclo concluído: OperationalState voltou para Idle em 2.02 s
```

Com o servidor de teste rodando, o UaExpert também conecta em `opc.tcp://localhost:4886`.

## 2. Subir no servidor do laboratório (aas_core)

Pré-requisitos no servidor:

- Docker com a imagem `aas_core_v1.1.2` (confira com `docker images | grep aas_core`).
- Rede `aas_default` (confira com `docker network ls`; se faltar, `docker network create aas_default`).
- Acesso ao discovery e ao MongoDB (192.168.100.21) e ao broker MQTT.

Passos:

1. Coloque a pasta `cr3-aas` dentro de `AAS_HERMES`, ao lado de `educational-robot-aas`. O
   compose reaproveita `../educational-robot-aas/src`.
2. `cp .env.example .env` e preencha com os mesmos valores de broker e banco do compose do
   Robô Educacional.
3. `docker compose -f docker-compose.cr3.yaml up -d`
4. `docker logs -f DobotCR3AAS`. A camada de integração espera 10 s antes de assinar o
   OperationalState; não pode aparecer "Nó com o nome contendo ... não encontrado".
5. No UaExpert, conecte em `opc.tcp://<ip-do-servidor>:4886` e confira o nó
   `AASAssetAdministrationShell:DobotCR3AAS`.
6. Teste de ponta a ponta com o broker do laboratório:
   ```bash
   python teste/gateway_simulado.py --mqtt-host <broker> --mqtt-port <porta>
   python teste/cliente_orquestrador.py --url opc.tcp://<ip-do-servidor>:4886
   ```

## Pontos de atenção

- **Identificadores dos submodelos.** Eles não podem conter "PickAndPlace" nem "Grabber". A
  camada de integração pega o primeiro nó cujo nome *contém* o trecho procurado e acabaria no
  nó SubmodelReference. Por isso os ids são `.../sm/DobotCR3/0001` a `0004`.
- **AAS_IDENTIFICATION.** O valor no `.env.example` foi gerado para o CR3. Confirme no
  laboratório se ele precisa estar cadastrado no banco do shell manager.
- **Namespace 3 do export I4AAS.** O export usa nomes no namespace 3 sem declará-lo. O
  `aas_core` carrega assim, como já faz com o Robô Educacional. O `servidor_teste.py` declara o
  namespace só na memória, porque versões novas da asyncua recusam o arquivo.
- **Tipos dos valores.** No export, as posições são inteiras (Int32), embora o tipo declarado
  seja String. O cliente de teste escreve respeitando o tipo atual do nó, e as posições ficam
  em milímetros inteiros.
- **Tópicos MQTT.** Com `ASSET_ID=dobot_cr3`, os tópicos são `spacexlab/AAS/dobot_cr3/command` e
  `spacexlab/AAS/dobot_cr3/state`. A camada Modbus TCP do CR3 (`integration-layer-cr3`) vai
  assinar o primeiro e publicar no segundo, no lugar do `gateway_simulado.py`.
