import time
import logging
from typing import Dict, List, Union

import yaml
from openzwave.node import ZWaveNode
from openzwave.value import ZWaveValue
from zwave_mqtt_bridge.command_classes import COMMAND_CLASS_RGB, COMMAND_CLASS_SWITCH, COMMAND_CLASS_DIMMER, SENSORS, COMMAND_CLASS_NOTIFICATION

from zwave_mqtt_bridge.hass_mqtt import HassMqtt, HassRgbLight, HassCommand, HassDimmer, HassSensor
from zwave_mqtt_bridge.actions import DimmerAction, RgbAction, SwitchAction, Action

LOG = logging.getLogger("node")


class Labels:

    def __init__(self):
        self._label_map = {}
        self._taken_labels = set()

    @staticmethod
    def _format_label(label: str):
        return label.lower().replace(" ", "_")

    def get_true_label(self, value: ZWaveValue):
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


class Metrics:

    def __init__(self, labels: Labels, ignored_labels: List[str]):
        self._data = {}
        self._labels = labels
        self._ignore_list = ignored_labels
        self._dirty = False
        self._last_metric_ts = 0

    @staticmethod
    def _get_true_value(value):
        if isinstance(value, float):
            value = "%.2f" % value
        return value

    def set_direct(self, key: str, new_value):
        old_value = self._data.get(key)
        if old_value != new_value:
            self._data[key] = new_value
            self._dirty = True

    def set_from_value(self, value: ZWaveValue):
        label = self._labels.get_true_label(value)
        if label in self._ignore_list:
            return
        new_value = self._get_true_value(value.data)
        old_value = self._data.get(label)
        if old_value != new_value:
            self._data[label] = new_value
            self._dirty = True

    def should_send(self):
        if len(self._data) == 0:
            return False
        if self._dirty or time.time() - self._last_metric_ts > 120:
            self._dirty = False
            self._last_metric_ts = time.time()
            return True
        return False

    def data(self):
        return self._data


