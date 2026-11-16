# Projeto Hermes — contexto para o Claude Code

Responda sempre em português do Brasil. O usuário é o Ronan de Souza Filho
(Engenharia Eletrônica, EST-UEA), desenvolvedor de hardware no Laboratório 4.0.

## O projeto
Célula pick-and-place controlada por AAS Tipo 2, na disciplina Tópicos Especiais 2
(orientador: Prof. Dr. Rodrigo Choji de Freitas, rcfreitas@uea). Equipe: Ronan de Souza
Filho, Walfredo Kelwin Sobreira Benevendes e João Felipe de Paula Almeida.
Objetivo central: o **teste de troca** — a mesma AAS comanda dois robôs diferentes e
só a camada de integração/gateway muda.

## Decisões em vigor (out/2026)
- Robô A: Dobot CR3. Robô B: Robô Educacional do Laboratório 4.0 (braço de 3 eixos,
  Arduino + RAMPS, G-code via serial, gateway em Raspberry Pi).
- Servidor AAS: OPC UA + MQTT, comum aos dois robôs (substitui o BaSyx/REST da proposta).
- CR3 comandado por **Modbus TCP** pela sua camada de integração (repositório
  integration-layer-cr3), que assina o mesmo tópico MQTT de comando do Robô B.
- O Robô Educacional passou por manutenção; peças quebradas foram reimpressas em 3D.

## Arquivos desta pasta
- `cr3-aas/` — **AAS do Dobot CR3 e servidor OPC UA** (tarefa atual). Leia `cr3-aas/README.md`.
  - `aas/DobotCR3AAS.aasx` (AASX Package Explorer, metamodelo V2.0) e
    `resources/DobotCR3AAS.aasx.xml` (NodeSet2 I4AAS que o servidor carrega).
  - `docker-compose.cr3.yaml` + `.env.example` — sobe com a imagem `aas_core_v1.1.2`, porta 4886,
    reaproveitando `../educational-robot-aas/src` (por isso a pasta fica dentro de AAS_HERMES).
  - `teste/` — `servidor_teste.py` (substitui o aas_core), `gateway_simulado.py`,
    `cliente_orquestrador.py`. Teste de ponta a ponta já validado (ciclo Start → Idle).
  - `ferramentas/` — geradores do NodeSet2 e do AASX a partir dos arquivos do Robô Educacional.
- `relatorio/Projeto_Hermes_Atividades_01-14_10.docx` — relatório da AP1 (atividades de
  01 a 14/10 com evidências). As Figuras 2, 3 e 4 ainda são placeholders.
- `relatorio/figuras/` — as 12 figuras do relatório em PNG (f02–f04 são os placeholders).
- `fotos/` — onde o Ronan coloca as fotos reais (nomes originais do Drive).
- `scripts/inserir_fotos.py` — troca os placeholders pelas fotos e gera
  `relatorio/..._final.docx`. Rodar: `pip install pillow && python scripts/inserir_fotos.py`.

## Tarefa atual: AAS do CR3 e servidor OPC UA
1. Copiar `cr3-aas/` para dentro do repositório AAS_HERMES do Ronan, ao lado de
   `educational-robot-aas/`.
2. Preencher os campos pendentes da AAS (lista no README) e regenerar AASX + NodeSet2 com
   `ferramentas/` usando os arquivos ORIGINAIS de `instance-aas/` (o NodeSet do Robô
   Educacional usado aqui foi reconstruído a partir do Drive).
3. Rodar o teste local (`teste/`), depois subir no servidor do laboratório com o
   docker-compose e repetir o teste com o broker real.
4. Em seguida: camada `integration-layer-cr3` (assina `spacexlab/AAS/dobot_cr3/command`,
   comanda o CR3 por Modbus TCP, publica `{"operational_state": "Idle"}` em `.../state`).

### Estado em 04/11/2026: ambiente local sem o hub (validado)
- A AAS em uso é a do Ronan: `C:\AAS\integration-layer\resources\DobotCR3_1.aasx.xml` + `CR3.aasx`
  (repositório GitLab do laboratório). Recebeu o submodelo Grabber (cópia do Robô Educacional V2)
  e HomePosition provisória (200, 150, 150), pois (120, 80, 40) caía na cúpula proibida.
- `C:\AAS\servidor-local\` substitui o aas_core: `aas_local.py` (asyncua, porta 4886) + pacote
  `core/` falso, Mosquitto (serviço Windows, 127.0.0.1:1883), cliente de teste e
  `iniciar_teste.ps1`. Leia `servidor-local/README.md`.
- Contrato Hermes funcionando: ponte `educational-robot-aas/src` → MQTT → `integration-layer`
  `python -m src.gateway_mqtt` (MQTT → Modbus) → simulador `monitorarModbus.py` (5020) → Idle.
- Ambiente: Windows sem Docker funcional (Docker Desktop + WSL 2 instalados em 04/11, falta
  reiniciar), Python 3.9 no venv `C:\AAS\.venv`, porta 4840 ocupada pelo `opcualds`.
- Robô B também validado localmente: `EducationalRobot_V2.aasx.xml` na porta 4885 (ASSET_ID
  0000_0000_0000_0000), gateway da Raspberry sem alteração via `servidor-local/testes/gateway_robo_b.py`
  (Python 3.11, venv `C:\AAS\.venv-robo-b`) e Arduino simulado (`simulador_arduino.py`, TCP 7777).
  Teste de troca feito: o mesmo cliente comanda os dois robôs (`cliente_orquestrador.py --robo cr3|educacional`).
- Deploy em Docker nesta máquina: `cd servidor-local; docker compose up -d` (7 contêineres
  `hermes-*`, mesmas portas do modo janelas — usar um ou outro). Serviço Mosquitto do Windows
  ficou parado, com partida manual. Detalhes na seção 3.1 do `servidor-local/README.md`.
- Máquina de estados (Fase 4.3) no gateway do CR3: Idle / Executing / Stopped / Error: <código>,
  Stop pela AAS (a ponte `educational-robot-aas/src` passou a repassar "stop"), vigilância da
  conexão e handshake opcional no registrador 4009 (`MODBUS_REG_STATUS`; 0 = tempo fixo).
- Orquestrador (Pacote 5) em `C:\AAS\orquestrador`: sequências JSON, 20 ciclos, recuperação com
  Calibrate, evidências do FAT em `execucoes/` (taxa CA-01/CA-04, CA-03, commits para o ICM).
- Próximo: CR3 real (192.168.5.1:502) e programa do controlador para os registradores 4000–4009;
  conversão para o referencial da célula (Fase 4.2); protocolo de FAT (7.1); commit do código.

Regra crítica: a camada de integração do laboratório acha nós pelo PRIMEIRO filho cujo nome
exibido CONTÉM o trecho. Ids de submodelo não podem conter "PickAndPlace"/"Grabber", e em
nós clonados "Value" precisa vir antes de "ValueType" na ordem dos filhos.

## Pendência menor: fotos do relatório da AP1
Colocar as três fotos em `fotos/` e rodar `scripts/inserir_fotos.py`; ajustar legendas das
Figuras 2 e 3 se necessário.

## Convenções de redação do relatório
Frases curtas, voz ativa, atividades atribuídas à equipe, período 01–14/10/2026.
Figuras com legenda ABNT ("Figura N – título" acima, "Fonte: …" abaixo).
Paleta das figuras: azul-marinho #1F3864, laranja #C55A11 (em desenvolvimento),
verde #2E7D32 (em operação).

@HISTORICO.md
