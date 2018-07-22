import json
import logging

from openzwave.node import ZWaveNode


class Action:

    def __init__(self):
        self._log = logging.getLogger("action")

    def action(self, data):
        pass


class SwitchAction(Action):

    def __init__(self, zwn: ZWaveNode, switch_id: int):
        Action.__init__(self)
        self._zwn = zwn
        self._switch_id = switch_id

    def action(self, data: str):
        toggle = data in [b"ON", b"True"]
        self._log.info("Switch Action: %s (%i) set to %r (raw: %s)", self._zwn.name, self._switch_id, toggle, data)
        self._zwn.set_switch(self._switch_id, toggle)


class DimmerAction(Action):

    def __init__(self, zwn: ZWaveNode, switch_id: int):
        Action.__init__(self)
        self._zwn = zwn
        self._switch_id = switch_id

    def action(self, raw: bytes):
        data = json.loads(raw.decode("utf8"))
        state = data.get("state")
        if state in ["ON", "True"]:
            brightness = data.get("brightness", 255)
            brightness = int(brightness * 95 / 255)
            self._zwn.set_dimmer(self._switch_id, brightness)
            self._log.info("Dimmer Action: %s (%i) set to %r (raw: %s)", self._zwn.name, self._switch_id, brightness,
                           data)
        else:
            self._zwn.set_dimmer(self._switch_id, 0)
            self._log.info("Dimmer Action: %s (%i) set to OFF (raw: %s)", self._zwn.name, self._switch_id, data)


class RgbAction(Action):
    """
    Z-Wave returns RGBW data in following format: #FFFFFFFF
    """
    def __init__(self, zwn: ZWaveNode, value_id: int):
        Action.__init__(self)
        self._zwn = zwn
        self._value_id = value_id

    def action(self, raw: bytes):
        data = json.loads(raw.decode("utf8"))
        state = data.get("state")
        r_color = data.get("color")
        r_white = data.get("white_value")
        if state in ["ON", "True"]:
            r, g, b, w = ["FF"] * 4
            if r_white or r_color:
                original = self._zwn.get_rgbw(self._value_id)
                r, g, b, w = [original[n*2+1:(n+1)*2+1] for n in range(0, 4)]
            if r_white:
                w = hex(r_white).upper()[2:4]
            if r_color:
                r, g, b = ["{0:#0{1}x}".format(r_color[k], 4).upper()[2:4] for k in ["r", "g", "b"]]
            color = "#" + r + g + b + w
            self._zwn.set_rgbw(self._value_id, color)
            self._log.info("RGB Action: %s (%i) set to %r (raw: %s)", self._zwn.name, self._value_id, color, raw)
        else:
            self._zwn.set_rgbw(self._value_id, "#00000000")
            self._log.info("RGB Action: %s (%i) set to OFF (raw: %s)", self._zwn.name, self._value_id, raw)
