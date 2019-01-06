import json
import logging

from zwave_mqtt_bridge.hass_mqtt import HassMqtt
from openzwave.node import ZWaveNode, ZWaveValue

_log = logging.getLogger("operations")

# TODO: State updates are sometimes received in middle of transition phase, ignore state changes right after action


class Device:

    def __init__(self, label: str, zwn: ZWaveNode, hass_mqtt: HassMqtt, zw_id: int, op_type: str):
        self._zwn = zwn
        self._hass_mqtt = hass_mqtt
        self._zw_id = zw_id
        self._op_type = op_type
        self.name = self._zwn.name
        self.label = label
        location = self._zwn.location
        self.topic_command = location + "/" + op_type + "/" + self.name + "/" + label + "/set"
        self.topic_status = location + "/" + op_type + "/" + self.name + "/" + label + "/status"
        self._hass_mqtt.register(self.topic_command, self)

    def mqtt_message(self, data):
        """
        Action from MQTT to the device operation

        :param data: Raw data
        :return: None
        """
        _log.warning("%r has not implemented mqtt_message. Message was %r", self, data)

    def generate_config(self):
        return {self._op_type: [
            {"platform": "mqtt",
             "qos": 0,
             "optimistic": False,
             "name": self.name,
             }]}

    def zwave_message(self, value: ZWaveValue):
        _log.warning("%r has not implemented zwave_message. Message was %r", self, value.data)

    def __repr__(self):
        return "<Device: %s>" % self._op_type


class SwitchDevice(Device):

    def __init__(self, label: str, zwn: ZWaveNode, hass_mqtt: HassMqtt, zw_id: int):
        self.state = zwn.get_switch_state(zw_id)
        Device.__init__(self, label, zwn, hass_mqtt, zw_id, "switch")
        self._hass_mqtt.publish_switch(self.topic_status, self.state)

    def mqtt_message(self, data):
        toggle = data in [b"ON", b"True"]
        _log.info("Action [Switch]: %s (%i) => %r", self._zwn.name, self._zw_id, toggle)
        self._zwn.set_switch(self._zw_id, toggle)

    def zwave_message(self, value: ZWaveValue):
        toggle = True if value.data else False
        if toggle != self.state:
            _log.info("Update [Switch]: %s (%i) => %r", self._zwn.name, self._zw_id, toggle)
            self.state = toggle
            self._hass_mqtt.publish_switch(self.topic_status, self.state)

    def generate_config(self):
        return {self._op_type: [
            {
                "platform": "mqtt",
                "qos": 0,
                "optimistic": False,
                "name": self.name + "_" + self.label,
                "command_topic": self.topic_command,
                "state_topic": self.topic_status,
                "payload_on": "ON",
                "payload_off": "OFF",
                "state_value_template": "{{ value_json.state }}"
            }
        ]}

    def __repr__(self):
        return "<SwitchDevice> Toggle: %r" % self.state


class DimmerDevice(Device):

    def __init__(self, label: str, zwn: ZWaveNode, hass_mqtt: HassMqtt, zw_id: int):
        self.brightness = zwn.get_dimmer_level(zw_id)
        Device.__init__(self, label, zwn, hass_mqtt, zw_id, "light")
        self._hass_mqtt.publish_light_state(self.topic_status, brightness=self._hass_brightness(self.brightness))

    def _hass_brightness(self, value: int):
        return int(value * 255 / 99)

    def zwave_message(self, value: ZWaveValue):
        new_brightness = value.data
        if new_brightness != self.brightness:
            _log.info("Update [Dimmer]: %s (%i) => %i", self._zwn.name, self._zw_id, new_brightness)
            self.brightness = new_brightness
            self._hass_mqtt.publish_light_state(self.topic_status, brightness=self._hass_brightness(self.brightness))

    def mqtt_message(self, data):
        data = json.loads(data.decode("utf8"))
        state = data.get("state")
        brightness = 0
        if state in ["ON", "True"]:
            brightness = int(data.get("brightness", 255) * 99 / 255)
        self._zwn.set_dimmer(self._zw_id, brightness)
        _log.info("Action [Dimmer]: %s (%i) => %i", self._zwn.name, self._zw_id, brightness)

    def generate_config(self):
        return {self._op_type: [
            {
                "platform": "mqtt",
                "qos": 0,
                "optimistic": False,
                "name": self.name + "_" + self.label,
                "command_topic": self.topic_command,
                "state_topic": self.topic_status,
                "payload_on": "ON",
                "payload_off": "OFF",
                "state_value_template": "{{ value_json.state }}",
                "brightness": True,
                "schema": "json"
            }
        ]}

    def __repr__(self):
        return "<DimmerDevice> Brightness: %i" % self.brightness


class RgbDevice(Device):
    """
    Z-Wave returns RGBW data in following format: #FFFFFFFF
    """
    def __init__(self, label: str, zwn: ZWaveNode, hass_mqtt: HassMqtt, zw_id: int):
        self.rgbw = zwn.get_rgbw(zw_id)
        Device.__init__(self, label, zwn, hass_mqtt, zw_id, "light")
        self._hass_mqtt.publish_rgb_state(self.topic_status, self._unwrap_zwave_data(self.rgbw))

    @staticmethod
    def _unwrap_zwave_data(raw):
        return [int("0x" + raw[1:3], 16),
                int("0x" + raw[3:5], 16),
                int("0x" + raw[5:7], 16),
                int("0x" + raw[7:9], 16)]

    def zwave_message(self, value: ZWaveValue):
        if value.data != self.rgbw:
            self.rgbw = value.data
            _log.info("Update [RGB]: %s (%i) => %s", self._zwn.name, self._zw_id, value.data)
            self._hass_mqtt.publish_rgb_state(self.topic_status, self._unwrap_zwave_data(self.rgbw))

    def mqtt_message(self, data):
        data = json.loads(data.decode("utf8"))
        state = data.get("state")
        r_color = data.get("color")
        r_white = data.get("white_value")
        r, g, b, w = ["00"] * 4
        _log.info(data)
        if state in ["ON", "True"]:
            r, g, b, w = [self.rgbw[n*2+1:(n+1)*2+1] for n in range(0, 4)]
            if r_white:
                w = "{0:#0{1}x}".format(r_white, 4).upper()[2:4]
            elif r_color:
                r, g, b = ["{0:#0{1}x}".format(r_color[k], 4).upper()[2:4] for k in ["r", "g", "b"]]
            else:
                r, g, b, w = ["FF"] * 4
        color = "#" + r + g + b + w
        _log.info("Action [RGB]: %s (%i) => %s", self._zwn.name, self._zw_id, color)
        self._zwn.set_rgbw(self._zw_id, color)
        # RGBW value can occasionally be reported from transition state, to fight this assume the color is set correctly
        self._hass_mqtt.publish_rgb_state(self.topic_status, self._unwrap_zwave_data(self.rgbw))

    def generate_config(self):
        return {self._op_type: [
            {
                "platform": "mqtt",
                "qos": 0,
                "optimistic": False,
                "name": self.name + "_" + self.label,
                "command_topic": self.topic_command,
                "state_topic": self.topic_status,
                "payload_on": "ON",
                "payload_off": "OFF",
                "state_value_template": "{{ value_json.state }}",
                "brightness": True,
                "schema": "json",
                "rgb": True,
                "white_value": True
            }
        ]}

    def __repr__(self):
        return "<RgbDevice> RGBW: %s" % self.rgbw
