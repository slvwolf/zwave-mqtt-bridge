from apistar import Include, Route, Component, render_template, annotate
from apistar.frameworks.asyncio import ASyncIOApp as App
from apistar.handlers import docs_urls, static_urls
from apistar.renderers import HTMLRenderer

from main import ZWaveComponent, init_zwave_component

settings = {
    'TEMPLATES': {
        'ROOT_DIR': 'templates',     # Include the 'templates/' directory.
        'PACKAGE_DIRS': ['apistar']  # Include the built-in apistar templates.
    }
}


@annotate(renderers=[HTMLRenderer()])
def index(zw: ZWaveComponent):
    nodes = zw.zw_service.nodes()
    return render_template('index.html', nodes=nodes)


def set_config(zw: ZWaveComponent, node_id: int, value_id: int, value: str):
    zw.zw_service.set_config(node_id, value_id, value)
    return {"msg": "Setting done"}

routes = [
    Route('/', 'GET', index),
    Route('/nodes/{node_id}/config/{value_id}', 'PUT', set_config),
    Include('/docs', docs_urls),
    Include('/static', static_urls)
]

app = App(routes=routes,
          settings=settings,
          components=[Component(ZWaveComponent, init_zwave_component)])

if __name__ == '__main__':
    app.main()

