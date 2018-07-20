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

    def action(self, data: str):
        dimming = 99 if data in [b"ON", b"True"] else 0
        self._log.info("Switch Action: %s (%i) set to %r (raw: %s)", self._zwn.name, self._switch_id, dimming, data)
        self._zwn.set_dimmer(self._switch_id, dimming)


class RgbAction(Action):

    def __init__(self, zwn: ZWaveNode, switch_id: int):
        Action.__init__(self)
        self._zwn = zwn
        self._switch_id = switch_id

    def action(self, data: str):
        self._log.info("[X] RGB Action: %s (%i) set to %r (raw: %s)", self._zwn.name, self._switch_id, data, data)
        # self._zwn.set_rgbw(self._switch_id, data)


class BrightnessAction(Action):

    def __init__(self, zwn: ZWaveNode, switch_id: int):
        Action.__init__(self)
        self._zwn = zwn
        self._switch_id = switch_id

    def action(self, data: str):
        dimming = int(data)
        self._log.info("Brightness Action: %s (%i) set to %r (raw: %s)", self._zwn.name, self._switch_id, dimming, data)
        self._zwn.set_dimmer(self._switch_id, dimming)
