from typing import Any

import paho.mqtt.client as mqtt
import json
import logging

log = logging.getLogger("bridge")


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

    def send_sensor_config(self, name, sensor_type, metric_name, metric_unit):
        msg = json.dumps({
            "device_class": sensor_type,
            "name": name + "_" + metric_name,
            "state_topic": "homeassistant/" + sensor_type + "/" + name + "/state",
            "unit_of_measurement": metric_unit,
            "value_template": "{{ value_json." + metric_name + " }}"})
        config_uri = "homeassistant/" + sensor_type + "/" + name + "_" + metric_name + "/config"
        self._mqttc.publish(config_uri, payload=msg)

    def send_switch_config(self, name: str, switch_name: str):
        config_uri = "homeassistant/switch/" + name + "_" + switch_name + "/config"
        command_topic = "cmd/switch/" + name + "/" + switch_name + "/set"
        self._mqttc.subscribe(command_topic)
        msg =json.dumps({
            "device_class": "switch",
            "name": name + "_" + switch_name,
            "state_topic": "homeassistant/switch/" + name + "/state",
            "value_template": "{{ value_json." + switch_name + " }}",
            "command_topic": command_topic,
            "unit_of_measurement": "x",
            "payload_on": "ON",
            "payload_off": "OFF"})
        self._mqttc.publish(config_uri, payload=msg)
        return command_topic

    def send_light_config(self, name: str, light_name: str):
        config_uri = "homeassistant/light/" + name + "_" + light_name + "/config"
        command_topic = "cmd/light/" + name + "/" + light_name + "/set"
        self._mqttc.subscribe(command_topic)
        msg = json.dumps({
            "device_class": "light",
            "name": name + "_" + light_name,
            "state_topic": "homeassistant/light/" + name + "/state",
            "value_template": "{{ value_json." + light_name + " }}",
            "payload_on": "ON",
            "payload_off": "OFF",
            "command_topic": command_topic})
        self._mqttc.publish(config_uri, payload=msg)
        return command_topic

    def send_rgb_light_config(self, name: str, light_name: str):
        config_uri = "homeassistant/light/" + name + "_" + light_name + "/config"
        command_topic = "cmd/light/" + name + "/" + light_name + "/set"
        rbg_topic = "cmd/light/" + name + "/" + light_name + "/rgb/set"
        b_topic = "cmd/light/" + name + "/" + light_name + "/brightness/set"
        self._mqttc.subscribe(command_topic)
        self._mqttc.subscribe(rbg_topic)
        self._mqttc.subscribe(b_topic)
        msg = json.dumps({
            "device_class": "light",
            "name": name + "_" + light_name,
            "command_topic": command_topic,
            "state_topic": "homeassistant/light/" + name + "/state",
            "rgb_state_topic": "homeassistant/light/" + name + "/rgb/state",
            "brightness_state_topic":  "homeassistant/light/" + name + "/brightness/state",
            "brightness_command_topic": b_topic,
            "value_template": "{{ value_json." + light_name + " }}",
            "rgb_value_template": "{{ value_json.rgb | join(',') }}",
            "brightness_value_template": "{{ value_json.brightness }}",
            "rgb_command_template": "{{ value.red }},{{ value.green }},{{ value.blue }}",
            "rgb_command_topic": rbg_topic,
            "payload_on": "ON",
            "payload_off": "OFF"})
        self._mqttc.publish(config_uri, payload=msg)
        return command_topic, rbg_topic, b_topic

    def send_metrics(self, device_class: str, name: str, metric_map: Any, state: str="state"):
        self._mqttc.publish("homeassistant/" + device_class + "/" + name + "/" + state,
                            payload=json.dumps(metric_map))

