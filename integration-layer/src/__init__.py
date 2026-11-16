try:
    from .pick_and_place import PickAndPlace  # modo OPC UA, carregado pelo servidor AAS
except ModuleNotFoundError as e:
    # Fora do servidor AAS (ex.: python -m src.gateway_mqtt) o pacote core não existe.
    if e.name != "core" and not (e.name or "").startswith("core."):
        raise
