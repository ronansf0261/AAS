# Abre cada componente do teste (contrato Hermes) numa janela do PowerShell:
#   monitor MQTT, simulador do robô, servidor AAS (OPC UA) e gateway do robô.
# O broker é o serviço "mosquitto" do Windows; se ele não estiver rodando, abre o Mosquitto
# em primeiro plano com o mosquitto.conf desta pasta.
#
# Pode rodar de novo à vontade: o que já estiver rodando é mantido e só o que falta é aberto.
# Os dois robôs funcionam ao mesmo tempo (OPC UA 4886 e 4885, Modbus 5020, serial TCP 7777,
# mesmo broker, tópicos diferentes).
#
# Uso (PowerShell, em C:\AAS):
#   powershell -ExecutionPolicy Bypass -File servidor-local\iniciar_teste.ps1 -Robo Ambos           # os dois robôs
#   powershell -ExecutionPolicy Bypass -File servidor-local\iniciar_teste.ps1                       # só o Dobot CR3 (Robô A)
#   powershell -ExecutionPolicy Bypass -File servidor-local\iniciar_teste.ps1 -Robo Educacional     # só o Robô Educacional (Robô B)
#   ... -ModbusHost 192.168.5.1 -ModbusPort 502      # CR3 real, sem simulador
#   ... -Robo Educacional -SerialPort COM3           # Arduino real no USB, sem simulador
#
# Atenção nas janelas: Ctrl+C SEM texto selecionado encerra o programa. Para copiar, selecione
# o texto antes (ou use o botão direito).
param(
    [ValidateSet("CR3", "Educacional", "Ambos")]
    [string]$Robo = "CR3",
    [string]$ModbusHost = "localhost",
    [int]$ModbusPort = 5020,
    [string]$SerialPort = "socket://127.0.0.1:7777"
)

$Raiz = Split-Path -Parent $PSScriptRoot           # C:\AAS
$Py = Join-Path $Raiz ".venv\Scripts\python.exe"
$PyB = Join-Path $Raiz ".venv-robo-b\Scripts\python.exe"   # Python 3.11 (gateway da Raspberry)
$Mosq = "C:\Program Files\mosquitto"

$CR3 = @{ Asset = "dobot_cr3"; Porta = 4886 }
$EDU = @{ Asset = "0000_0000_0000_0000"; Porta = 4885 }   # o mesmo ASSET_ID do docker-compose do laboratório

if (-not (Test-Path $Py)) { throw "Ambiente Python não encontrado em $Py (veja o README, seção Instalação)." }

# O deploy em Docker (docker-compose.yaml) usa as mesmas portas: rode um ou outro.
$docker = Get-Command docker -ErrorAction SilentlyContinue
if ($docker -and (& docker ps -q --filter "name=hermes-" 2>$null)) {
    throw "Os contêineres do Hermes estão rodando (docker compose). Pare com 'docker compose down' em servidor-local antes de usar este lançador."
}
if ($Robo -ne "CR3" -and -not (Test-Path $PyB)) { throw "Ambiente Python 3.11 não encontrado em $PyB (veja o README, seção Instalação)." }

# Linhas de comando dos processos em execução, para não abrir um componente duas vezes.
$emExecucao = @(Get-CimInstance Win32_Process -Filter "Name='python.exe' OR Name='mosquitto_sub.exe'" |
                ForEach-Object { $_.CommandLine })

function Abrir-Janela([string]$Titulo, [string]$Pasta, [string]$Comando, [string]$Assinatura) {
    if ($Assinatura -and ($emExecucao | Where-Object { $_ -like "*$Assinatura*" })) {
        Write-Host "  já rodando, mantido: $Titulo"
        return
    }
    $cmd = "`$Host.UI.RawUI.WindowTitle = '$Titulo'; Set-Location '$Pasta'; $Comando"
    Start-Process powershell.exe -ArgumentList "-NoExit", "-Command", $cmd
    Write-Host "  aberto: $Titulo"
}

$servico = Get-Service mosquitto -ErrorAction SilentlyContinue
if ($servico -and $servico.Status -eq "Running") {
    Write-Host "Broker: serviço mosquitto rodando (127.0.0.1:1883)."
} else {
    Abrir-Janela "Mosquitto (1883)" $PSScriptRoot "& '$Mosq\mosquitto.exe' -c '$PSScriptRoot\mosquitto.conf' -v" "mosquitto.conf"
}

