# Camada de Integração

Esta código é responsável por implementar a parte funcional do AAS, tornando acessível o mesmo por meio de uma API OPC UA e fazendo comunicação com o asset por meio do protocolo MQTT.

## Iniciando

Para fazer deploy do AAS é necessário alterar o `docker-compose.yaml` nos campos de variáveis de ambiente, coloque as respectivas variáveis que correspondam a seu asset.:
```bash
    environment:
      - MQTT_HOST=junction.proxy.rlwy.net
      - MQTT_PORT=25481
      - ASSET_ID=0000_0000_0000_0000
```
Também é importante mudar o nome do container no campo:
```bash
    container_name: EducationalRobot_V2
```
Dentro da pasta resources você terá o xml representando a instância do AAS do robô, é importante que o docker-compose contanha o seguinte campo com o mesmo nome do arquivo presente em resources:
```bash
    command: >
      -f EducationalRobot_V2.aasx.xml
```
Após todas as configurações feitas, dentro do servidor que hospedará o AAS, execute o seguinte comando:
```bash
docker compose up -d
```