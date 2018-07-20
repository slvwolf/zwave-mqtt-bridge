import logging

from apistar import ASyncApp, Route, App, http

from main import ZWaveComponent
from zwave_mqtt_bridge.bridge import Bridge

logging.basicConfig(level=logging.DEBUG)
_log = logging.getLogger("main")


def index(app: App, bridge: Bridge):
    try:
        nodes = bridge.nodes()
        return app.render_template('index.html', nodes=nodes)
    except Exception as e:
        _log.warning("Could not show index", e)


def route_node(app: App, bridge: Bridge, r_node: str):
    try:
        node = bridge.nodes().get(r_node)
        if not node:
            for n in bridge.nodes().values():
                if str(n.id()) == r_node:
                    node = n
                    break
        if not node:
            return http.JSONResponse({"error": "not_found",
                                      "requested_node": r_node,
                                      "available_nodes": bridge.nodes().keys()},
                                     status_code=404)
        return app.render_template('node.html', node=node)
    except Exception as e:
        _log.warning("Could not show index", e)


def set_config(bridge: Bridge, node_id: int, value_id: int, value: str):
    bridge.set_config(node_id, value_id, value)
    return {"msg": "Setting done"}


def push_configs(bridge: Bridge):
    bridge.register_all()
    return {"msg": "All nodes registered to HA"}


routes = [
    Route('/', 'GET', index),
    Route('/nodes/{r_node}', 'GET', route_node),
    Route('/nodes/{node_id}/config/{value_id}', 'PUT', set_config),
    Route('/ha/register', 'POST', push_configs),
]

_log.info("Creating application")
app = ASyncApp(routes=routes,
               components=[ZWaveComponent()],
               template_dir="templates",
               static_dir="static")

if __name__ == '__main__':
    _log.info("Starting app")
    app.serve('0.0.0.0', 5000, debug=False)
