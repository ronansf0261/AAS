# Orquestrador do Projeto Hermes (Pacote 5)

Executa sequências de pick-and-place **pela AAS**, por OPC UA, e registra as evidências do FAT.
Não sabe qual robô está do outro lado: o mesmo orquestrador comanda o Dobot CR3 e o Robô
Educacional, e é isso que o teste de troca exige (CA-04 e CA-05).

```
orquestrador.py ──OPC UA──► AAS (OperationalState, posições) ──MQTT──► gateway ──► robô
       ▲                                                                    │
       └──────────── estados: Start → Executing → Idle / Stopped / Error ◄──┘
```

## Uso

Com o ambiente no ar (Docker ou `iniciar_teste.ps1`), a partir de `C:\AAS\orquestrador`:

```powershell
..\.venv\Scripts\python orquestrador.py sequencias\cr3.json              # 20 ciclos no CR3
..\.venv\Scripts\python orquestrador.py sequencias\robo_b.json           # 20 ciclos no Robô Educacional
..\.venv\Scripts\python orquestrador.py sequencias\cr3.json --ciclos 3   # menos ciclos
..\.venv\Scripts\python orquestrador.py sequencias\cr3.json --parar-na-falha

..\.venv\Scripts\python orquestrador.py --robo cr3 --estado      # estado e posições na AAS
..\.venv\Scripts\python orquestrador.py --robo cr3 --calibrar    # Calibrate e espera Idle
..\.venv\Scripts\python orquestrador.py --robo cr3 --parar       # Stop e espera Stopped
```

`--robo educacional` aponta para a AAS do Robô Educacional; `--url` aceita qualquer servidor.
Ctrl+C durante uma execução manda Stop ao robô e grava o que já foi feito.

## O que acontece numa execução

1. **Preparação.** Se o OperationalState não for `Idle`, espera o robô terminar ou manda
   `Calibrate`.
2. **Ciclo.** Escreve pick e place (e a garra, se a sequência pedir), escreve `Start` e espera um
   estado final na AAS, acompanhando cada mudança pela assinatura OPC UA:

   | Estado final | Resultado do ciclo |
   | --- | --- |
   | `Idle` | OK |
   | `Error: <código>` | ERRO |
   | `Stopped` | PARADO |
   | nenhum até `timeout_ciclo_s` | TIMEOUT (manda `Stop`) |

3. **Recuperação.** Depois de um ciclo que não terminou em OK, manda `Calibrate` e segue. Se a
   recuperação falhar, encerra. Com `--parar-na-falha`, encerra no primeiro problema.
4. **Evidências** em `execucoes\<data-hora>_<sequência>\`:
   - `ciclos.csv`: um ciclo por linha (posições, início, duração, estados observados, resultado);
   - `eventos.log`: cada mudança de estado com o tempo desde o comando;
   - `resumo.json`: totais, taxa de sucesso, observabilidade, tempos, recuperações e o commit
     de cada repositório no momento da execução.

## Ligação com os critérios do FAT (item 8.2 da proposta)

| Critério | O que o orquestrador entrega |
| --- | --- |
| CA-01 e CA-04 (20 ciclos, ≥ 95%) | `taxa_sucesso` e `aprovado_taxa_sucesso` no `resumo.json` |
| CA-03 (estado em 100% dos ciclos) | `observabilidade_estado`: ciclos em que a AAS devolveu um estado final |
| CA-05 e ICM (diff entre commits) | `versoes`: commit e arquivos não commitados de cada repositório |
| CA-07 (falhas) | resultado PARADO/ERRO por ciclo e a recuperação com Calibrate no `eventos.log` |

O ICM só é medível com o código versionado: `resumo.json` avisa quando um repositório tem
arquivos não commitados ou quando a pasta não está no Git.

## Sequências

Arquivos JSON em `sequencias\`. Cada ciclo executa um passo; os passos se repetem em ordem.

```json
{
  "nome": "Sequência de referência — Dobot CR3",
  "aas_url": "opc.tcp://127.0.0.1:4886",
  "ciclos": 20,
  "timeout_ciclo_s": 60,
  "meta_sucesso": 0.95,
  "garra": {"abertura": 180, "fechamento": 45},
  "passos": [
    {"pick": [200, 150, 100], "place": [-200, 150, 100]},
    {"pick": [-200, 150, 100], "place": [200, 150, 100]}
  ]
}
```

Os dois passos levam a peça e trazem de volta, então 20 ciclos seguidos rodam sem reposição.
`garra` é opcional e só é escrita se a AAS tiver o submodelo Grabber.

**Pendência (Fase 4.2):** as coordenadas ainda estão no referencial de cada robô, por isso há uma
sequência por robô. Quando os gateways converterem do referencial da célula, uma única sequência
servirá aos dois, como pede o CA-04 ("mesma sequência").

## Resultado dos testes (simulação)

| Teste | Resultado |
| --- | --- |
| CR3, 20 ciclos | 20/20 OK, `Start → Executing → Idle` em todos, 3,44 s por ciclo |
| Robô Educacional, 3 ciclos | 3/3 OK, `Start → Idle`, cerca de 23 s por ciclo |
| Stop pela AAS no meio do ciclo | ciclo PARADO, recuperação com Calibrate, ciclo seguinte OK |
| Parada informada pelo robô | `Stopped`, recuperação, ciclo seguinte OK |
| Alarme do robô | `Error: Robot Alarm`, recuperação, ciclo seguinte OK |
| Conexão Modbus cai no meio do ciclo | `Error: Modbus Communication Failed`; recuperação falha enquanto o robô está fora e a execução encerra com o motivo registrado |

O gateway do Robô Educacional (Raspberry Pi) ainda não tem a máquina de estados: só devolve
`Idle`, não trata `Stop` e não informa falhas.
