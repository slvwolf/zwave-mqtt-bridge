import time
import logging
from typing import Dict, List

from openzwave.node import ZWaveNode
from openzwave.value import ZWaveValue

from zwave_mqtt_bridge.command_classes import COMMAND_CLASS_NOTIFICATION
from zwave_mqtt_bridge.hass_mqtt import HassMqtt
from zwave_mqtt_bridge.actions import DimmerAction, RgbAction, BrightnessAction, SwitchAction, Action


class ZwNode:

    def __init__(self, zwn: ZWaveNode, mqtt: HassMqtt, ignored_labels: List):
        self._label_map = {}
        self._taken_labels = set()
        self._zwn = zwn
        self._mqtt = mqtt
        self._actions = {}  # type: Dict[str, SwitchAction]
        self._log = logging.getLogger("node")
        self._spam_tick = (time.time(), 60)
        self._last_metrics = {}
        self._ignored_labels = ignored_labels

    def name(self):
        return self._zwn.name

    @staticmethod
    def _format_label(label: str):
        return label.lower().replace(" ", "_")

    def is_spamming(self) -> bool:
        last_time, count = self._spam_tick
        intervals = int((time.time() - last_time))
        if intervals > 10:
            count += intervals
            count = min(count, 100)
            last_time = int(time.time())
        if count > 0:
            count -= 1
            if count == 0:
                self._log.warning("Spamming node detected %s (%s). Setting 60s timeout.", self._zwn.name,
                                  self._zwn.product_name)
                count = -60
        self._spam_tick = (last_time, count)
        return count == 0

    def _get_true_label(self, value: ZWaveValue):
        """
        ZWave can have same labels for multiple items. In order to avoid naming overlapping generate postfixes.
        :param value: ZWaveValue
        :return: New label
        """
        label = self._format_label(value.label)
        true_name = self._label_map.get(str(value.command_class) + str(value.value_id))
        if not true_name:
            while str(value.command_class) + label in self._taken_labels:
                if label[-2] == "_":
                    v = int(label[-1]) + 1
                    label = label[:-2] + "_" + str(v)
                elif label[-3] == "_":
                    v = int(label[-2]) + 1
                    label = label[:-3] + "_" + str(v)
                else:
                    label = label + "_2"
            self._taken_labels.add(str(value.command_class) + label)
            self._label_map[str(value.command_class) + str(value.value_id)] = label
            return label
        return true_name

    def _should_send_metrics(self, metric: str, data: dict):
        if len(data) == 0:
            return False
        last_metrics, last_send = self._last_metrics.get(metric, ({}, 0))
        if last_metrics != data or time.time() - last_send > 120:
            self._last_metrics[metric] = (data, time.time())
            return True
        return False

    def register_sensors(self) -> Dict[str, Action]:
        """
        Registers normal sensors and notification classes as well
        """
        for s_id in self._zwn.get_sensors():
            v = self._zwn.values[s_id]  # type: ZWaveValue
            self._mqtt.send_sensor_config(self._zwn.name, "sensor", self._get_true_label(v), v.units)
            self._log.info("Sensor %s / %s", self._zwn.name, self._get_true_label(v))
        for s_id in self._zwn.get_values_for_command_class(COMMAND_CLASS_NOTIFICATION):
            v = self._zwn.values[s_id]  # type: ZWaveValue
            self._mqtt.send_sensor_config(self._zwn.name, "sensor", self._get_true_label(v), v.units)
            self._log.info("Sensor (Notification) %s / %s", self._zwn.name, self._get_true_label(v))
        return {}

    def send_sensor_data(self) -> bool:
        """
        Send all sensor data, return true if something was relayed forward
        :return: True if data was sent
        """
        metrics = {}
        values = self._zwn.get_sensors()
        values.update(self._zwn.get_values_for_command_class(COMMAND_CLASS_NOTIFICATION))
        for s_id in values:
            value = self._zwn.values[s_id].data
            if isinstance(value, float):
                value = "%.2f" % value
            metrics[self._get_true_label(self._zwn.values[s_id])] = value
            # Include notification class data
        return self._mqtt_metrics_send("sensor", metrics)

    def _mqtt_metrics_send(self, mtype: str, metrics: dict, state="state") -> bool:
        for label in self._ignored_labels:
            if label in metrics:
                del metrics[label]
        if self._should_send_metrics(mtype, metrics):
            self._log.info("Sending %s %s data", self._zwn.name, mtype)
            self._mqtt.send_metrics(mtype, self._zwn.name, metrics, state=state)
            return True
        return False

    def send_switch_data(self):
        metrics = {self._get_true_label(self._zwn.values[s_id]):
                   "OFF" if self._zwn.get_switch_state(s_id) == 0 else "ON"
                   for s_id in self._zwn.get_switches()}
        return self._mqtt_metrics_send("switch", metrics)

    def send_dimmer_data(self):
        metrics = {self._get_true_label(self._zwn.values[s_id]):
                   "OFF" if self._zwn.get_dimmer_level(s_id) == 0 else "ON"
                   for s_id in self._zwn.get_dimmers()}
        return self._mqtt_metrics_send("light", metrics)

    def send_rgb_data(self):
        metrics = {self._get_true_label(self._zwn.values[s_id]):
                   self._zwn.get_rgbw(s_id)
                   for s_id in self._zwn.get_rgbbulbs()}
        return self._mqtt_metrics_send("light", metrics, state="rgb/state")

    def register_switches(self) -> Dict[str, Action]:
        topics = {}
        for s_id in self._zwn.get_switches():
            v = self._zwn.values[s_id]  # type: ZWaveValue
            topic = self._mqtt.send_switch_config(self._zwn.name, self._get_true_label(v))
            topics[topic] = SwitchAction(self._zwn, v.value_id)
            self._log.info("Switch %s / %s", self._zwn.name, self._get_true_label(v))
        return topics

    def register_dimmers(self) -> Dict[str, Action]:
        topics = {}
        for s_id in self._zwn.get_dimmers():
            v = self._zwn.values[s_id]  # type: ZWaveValue
            topic = self._mqtt.send_light_config(self._zwn.name, self._get_true_label(v))
            topics[topic] = DimmerAction(self._zwn, v.value_id)
            self._log.info("Light %s / %s", self._zwn.name, self._get_true_label(v))
        return topics

    def register_rgbw(self) -> Dict[str, Action]:
        topics = {}
        for s_id in self._zwn.get_rgbbulbs():
            v = self._zwn.values[s_id]  # type: ZWaveValue
            topic, rgb_topic, b_topic = self._mqtt.send_rgb_light_config(self._zwn.name, self._get_true_label(v))
            topics[topic] = DimmerAction(self._zwn, v.value_id)
            topics[rgb_topic] = RgbAction(self._zwn, v.value_id)
            topics[b_topic] = BrightnessAction(self._zwn, v.value_id)
            self._log.info("RGBLight %s / %s", self._zwn.name, self._get_true_label(v))
        return topics
