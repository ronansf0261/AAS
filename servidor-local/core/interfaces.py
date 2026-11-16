"""Interfaces que o aas_core oferece às camadas de integração."""


class Entrypoint:
    """Classe base do src/user_entrypoint.py: init() roda uma vez, depois da carga da AAS."""

    def __init__(self, server):
        self.server = server

    async def init(self):
        pass


class BaseSubmodel:
    """Classe base de um submodelo com lógica (ex.: src/pick_and_place.py -> PickAndPlace).

    O servidor instancia a classe com o servidor OPC UA e chama init(nó_do_submodelo) numa task.
    """

    def __init__(self, server):
        self.server = server

    async def init(self, node, *args, **kwargs):
        pass