function Iniciar-CR3 {
    Write-Host "[CR3] Dobot CR3 - OPC UA $($CR3.Porta), tópicos spacexlab/AAS/$($CR3.Asset)/#"
    Abrir-Janela "[CR3] Monitor MQTT" $Raiz "& '$Mosq\mosquitto_sub.exe' -h localhost -t 'spacexlab/AAS/$($CR3.Asset)/#' -v" "spacexlab/AAS/$($CR3.Asset)/#"
    if ($ModbusHost -eq "localhost" -or $ModbusHost -eq "127.0.0.1") {
        Abrir-Janela "[CR3] Simulador Modbus ($ModbusPort)" "$Raiz\integration-layer" "`$env:MODBUS_SIM_PORT = '$ModbusPort'; & '$Py' -u src\monitorarModbus.py" "monitorarModbus.py"
    } else {
        Write-Host "  Modbus: controlador em ${ModbusHost}:$ModbusPort (simulador não aberto)."
    }
    Abrir-Janela "[CR3] Servidor AAS (OPC UA $($CR3.Porta))" $Raiz "& '$Py' -u servidor-local\aas_local.py -f DobotCR3_1.aasx.xml --resources integration-layer\resources --src educational-robot-aas\src --asset-id $($CR3.Asset) --porta $($CR3.Porta)" "--porta $($CR3.Porta)"
    Start-Sleep -Seconds 2
    Abrir-Janela "[CR3] Gateway MQTT -> Modbus" "$Raiz\integration-layer" "`$env:ASSET_ID = '$($CR3.Asset)'; `$env:MODBUS_HOST = '$ModbusHost'; `$env:MODBUS_PORT = '$ModbusPort'; `$env:AAS_OPCUA_URL = 'opc.tcp://127.0.0.1:$($CR3.Porta)'; & '$Py' -u -m src.gateway_mqtt" "src.gateway_mqtt"
}

function Iniciar-Educacional {
    Write-Host "[Robô B] Robô Educacional - OPC UA $($EDU.Porta), tópicos spacexlab/AAS/$($EDU.Asset)/#"
    Abrir-Janela "[Robô B] Monitor MQTT" $Raiz "& '$Mosq\mosquitto_sub.exe' -h localhost -t 'spacexlab/AAS/$($EDU.Asset)/#' -v" "spacexlab/AAS/$($EDU.Asset)/#"
    if ($SerialPort.StartsWith("socket://")) {
        $portaSim = $SerialPort.Split(":")[-1]
        Abrir-Janela "[Robô B] Simulador Arduino (TCP $portaSim)" $Raiz "& '$PyB' -u servidor-local\testes\simulador_arduino.py --porta $portaSim" "simulador_arduino.py"
        Start-Sleep -Seconds 1
    } else {
        Write-Host "  Serial: Arduino em $SerialPort (simulador não aberto)."
    }
    Abrir-Janela "[Robô B] Servidor AAS (OPC UA $($EDU.Porta))" $Raiz "& '$Py' -u servidor-local\aas_local.py -f EducationalRobot_V2.aasx.xml --resources educational-robot-aas\resources --src educational-robot-aas\src --asset-id $($EDU.Asset) --porta $($EDU.Porta)" "--porta $($EDU.Porta)"
    Abrir-Janela "[Robô B] Gateway MQTT -> G-code serial" $Raiz "`$env:ASSET_ID = '$($EDU.Asset)'; `$env:SERIAL_PORT = '$SerialPort'; & '$PyB' -u servidor-local\testes\gateway_robo_b.py" "gateway_robo_b.py"
}

if ($Robo -in "CR3", "Ambos") { Iniciar-CR3 }
if ($Robo -in "Educacional", "Ambos") { Iniciar-Educacional }

Write-Host ""
Write-Host "Aguarde ~15 s (a ponte do laboratório assina o OperationalState 10 s depois de subir) e rode:"
if ($Robo -in "CR3", "Ambos") { Write-Host "  & '$Py' servidor-local\testes\cliente_orquestrador.py --robo cr3           # UaExpert: opc.tcp://127.0.0.1:$($CR3.Porta)" }
if ($Robo -in "Educacional", "Ambos") { Write-Host "  & '$Py' servidor-local\testes\cliente_orquestrador.py --robo educacional   # UaExpert: opc.tcp://127.0.0.1:$($EDU.Porta)" }
Write-Host "MQTT Explorer: 127.0.0.1:1883, tópico spacexlab/#"
Write-Host "Ctrl+C sem texto selecionado encerra o programa da janela."
