import itertools
import time
import logging
import yaml
from typing import Dict, List
from openzwave.node import ZWaveNode
from openzwave.value import ZWaveValue
from zwave_mqtt_bridge.command_classes import SENSORS, COMMAND_CLASS_NOTIFICATION
from zwave_mqtt_bridge.devices import SwitchDevice, DimmerDevice, RgbDevice
from zwave_mqtt_bridge.hass_mqtt import HassMqtt

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
        if isinstance(value, bool):
            value = "on" if value else "off"
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
            # Fix for some sensors not always registering sensor movement
            if label == "burglar":
                self.set_direct("sensor", "on" if int(new_value) > 0 else "off")
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
        self._spam_tick = (time.time(), 600)
        self._labels = Labels()
        self._m = Metrics(self._labels, ignored_labels)
        self._config = dict()  # type: Dict[str, str]
        self._devices = {}
        self._cmds = {}

    @staticmethod
    def _scale_to_hass(data: int) -> int:
        return int(data * 255 / 95)

    def devices(self):
        return self._devices

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
        for dev in itertools.chain(self._cmds.values(), self._devices.values()):
            config = dev.generate_config()
            for key in config.keys():
                if key not in full_set:
                    full_set[key] = []
                full_set[key].extend(config[key])
        return yaml.dump(full_set, default_flow_style=False).replace("\n", "<br>").replace(" ", "&nbsp;")

    def zw_values(self):
        return self._zwn.get_values()

    def registration_state(self) -> str:
        if len(self._devices) > 0:
            return "Actionable"
        if self._cmds.get("metrics"):
            return "Sensor"
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

    def register(self, hass_mqtt: HassMqtt):
        self.__register_devices(self._zwn.get_switches(), SwitchDevice, hass_mqtt)
        self.__register_devices(self._zwn.get_dimmers(), DimmerDevice, hass_mqtt)
        self.__register_devices(self._zwn.get_rgbbulbs(), RgbDevice, hass_mqtt)
        self._register_sensors()

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

    def __register_devices(self, sids: List[int], device_type, hass_mqtt):
        for s_id in sids:
            if s_id in self._devices:
                continue
            v = self._zwn.values[s_id]  # type: ZWaveValue
            LOG.info("Registering %s / %s", self._zwn.name, self._labels.get_true_label(v))
            self._devices[s_id] = device_type(self._labels.get_true_label(v), self._zwn, hass_mqtt, s_id)

    def update_state(self, value: ZWaveValue) -> bool:
        dev = self._devices.get(value.value_id)
        if dev:
            dev.zwave_message(value)
            return True
        if value.command_class in SENSORS:
            LOG.debug("Sensor data, %s => %s=%r", self.name(), value.label, value.data)
            self._m.set_from_value(value)
            if self._m.should_send():
                self._mqtt_metrics_send()
            return True
        return False

    def get_raw_zwn(self) -> ZWaveNode:
        return self._zwn