class ZwNode:

    def __init__(self, zwn: ZWaveNode, mqtt: HassMqtt, ignored_labels: List):
        self._zwn = zwn
        self._mqtt = mqtt
        self._actions = {}  # type: Dict[str, SwitchAction]
        self._spam_tick = (time.time(), 600)
        self._labels = Labels()
        self._m = Metrics(self._labels, ignored_labels)
        self._cmds = dict()   # type: Dict[str, Union[HassCommand, HassDimmer, HassRgbLight, HassSensor]]
        self._topics = dict()  # type: Dict[str, Action]
        self._config = dict()  # type: Dict[str, str]
        self._data_hooks = set()

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
        return self._m.data()

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
        except ValueError:
            pass
        self._zwn.set_config_param(int(value_id), value)
        LOG.info("Setting %r = %r", value_id, value)

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
                LOG.warning("Spamming node detected %s (%s). Setting 60s timeout.", self._zwn.name,
                            self._zwn.product_name)
                count = -60
        self._spam_tick = (last_time, count)
        return count == 0

    def send_data(self) -> bool:
        result = False
        for hook in self._data_hooks:
            result = hook() or result
        return result

    def _collect_initial_sensor_data(self):
        """
        Send all sensor data, return true if something was relayed forward
        :return: True if data was sent
        """
        values = self._zwn.get_sensors()
        values.update(self._zwn.get_values_for_command_class(COMMAND_CLASS_NOTIFICATION))
        for s_id in values:
            self._m.set_from_value(self._zwn.values[s_id])
        battery = self._zwn.get_battery_level()
        if battery:
            self._m.set_direct("battery", battery)

    def _mqtt_metrics_send(self):
        LOG.info("Sending metrics for %r: %r ", self._zwn.name, self._m.data())
        self._mqtt.send_metrics(self._cmds.get("metrics"), self._m.data())

    def _send_switch_data(self):
        done = False
        for s_id in self._zwn.get_switches():
            if s_id in self._cmds:
                cmd = self._cmds.get(s_id)
                data = self._zwn.get_switch_state(s_id)
                if cmd.should_status_send(data):
                    self._mqtt.send_switch_state(cmd, data)
                    done = True
        return done

    def _send_dimmer_data(self):
        done = False
        for s_id in self._zwn.get_dimmers():
            if s_id in self._cmds:
                cmd = self._cmds.get(s_id)
                data = self._scale_to_hass(self._zwn.get_dimmer_level(s_id))
                if cmd.should_status_send(data):
                    self._mqtt.send_light_state(cmd, data)
                    done = True
        return done

    def _send_rgb_data(self):
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

    def register(self) -> Dict[str, Action]:
        self._register_switches()
        self._register_sensors()
        if not self._register_rgbw():
            self._register_dimmers()
        return self._topics

    def _register_sensors(self) -> bool:
        """
        Registers normal sensors and notification classes as well. Return true if sensors found.
        """
        cmd = self._mqtt.register_metrics(self._zwn.location, self._zwn.name)
        self._cmds["metrics"] = cmd
        for s_id in self._zwn.get_sensors():
            v = self._zwn.values[s_id]  # type: ZWaveValue
            cmd.add_metric(self._labels.get_true_label(v))
            LOG.info("Sensor %s / %s", self._zwn.name, self._labels.get_true_label(v))
        for s_id in self._zwn.get_values_for_command_class(COMMAND_CLASS_NOTIFICATION):
            v = self._zwn.values[s_id]  # type: ZWaveValue
            cmd.add_metric(self._labels.get_true_label(v))
            LOG.info("Sensor (Notification) %s / %s", self._zwn.name, self._labels.get_true_label(v))
        if self._zwn.get_battery_level():
            cmd.add_metric("battery")
        self._collect_initial_sensor_data()
        return True

    def _register_switches(self):
        for s_id in self._zwn.get_switches():
            if s_id in self._cmds:
                continue
            v = self._zwn.values[s_id]  # type: ZWaveValue
            cmd = self._mqtt.register_switch(self._zwn.location, self._zwn.name, self._labels.get_true_label(v))
            self._cmds[s_id] = cmd
            action = SwitchAction(self._zwn, v.value_id)
            self._topics[cmd.command] = action
            LOG.info("Switch %s / %s", self._zwn.name, self._labels.get_true_label(v))
            self._data_hooks.add(self._send_switch_data)

    def _register_dimmers(self) -> Dict[str, Action]:
        for s_id in self._zwn.get_dimmers():
            if s_id in self._cmds:
                continue
            v = self._zwn.values[s_id]  # type: ZWaveValue
            cmd = self._mqtt.register_light(self._zwn.location, self._zwn.name, self._labels.get_true_label(v))
            self._cmds[s_id] = cmd
            self._topics[cmd.command] = DimmerAction(self._zwn, v.value_id)
            LOG.info("Light %s / %s", self._zwn.name, self._labels.get_true_label(v))
            self._data_hooks.add(self._send_dimmer_data)
        return self._topics

    def _register_rgbw(self) -> bool:
        """
        Register RGBW lights.
        :return: At least one light found
        """
        found = False
        for s_id in self._zwn.get_rgbbulbs():
            found = True
            if s_id in self._cmds:
                continue
            v = self._zwn.values[s_id]  # type: ZWaveValue
            cmd = self._mqtt.register_rgb_light(self._zwn.location, self._zwn.name, self._labels.get_true_label(v))
            self._cmds[s_id] = cmd
            self._topics[cmd.command] = RgbAction(self._zwn, v.value_id)
            LOG.info("RGBLight %s / %s", self._zwn.name, self._labels.get_true_label(v))
            self._data_hooks.add(self._send_rgb_data)
        return found

    def update_state(self, value: ZWaveValue) -> bool:
        if value.command_class in SENSORS:
            LOG.info("Sensor data, %s => %s=%r", self.name(), value.label, value.data)
            self._m.set_from_value(value)
            if self._m.should_send():
                self._mqtt_metrics_send()
            return True
        elif value.command_class == COMMAND_CLASS_DIMMER:
            LOG.info("Dimmer data, %s => %s=%r", self.name(), value.label, value.data)
            if self._send_rgb_data():
                return True
            self._send_dimmer_data()
            return True
        elif value.command_class == COMMAND_CLASS_SWITCH:
            if self._send_switch_data():
                LOG.info("Switch data, %s => %s=%r", self.name(), value.label, value.data)
            return True
        elif value.command_class == COMMAND_CLASS_RGB:
            if self._send_rgb_data():
                LOG.info("RGB data, %s => %s=%r", self.name(), value.label, value.data)
            return True
        return False
