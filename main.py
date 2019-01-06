import time
import logging
import yaml
import sys

from apistar import Component
from openzwave.network import ZWaveNetwork
from openzwave.option import ZWaveOption
from pydispatch import dispatcher

from zwave_mqtt_bridge.bridge import Bridge
from zwave_mqtt_bridge.hass_mqtt import HassMqtt


LOG = logging.getLogger("bridge")


class ZWaveComponent(Component):
    preload = True

    def resolve(self) -> Bridge:
        return self.zw_service

    def __init__(self):
        Component.__init__(self)
        config_file = "config.yaml"
        data = yaml.load(open(config_file))
        config_path = data.get("zwave", {}).get("config")
        device = data.get("zwave", {}).get("device")
        ignored_labels = data.get("bridge", {}).get("ignored", [])
        mqtt_host = data.get("mqtt", {}).get("host")
        user = data.get("mqtt", {}).get("user")
        password = data.get("mqtt", {}).get("password")

        if not config_path or not device:
            LOG.warning("Configuration is invalid, please see examples for reference")
            sys.exit(-1)

        mqtt = HassMqtt("zwave", mqtt_host, user, password)
        zw_service = Bridge(mqtt, ignored_labels)

        options = ZWaveOption(device, config_path=config_path, user_path=".", cmd_line="")
        options.set_log_file("OZW_Log.log")
        options.set_append_log_file(False)
        options.set_console_output(False)
        options.set_save_log_level('Alert')
        options.set_logging(False)
        options.lock()
        zw_network = ZWaveNetwork(options, log=None)

        def network_ready(network):
            LOG.info("Network ready, %d nodes ready", network.nodes_count)

        def network_failed(network):
            LOG.info("Network failed to load. Found %d nodes", network.nodes_count)

        def network_started(network):
            LOG.info("Network started. Found %d nodes.", network.nodes_count)
            dispatcher.connect(zw_service.value_update, ZWaveNetwork.SIGNAL_VALUE)

        dispatcher.connect(network_started, ZWaveNetwork.SIGNAL_NETWORK_STARTED)
        dispatcher.connect(network_failed, ZWaveNetwork.SIGNAL_NETWORK_FAILED)
        dispatcher.connect(network_ready, ZWaveNetwork.SIGNAL_NETWORK_READY)

        LOG.info("*"*30)
        LOG.info("Starting network..")
        self.zw_service = zw_service
        self.zw_service.zw_network = zw_network

        zw_network.start()
        try:
            for i in range(0, 300):
                if zw_network.state >= zw_network.STATE_AWAKED:
                    LOG.info("Network is ready (or actually AWAKED, but should be ok)")
                    break
                else:
                    time.sleep(5.0)
                    LOG.info("Waiting.. (%i s). State: %s", i*5, zw_network.state_str)
            LOG.info("Starting run..")
            time.sleep(1)
            LOG.info("Registering all..")
            zw_service.register_all()
            time.sleep(1)
            LOG.info("Diving into event loop..")
        except InterruptedError as e:
            LOG.info("Interrupted")
            zw_network.stop()
            time.sleep(10)
            raise e
        except KeyboardInterrupt:
            LOG.info("Interrupted")
            zw_network.stop()
        except Exception as e:
            LOG.error(e)
            zw_network.stop()
            time.sleep(10)
            raise e


def init_zwave_component():
    return ZWaveComponent()

