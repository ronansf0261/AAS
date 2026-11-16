from asyncua import Node
from core.interfaces import Entrypoint
from core.log import logger


class UserEntrypoint(Entrypoint):
    def __init__(self, server):
        super().__init__(server)
        logger.info("UserEntrypoint initialized")

    async def init(self):
        # Setup pick and place
        path_command = ["AssetAdministrationShell", "PickAndPlace", "PickAndPlacePositioning", "GripperControl", "OperationalState", "Value"]

        path_xin = ["AssetAdministrationShell", "PickAndPlace", "PickAndPlacePositioning", "GripperControl", "PickPosition", "XPosition", "Value"]
        path_yin = ["AssetAdministrationShell", "PickAndPlace", "PickAndPlacePositioning", "GripperControl", "PickPosition", "YPosition", "Value"]
        path_zin = ["AssetAdministrationShell", "PickAndPlace", "PickAndPlacePositioning", "GripperControl", "PickPosition", "ZPosition", "Value"]

        path_xout = ["AssetAdministrationShell", "PickAndPlace", "PickAndPlacePositioning", "GripperControl", "PlacePosition", "XPosition", "Value"]
        path_yout = ["AssetAdministrationShell", "PickAndPlace", "PickAndPlacePositioning", "GripperControl", "PlacePosition", "YPosition", "Value"]
        path_zout = ["AssetAdministrationShell", "PickAndPlace", "PickAndPlacePositioning", "GripperControl", "PlacePosition", "ZPosition", "Value"]

        command: Node = await self.find_value_node(path_command)
        xin: Node = await self.find_value_node(path_xin)
        yin: Node = await self.find_value_node(path_yin)
        zin: Node = await self.find_value_node(path_zin)
        xout: Node = await self.find_value_node(path_xout)
        yout: Node = await self.find_value_node(path_yout)
        zout: Node = await self.find_value_node(path_zout)

        await command.set_writable()
        await xin.set_writable()
        await yin.set_writable()
        await zin.set_writable()
        await xout.set_writable()
        await yout.set_writable()
        await zout.set_writable()

        # Setup grabber
        path_opening_width = ["AssetAdministrationShell", "Grabber", "ParallelGripping", "OpeningWidth", "Value"]
        path_clamping_width = ["AssetAdministrationShell", "Grabber", "ParallelGripping", "ClampingWidth", "Value"]

        opening_width_node = await self.find_value_node(path_opening_width)
        clamping_width_node = await self.find_value_node(path_clamping_width)

        await opening_width_node.set_writable()
        await clamping_width_node.set_writable()

    async def find_value_node(self, path):
        try:
            root_node = self.server.get_root_node()
            objects_node = await root_node.get_child(["0:Objects"])
            current_node = objects_node

            for level in path:
                children = await current_node.get_children()
                next_node = None

                for child in children:
                    display_name = await child.read_display_name()
                    if level in display_name.Text:
                        next_node = child
                        break

                if next_node is None:
                    return None
                current_node = next_node

            return current_node

        except Exception as _:
            return None
