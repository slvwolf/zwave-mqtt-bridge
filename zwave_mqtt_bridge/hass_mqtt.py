from typing import Dict

import paho.mqtt.client as mqtt
import json
import logging

log = logging.getLogger("hass_mqtt")
log.setLevel(logging.DEBUG)

class HassBase:

    def __init__(self, location: str, device_type: str, name: str, platform: str):
        if not location:
            location = "house"
        self._name = name
        self._domain = location
        self._platform = platform
        self._device_type = device_type

    def generate_config(self):
        return {self._device_type: [
            {"platform": self._platform,
             "qos": 0,
             "optimistic": False,
             "name": self._name,
             }]}

    def __repr__(self):
        return "HassBase<" + self._name + ">"


class HassCommand(HassBase):

    def __init__(self, location: str, device_type: str, name: str, second_name: str, platform: str="mqtt"):
        HassBase.__init__(self, location, device_type, name, platform)
        self.command = location + "/" + device_type + "/" + name + "/" + second_name + "/set"
        self.status = location + "/" + device_type + "/" + name + "/" + second_name + "/status"
        self._second_name = second_name

    def register_all(self, mqttc: mqtt.Client):
        log.info("Subscribing to: " + self.command)
        mqttc.subscribe(self.command)

    def generate_config(self):
        data = HassBase.generate_config(self)
        v = data[self._device_type][0]
        v["name"] = self._name + "_" + self._second_name
        v["command_topic"] = self.command
        v["state_topic"] = self.status
        if self._platform == "mqtt":
            v["payload_on"] = "ON"
            v["payload_off"] = "OFF"
            v["state_value_template"] = "{{ value_json.state }}"
        return data

    def __repr__(self):
        return "HassCommand<" + self._name + "_" + self._second_name + ">"


class HassDimmer(HassCommand):

    def __init__(self, domain: str, name: str, light_name: str):
        HassCommand.__init__(self, domain, "light", name, light_name)
        self.brightness = domain + "/light/" + name + "/" + light_name + "/brightness/set"
        self.status_brightness = domain + "/light/" + name + "/" + light_name + "/brightness/status"

    def generate_config(self):
        data = HassCommand.generate_config(self)
        v = data[self._device_type][0]
        v["brightness_value_template"] = "{{ value_json.brightness }}"
        v["brightness_state_topic"] = self.status_brightness
        v["brightness_command_topic"] = self.brightness
        v["state_value_template"] = "{{ value_json.state }}"
        return data

    def __repr__(self):
        return "HassDimmer<" + self._name + "_" + self._second_name + ">"


class HassRgbLight(HassDimmer):

    def __init__(self, domain: str, name: str, light_name: str):
        HassDimmer.__init__(self, domain, name, light_name)
        self.rgb = domain + "/light/" + name + "/" + light_name + "/rgb/set"
        self.status_rgb = domain + "/light/" + name + "/" + light_name + "/rgb/status"

    def register_all(self, mqttc: mqtt.Client):
        HassDimmer.register_all(self, mqttc)
        log.info("Subscribing to: " + self.rgb)
        mqttc.subscribe(self.rgb)
        log.info("Subscribing to: " + self.brightness)
        mqttc.subscribe(self.brightness)

    def generate_config(self):
        data = HassDimmer.generate_config(self)
        v = data[self._device_type][0]
        v["rgb_state_topic"] = self.status_rgb
        v["rgb_command_topic"] = self.rgb
        v["rgb_value_template"] = "{{ value_json.rgb | join(',') }}"
        return data

    def __repr__(self):
        return "HassRGB<" + self._name + "_" + self._second_name + ">"


class HassSensor(HassBase):

    def __init__(self, location: str, name: str):
        HassBase.__init__(self, location, "sensor", name)
        self._metrics = set()
        self.status_metric = "/".join([self._domain, self._device_type, name, "sensor"])

    def add_metric(self, metric: str):
        self._metrics.add(metric)

    def generate_config(self):
        """
        Example,

        sensor:
          - platform: mqtt
            name: "Temperature"
            state_topic: "office/sensor1"
            unit_of_measurement: '°C'
            value_template: "{{ value_json.temperature }}"
        """
        data = {"sensor": []}
        for m in self._metrics:
            data["sensor"].append({
                "platform": "mqtt",
                "name": self._name + "_" + m,
                "state_topic": self.status_metric,
                "value_template": "{{ value_json.%s }}" % m
            })
        return data


class HassMqtt:
    def __init__(self, client_id, host: str, username: str, password: str):
        self._mqttc = mqtt.Client(client_id=client_id)
        self._mqttc.enable_logger(log)
        if username and password:
            self._mqttc.username_pw_set(username, password)
        self._mqttc.connect(host)
        self._mqttc.on_message = self._on_message
        self._mqttc.loop_start()
        self.on_message = None

    def _on_message(self, client, userdata, message: mqtt.MQTTMessage):
        if self.on_message:
            self.on_message(message.topic, message.payload)

    def register_metrics(self, location, name):
        log.info("Setting up sensor: %r / %r" % (name, name))
        topic = HassSensor(location, name)
        return topic

    def send_switch_config(self, location: str, name: str, switch_name: str):
        log.info("Setting up switch: %r / %r" % (name, switch_name))
        topic = HassCommand(location, "switch", name, switch_name)
        topic.register_all(self._mqttc)
        return topic

    def send_light_config(self, location: str, name: str, light_name: str) -> HassDimmer:
        log.info("Setting up light: %r / %r" % (name, light_name))
        topic = HassDimmer(location, name, light_name)
        topic.register_all(self._mqttc)
        return topic

    def send_rgb_light_config(self, location: str, name: str, light_name: str) -> HassRgbLight:
        log.info("Setting up RGB light: %r / %r" % (name, light_name))
        topic = HassRgbLight(location, name, light_name)
        topic.register_all(self._mqttc)
        return topic

    def send_metrics(self, cmd: HassSensor, metric_map: Dict):
        if cmd and metric_map:
            self._mqttc.publish(cmd.status_metric, payload=json.dumps(metric_map), retain=True)

    def send_dimmer_state(self, cmd: HassDimmer, brightness: int):
        log.info("Sending dimmer state: %r = %r", cmd, brightness)
        data = "OFF" if brightness == 0 else "ON"
        self._mqttc.publish(cmd.status, json.dumps({"state": data}), retain=True)
        self._mqttc.publish(cmd.status_brightness, json.dumps({"brightness": brightness}), retain=True)

    def send_switch_state(self, cmd: HassDimmer, state: bool):
        log.info("Sending switch state: %r = %r", cmd, state)
        data = "OFF" if not state else "ON"
        log.debug("Publish: %r ==> %r", cmd.status, data)
        self._mqttc.publish(cmd.status, data, retain=True)
