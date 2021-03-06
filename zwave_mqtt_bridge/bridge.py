import json
import time
import logging

from typing import Dict, List, Union

from openzwave.node import ZWaveNode
from openzwave.value import ZWaveValue
from openzwave.network import ZWaveNetwork

from zwave_mqtt_bridge.hass_mqtt import HassMqtt
from zwave_mqtt_bridge.zw_node import ZwNode

DEBUG = True

logging.basicConfig(level=logging.DEBUG,
                    format='%(asctime)s %(name)-12s %(levelname)-8s %(message)s',
                    datefmt='%m-%d %H:%M',
                    filename='zwave-gate.log',
                    filemode='w')
_log = logging.getLogger("bridge")


class Bridge:

    def __init__(self, mqtt: HassMqtt, ignored_labels: List):
        self._ignored_labels = ignored_labels
        self._mqtt = mqtt
        self._nodes = {}  # type: Dict[str, ZwNode]
        self._last_config = 0
        self._log = logging.getLogger("zwbridge")
        self._repair_time = 0
        self._last_repair_attempt = 0
        self._healing = False
        self.zw_network = None
        #self._repair_time = int(time.time() / (24*60*60))

    def _find_node(self, node_id: int) -> Union[ZwNode, None]:
        for i in self._nodes.values():
            if i.id() == node_id:
                return i
        return None

    def set_config(self, node_id: int, config_id: int, data: str):
        self._find_node(node_id).set_config(int(config_id), json.loads(data))

    def nodes(self):
        return self._nodes

    def check_for_repair(self, network: ZWaveNetwork):
        if time.time() - self._last_repair_attempt > 5*60:
            self._last_repair_attempt = time.time()
            if network.is_ready:
                now = int(time.time() / (24*60*60))
                if now != self._repair_time:
                    try:
                        _log.info("Starting healing..")
                        self._healing = True
                        network.heal(True)
                    finally:
                        self._healing = False
                        self._repair_time = now
                        _log.info("Healing done")
            else:
                _log.info("Healing scheduled - waiting network to be ready")

    def register_all(self):
        self._last_config = time.time()
        for node in self._nodes.values():
            node.register(self._mqtt)

    def value_update(self, network: ZWaveNetwork, node: ZWaveNode, value: ZWaveValue):
        self.check_for_repair(network)
        if self._healing:
            _log.info("Healing, skipping value update")
            return
        n = self._nodes.get(node.name)  # type: ZwNode
        if not n:
            self._log.info("New node %s", node)
            n = ZwNode(node, self._mqtt, self._ignored_labels)
            name = node.name
            if node.name == "":
                name = str(node.node_id)
            self._nodes[name] = n
        if value.genre == "User":
            if self._last_config:
                if value.label.lower() in self._ignored_labels:
                    return
                if n.is_spamming():
                    return
                if not n.update_state(value):
                    self._log.info("Value update (Command class: %r), %s => %s=%r (NOT HANDLED)", hex(value.command_class),
                                   n.name(), value.label, value.data)
        elif value.genre == "System":
            self._log.debug("System (Command class: %r), %s => %s=%r (NOT HANDLED)", hex(value.command_class),
                           n.name(), value.label, value.data)
        elif value.genre == "Config":
            self._log.debug("Config (Command class: %r), %s => %s=%r (NOT HANDLED)", hex(value.command_class),
                           n.name(), value.label, value.data)
        elif value.genre == "Basic":
            self._log.debug("Basic (Command class: %r), %s => %s=%r (NOT HANDLED)", hex(value.command_class),
                           n.name(), value.label, value.data)
        else:
            _log.info("Unhandled message of genre %r (%r, %r)", value.genre, value.label, value.data)

    def heal(self, node_id):
        self._find_node(node_id)._zwn.heal()

    def network_update(self, node_id):
        return self.zw_network.controller.request_network_update(node_id)

    def neighbor_update(self, node_id):
        return self.zw_network.controller.request_node_neighbor_update(node_id)

    def network_heal(self):
        return self.zw_network.heal()

    def add_node(self):
        return self.zw_network.controller.add_node()

    def write_config(self):
        return self.zw_network.write_config()

    def update_config(self):
        return self.zw_network.controller.update_ozw_config()

    def rename_node(self, node_id, name):
        pass

    def refresh_info(self, node_id):
        return self.zw_network.controller.send_node_information(node_id)
