from typing import Dict, List

import paho.mqtt.client as mqtt
import json
import logging

LOG = logging.getLogger("hass_mqtt")


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


class HassSensor(HassBase):

    def __init__(self, location: str, name: str):
        HassBase.__init__(self, location, "sensor", name, "mqtt")
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
        LOG.info("Initialising MQTT")
        self._mqttc = mqtt.Client(client_id=client_id)
        self._mqttc.enable_logger(LOG)
        if username and password:
            self._mqttc.username_pw_set(username, password)
        LOG.info("Connecting MQTT")
        self._mqttc.connect(host)
        self._mqttc.on_message = self._on_message
        self._mqttc.loop_start()
        self.on_message = None
        self._map = {}
        LOG.info("MQTT ready")

    def _on_message(self, client, userdata, message: mqtt.MQTTMessage):
        LOG.debug("Topic %r received message %r" % (message.topic, message.payload))
        route = self._map.get(message.topic)
        if route:
            route.mqtt_message(message.payload)
        else:
            if self.on_message:
                self.on_message(message.topic, message.payload)

    def register(self, topic, listener):
        LOG.info("Topic %r registered for %r", topic, listener)
        self._map[topic] = listener
        self._mqttc.subscribe(topic)

    def register_metrics(self, location, name):
        LOG.info("Setting up sensor: %r / %r" % (name, name))
        topic = HassSensor(location, name)
        return topic

    def send_metrics(self, cmd: HassSensor, metric_map: Dict):
        if cmd and metric_map:
            #LOG.info("MQTT Metrics send: %r => %r", cmd.status_metric, metric_map)
            self._mqttc.publish(cmd.status_metric, payload=json.dumps(metric_map), retain=True)

    def publish_light_state(self, topic: str, brightness: int = None, color: List[int] = None):
        """
        Example message for mqtt / json lights
            {
              "brightness": 255,
              "color_temp": 155,
              "color": {
                "r": 255,
                "g": 180,
                "b": 200,
                "x": 0.406,
                "y": 0.301,
                "h": 344.0,
                "s": 29.412
              },
              "effect": "colorloop",
              "state": "ON",
              "transition": 2,
              "white_value": 150
            }
        """
        if brightness is None:
            brightness = color[3] if color else 255
        data = {"state": "OFF" if brightness == 0 else "ON",
                "brightness": brightness}
        if color:
            data["color"] = {
                "r": color[0],
                "g": color[1],
                "b": color[2]
            }
            if len(color) == 4:
                data["white_value"] = color[3]
        LOG.debug("Sending light state: %r = %r", topic, data)
        self._mqttc.publish(topic, json.dumps(data), retain=True)

    def publish_rgb_state(self, topic: str, color: List[int]):
        if sum(color) == 0:
            data = {"state": "OFF"}
        else:
            data = {"state": "ON",
                    "brightness": 255,
                    "color": {"r": color[0],
                              "g": color[1],
                              "b": color[2]}
                    }
            if len(color) == 4:
                data["white_value"] = color[3]
        LOG.debug("Sending light state: %r = %r", topic, data)
        self._mqttc.publish(topic, json.dumps(data), retain=True)

    def publish_switch(self, topic: str, state: bool):
        data = "OFF" if not state else "ON"
        LOG.debug("Publish: %r ==> %r", topic, data)
        self._mqttc.publish(topic, data, retain=True)
