# zwave-mqtt-bridge

_Service for bridging ZWave components to Home Assistant over MQTT._

Note: Project is in prototype state so expect some rough edges

## Supported Devices

- Sensors
- Binary sensors
- Light controls
- Light brightness

## Known issues

- RGB light colors are not controllable
- Auto discovery messages are sent only during initialization (bridge needs to be restarted if Home Assistant is
rebooted)

