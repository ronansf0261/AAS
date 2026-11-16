import logging


def convert_to_gcode(data, end_effector:str, gripper_open:str, gripper_close:str) -> list[str] | None:
    z_offset = 30
    feedrate_approach = 20
    feedrate_normal = 300
    feedrate_mid = 300

    try:
        in_coord = {
            "x": float(data["in_coord"]["x"]),
            "y": float(data["in_coord"]["y"]),
            "z": float(data["in_coord"]["z"])
        }

        out_coord = {
            "x": float(data["out_coord"]["x"]),
            "y": float(data["out_coord"]["y"]),
            "z": float(data["out_coord"]["z"])
        }

        mid_point_status = (in_coord.get("y") < 100 or out_coord.get("y") < 100) and (in_coord.get("x") < 0 < out_coord.get("x")) or (in_coord.get("x") > 0 > out_coord.get("x"))

        mid_coord = {
            "x": float(0),
            "y": float(180),
            "z": float(30)
        }

        pick_gcode = f"G0 X{in_coord['x']} Y{in_coord['y']} Z{in_coord['z'] + z_offset} F{feedrate_normal}"
        approach_pick_gcode = f"G0 Z{in_coord['z']} F{feedrate_approach}"
        lift_after_pick_gcode = f"G0 Z{in_coord['z'] + z_offset} F{feedrate_approach}"
        mid_point = ''
        move_to_place_gcode = f"G0 X{out_coord['x']} Y{out_coord['y']} Z{out_coord['z'] + z_offset} F{feedrate_normal}"
        place_gcode = f"G0 Z{out_coord['z']} F{feedrate_approach}"
        lift_after_place_gcode = f"G0 Z{out_coord['z'] + z_offset} F{feedrate_approach}"
        home_gcode = "G0 X0 Y185 Z120 F300"

        if mid_point_status:
            mid_point = f"G0 X{mid_coord.get('x')} Y{mid_coord.get('y')} Z{out_coord['z'] + z_offset} F{feedrate_mid}"
        if mid_point_status:
            move_to_place_gcode = f"G0 X{out_coord['x']} Y{out_coord['y']} Z{out_coord['z'] + z_offset} F{feedrate_mid}"

        # Electromagnet Gcode builder
        if end_effector == "Electromagnet":
            grab_gcode = "M6"
            release_gcode = "M7"

            logging.info("Electromagnet Selected")

            return [pick_gcode,
                    approach_pick_gcode,
                    grab_gcode,
                    lift_after_pick_gcode,
                    mid_point,
                    move_to_place_gcode,
                    place_gcode,
                    release_gcode,
                    lift_after_place_gcode,
                    home_gcode]

        # Parallel_Gripper Gcode builder
        elif end_effector == "Parallel Gripper":

            logging.info("Parallel_Gripper Selected")

            gripper_open_value = int(gripper_open)
            gripper_close_value = int(gripper_close)

            gripper_open_gcode = f"M3S{gripper_open_value}"
            gripper_close_gcode = f"M3S{gripper_close_value}"

            return [gripper_open_gcode,
                    pick_gcode,
                    approach_pick_gcode,
                    gripper_close_gcode,
                    lift_after_pick_gcode,
                    mid_point,
                    move_to_place_gcode,
                    place_gcode,
                    gripper_open_gcode,
                    lift_after_place_gcode,
                    home_gcode]

        # DEFAULT Gcode builder
        else:
            logging.info("Default Selected")

            return [pick_gcode,
                    approach_pick_gcode,
                    lift_after_pick_gcode,
                    mid_point,
                    move_to_place_gcode,
                    place_gcode,
                    lift_after_place_gcode,
                    home_gcode]

    except KeyError as e:
        logging.error(f"Missing key in JSON: {e}")
        return None

    except ValueError as e:
        logging.error(f"Error converting coordinate to number: {e}")
        return None


