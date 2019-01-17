import logging

from apistar import ASyncApp, Route, App, http

from main import ZWaveComponent
from zwave_mqtt_bridge.bridge import Bridge

logging.basicConfig(level=logging.DEBUG,
                    format='%(asctime)s %(name)-12s %(levelname)-8s %(message)s',
                    datefmt='%m-%d %H:%M',
                    filename='zwave-gate.log',
                    filemode='w')
_log = logging.getLogger("main")


def index(app: App, bridge: Bridge):
    try:
        nodes = bridge.nodes()
        return app.render_template('index.html', nodes=nodes, network=bridge.zw_network)
    except Exception as e:
        _log.warning("Could not show index", e)


def _r(app: App, bridge: Bridge, r_node: str, page: str):
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
        return app.render_template('node%s.html' % page, node=node)
    except Exception as e:
        _log.warning("Could not show index", e)


def route_node(app: App, bridge: Bridge, r_node: str):
    return _r(app, bridge, r_node, "")


def route_commands(app: App, bridge: Bridge, r_node: str):
    return _r(app, bridge, r_node, "_commands")


def route_config(app: App, bridge: Bridge, r_node: str):
    return _r(app, bridge, r_node, "_config")


def route_metrics(app: App, bridge: Bridge, r_node: str):
    return _r(app, bridge, r_node, "_metrics")


def set_config(bridge: Bridge, node_id: int, value_id: int, value: str):
    try:
        bridge.set_config(node_id, value_id, value)
    except Exception as e:
        _log.error(e)
        raise e
    return {"msg": "Setting done"}


def push_configs(bridge: Bridge):
    bridge.register_all()
    return {"msg": "All nodes registered to HA"}


def html_node_cmd(action, node_id, result_f):
    try:
        return app.render_template('node_cmd.html', action=action, node_id=node_id, result=result_f())
    except Exception as e:
        _log.warning("Could not show index", e)
    return {"msg": "Error"}


def heal_node(bridge: Bridge, node_id: int):
    return html_node_cmd("Heal", node_id, lambda: bridge.heal(node_id))


def add_node(bridge: Bridge):
    r = bridge.add_node()
    return {"msg": "Waiting to add node (%r)" % r}


def remove_node(bridge: Bridge):
    r = bridge.zw_network.controller.remove_node()
    return {"msg": "Waiting to remove node (%r)" % r}


def rename_node(bridge: Bridge, node_id: int, name: str):
    r = bridge.rename_node(node_id, name)
    return {"msg": "Renamed (%r)" % r}


def network_update(bridge: Bridge, node_id: int):
    return html_node_cmd("Network Update", node_id, lambda: bridge.network_update(node_id))


def neighbor_update(bridge: Bridge, node_id: int):
    return html_node_cmd("Neighbor Update", node_id, lambda: bridge.neighbor_update(node_id))


def remove_faulty_node(bridge: Bridge, node_id: int):
    return html_node_cmd("Remove Faulty Node", node_id, lambda: bridge.zw_network.controller.remove_failed_node(node_id))


def heal_network(bridge: Bridge):
    bridge.network_heal()
    return {"msg": "Setting done"}


def write_config(bridge: Bridge):
    bridge.write_config()
    return {"msg": "Setting done"}


def update_config(bridge: Bridge):
    r = bridge.update_config()
    return {"msg": "%r" % r}


def refresh_info(bridge: Bridge, node_id: int):
    return html_node_cmd("Refresh", node_id, lambda: bridge.refresh_info(node_id))


routes = [
    Route('/', 'GET', index),
    Route('/network/write_config', 'GET', write_config),
    Route('/controller/add_node', 'GET', add_node),
    Route('/controller/remove_node', 'GET', remove_node),
    Route('/controller/update_config', 'GET', update_config),
    Route('/network/heal', 'GET', heal_network),
    Route('/nodes/{r_node}', 'GET', route_node),
    Route('/nodes/{r_node}/commands', 'GET', route_commands),
    Route('/nodes/{r_node}/config', 'GET', route_config),
    Route('/nodes/{r_node}/metrics', 'GET', route_metrics),

    Route('/nodes/{node_id}/config/{value_id}', 'PUT', set_config),
    Route('/nodes/{node_id}/heal', 'GET', heal_node),
    Route('/nodes/{node_id}/refresh', 'GET', refresh_info),
    Route('/nodes/{node_id}/network', 'GET', network_update),
    Route('/nodes/{node_id}/neighbor', 'GET', neighbor_update),
    Route('/nodes/{node_id}/remove', 'GET', remove_faulty_node),
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
