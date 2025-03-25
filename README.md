# zwave-mqtt-bridge

_Service for bridging ZWave components to Home Assistant over MQTT._

**This project is no longer maintained**

Note: Project is in prototype state so expect some rough edges

## Intalling and Running

    pip3 install -t requirements.txt 
    cp example_config.yaml config.yaml

Do the necessary changes to `config.yaml` and run,

    export LC_ALL=C.UTF-8
    export LANG=C.UTF-8
    apistar run
    
Production run

    export LC_ALL=C.UTF-8
    export LANG=C.UTF-8
    uvicorn app:app --port 5000 --host 0.0.0.0

Service will open up status page on `http://127.0.0.1:5000`

## Supported Devices

- Sensors
- Binary sensors
- All Lights

## Known issues
- RGB State is not supported
