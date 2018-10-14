import time
import logging
from typing import Dict, List, Union

import yaml
from openzwave.node import ZWaveNode
from openzwave.value import ZWaveValue

from zwave_mqtt_bridge.command_classes import COMMAND_CLASS_NOTIFICATION
from zwave_mqtt_bridge.hass_mqtt import HassMqtt, HassRgbLight, HassCommand, HassDimmer, HassSensor
from zwave_mqtt_bridge.actions import DimmerAction, RgbAction, SwitchAction, Action


class ZwNode:

    def __init__(self, zwn: ZWaveNode, mqtt: HassMqtt, ignored_labels: List):
        self._label_map = {}
        self._taken_labels = set()
        self._zwn = zwn
        self._mqtt = mqtt
        self._actions = {}  # type: Dict[str, SwitchAction]
        self._log = logging.getLogger("node")
        self._spam_tick = (time.time(), 600)
        self._last_metrics = {}
        self._ignored_labels = ignored_labels
        self._cmds = dict()   # type: Dict[str, Union[HassCommand, HassDimmer, HassRgbLight, HassSensor]]
        self._topics = dict()  # type: Dict[str, Action]
        self._config = dict()  # type: Dict[str, str]

    @staticmethod
    def _scale_to_hass(data: int) -> int:
        return int(data * 255 / 95)

    def name(self):
        return self._zwn.name

    def id(self):
        return self._zwn.node_id

    def model(self):
        return self._zwn.product_name

    def metrics(self) -> Dict:
        return self._last_metrics

    def config_template(self) -> Dict[str, List]:
        full_set = dict()
        for cmd in self._cmds.values():
            config = cmd.generate_config()
            for key in config.keys():
                if key not in full_set:
                    full_set[key] = []
                full_set[key].extend(config[key])
        return yaml.dump(full_set, default_flow_style=False).replace("\n", "<br>").replace(" ", "&nbsp;")

    def zw_values(self):
        return self._zwn.get_values()

    def topics(self) -> Dict[str, Action]:
        return self._topics

    def registration_state(self) -> str:
        if len(self._topics) > 0:
            return "Topics Active"
        if self._cmds.get("metrics"):
            return "Sensor Active"
        return "-"

    def set_config(self, value_id, value):
        try:
            value = int(value)
        except:
            pass
        self._zwn.set_config_param(int(value_id), value)
        self._log.info("Setting %r = %r", value_id, value)

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
        battery = self._zwn.get_battery_level()
        if battery:
            metrics["battery"] = battery
        return self._mqtt_metrics_send("sensor", metrics)

    def _mqtt_metrics_send(self, mtype: str, metrics: dict) -> bool:
        for label in self._ignored_labels:
            if label in metrics:
                del metrics[label]
        if self._should_send_metrics(mtype, metrics):
            self._log.info("Sending %s %s data", self._zwn.name, mtype)
            self._mqtt.send_metrics(self._cmds.get("metrics"), metrics)
            return True
        return False

    def send_switch_data(self):
        done = False
        for s_id in self._zwn.get_switches():
            if s_id in self._cmds:
                cmd = self._cmds.get(s_id)
                data = self._zwn.get_switch_state(s_id)
                if cmd.should_status_send(data):
                    self._mqtt.send_switch_state(cmd, data)
                    done = True
        return done

    def send_dimmer_data(self):
        done = False
        for s_id in self._zwn.get_dimmers():
            if s_id in self._cmds:
                cmd = self._cmds.get(s_id)
                data = self._scale_to_hass(self._zwn.get_dimmer_level(s_id))
                if cmd.should_status_send(data):
                    self._mqtt.send_light_state(cmd, data)
                    done = True
        return done

    def send_rgb_data(self):
        done = False
        for s_id in self._zwn.get_rgbbulbs():
            cmd = self._cmds.get(s_id)
            if cmd:
                raw = self._zwn.get_rgbw(s_id)  # In #FFFFFFFF
                r = int("0x" + raw[1:3], 16)
                g = int("0x" + raw[3:5], 16)
                b = int("0x" + raw[5:7], 16)
                w = int("0x" + raw[7:9], 16)
                data = [r, g, b, w]
                if cmd.should_status_send(data):
                    self._mqtt.send_light_state(cmd, None, data)
                    done = True
        return done

    def register_sensors(self) -> Dict[str, Action]:
        """
        Registers normal sensors and notification classes as well
        """
        cmd = self._mqtt.register_metrics(self._zwn.location, self._zwn.name)
        self._cmds["metrics"] = cmd
        for s_id in self._zwn.get_sensors():
            v = self._zwn.values[s_id]  # type: ZWaveValue
            cmd.add_metric(self._get_true_label(v))
            self._log.info("Sensor %s / %s", self._zwn.name, self._get_true_label(v))
        for s_id in self._zwn.get_values_for_command_class(COMMAND_CLASS_NOTIFICATION):
            v = self._zwn.values[s_id]  # type: ZWaveValue
            cmd.add_metric(self._get_true_label(v))
            self._log.info("Sensor (Notification) %s / %s", self._zwn.name, self._get_true_label(v))
        if self._zwn.get_battery_level():
            cmd.add_metric("battery")
        return {}

    def register_switches(self) -> Dict[str, Action]:
        topics = {}
        for s_id in self._zwn.get_switches():
            if s_id in self._cmds:
                continue
            v = self._zwn.values[s_id]  # type: ZWaveValue
            cmd = self._mqtt.register_switch(self._zwn.location, self._zwn.name, self._get_true_label(v))
            self._cmds[s_id] = cmd
            topics[cmd.command] = SwitchAction(self._zwn, v.value_id)
            self._log.info("Switch %s / %s", self._zwn.name, self._get_true_label(v))
        return topics

    def register_dimmers(self) -> Dict[str, Action]:
        for s_id in self._zwn.get_dimmers():
            if s_id in self._cmds:
                continue
            v = self._zwn.values[s_id]  # type: ZWaveValue
            cmd = self._mqtt.register_light(self._zwn.location, self._zwn.name, self._get_true_label(v))
            self._cmds[s_id] = cmd
            self._topics[cmd.command] = DimmerAction(self._zwn, v.value_id)
            self._log.info("Light %s / %s", self._zwn.name, self._get_true_label(v))
        return self._topics

    def register_rgbw(self) -> Dict[str, Action]:
        for s_id in self._zwn.get_rgbbulbs():
            if s_id in self._cmds:
                continue
            v = self._zwn.values[s_id]  # type: ZWaveValue
            cmd = self._mqtt.register_rgb_light(self._zwn.location, self._zwn.name, self._get_true_label(v))
            self._cmds[s_id] = cmd
            self._topics[cmd.command] = RgbAction(self._zwn, v.value_id)
            self._log.info("RGBLight %s / %s", self._zwn.name, self._get_true_label(v))
        return self._topics
