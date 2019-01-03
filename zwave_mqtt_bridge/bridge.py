import time
import logging

from typing import Dict, List, Union

from openzwave.node import ZWaveNode
from openzwave.value import ZWaveValue
from openzwave.network import ZWaveNetwork

from zwave_mqtt_bridge.actions import Action

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
        self._mqtt.on_message = self._on_message
        self._nodes = {}  # type: Dict[str, ZwNode]
        self._last_config = 0
        self._actions = {}  # type: Dict[str, Action]
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
        self._find_node(node_id).set_config(int(config_id), data)

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

    def _on_message(self, topic: str, data: str):
        if self._healing:
            _log.info("Healing, skipping request")
            return
        try:
            action = self._actions.get(topic)
            _log.debug("Received message: %r = %r", topic, data)
            if action:
                action.action(data)
        except Exception as e:
            _log.critical("Could not handle message %r / %r", topic, data)
            _log.critical("Exception was", e)

    def register_all(self):
        self._last_config = time.time()
        for node in self._nodes.values():
            self._actions.update(node.register())

    def value_update(self, network: ZWaveNetwork, node: ZWaveNode, value: ZWaveValue):
        self.check_for_repair(network)
        if self._healing:
            _log.info("Healing, skipping value update")
            return
        n = self._nodes.get(node.name)  # type: ZwNode
        if not n:
            self._log.info("New node %s", node)
            n = ZwNode(node, self._mqtt, self._ignored_labels)
            self._nodes[node.name] = n
        if value.genre == "User":
            if self._last_config:
                if value.label.lower() in self._ignored_labels:
                    return
                if n.is_spamming():
                    return
                if not n.update_state(value):
                    self._log.info("Value update (Command class: %r), %s => %s=%r (NOT HANDLED)", hex(value.command_class),
                                   n.name(), value.label, value.data)

    def report_all(self):
        if self._healing:
            _log.info("Healing, skipping full report update")
            return
        for node in self._nodes.values():
            node.send_data()

    def heal(self, node_id):
        self._find_node(node_id)._zwn.heal()

    def network_update(self, node_id):
        self._find_node(node_id)._zwn.network_update()

    def neighbor_update(self, node_id):
        self._find_node(node_id)._zwn.neighbor_update()

    def network_heal(self):
        self.zw_network.heal()
