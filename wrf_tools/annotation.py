import json
import webbrowser
from pathlib import Path
from threading import Timer
from typing import Any

import click
import dash_leaflet as dl
import yaml
from dash import (
    Dash,
    dcc,
    html,
    Input,
    Output,
    State,
    callback,
    callback_context,
    ALL,
    no_update,
)
from PIL import Image
import plotly.graph_objects as go


class AnnotationManager:
    """Manages loading and saving annotations and geographic points to YAML."""

    def __init__(self, yaml_path: Path, data_dir: Path):
        self.yaml_path = yaml_path
        self.data_dir = data_dir
        self.annotations: dict[str, dict[str, list[dict[str, Any]]]] = {}
        self.geographic_points: dict[str, dict[str, Any]] = {}
        self.load()

    def load(self) -> None:
        """Load annotations and geographic points from YAML file."""
        if self.yaml_path.exists():
            with open(self.yaml_path) as f:
                data = yaml.safe_load(f)
                if data:
                    self.annotations = data.get("domains", {})
                    self.geographic_points = data.get("geographic_points", {})
                else:
                    self.annotations = {}
                    self.geographic_points = {}
        else:
            self.annotations = {}
            self.geographic_points = {}

    def save(self) -> None:
        """Save annotations and geographic points to YAML file."""
        with open(self.yaml_path, "w") as f:
            yaml.dump(
                {
                    "geographic_points": self.geographic_points,
                    "domains": self.annotations,
                },
                f,
                default_flow_style=False,
                sort_keys=False,
            )

    def get_geographic_points(self) -> dict[str, dict[str, Any]]:
        """Return all named geographic points."""
        return self.geographic_points

    def add_geographic_point(self, key: str, name: str, lat: float, lon: float) -> None:
        """Add a named geographic point."""
        self.geographic_points[key] = {
            "name": name,
            "latitude": lat,
            "longitude": lon,
        }
        self.save()

    def update_geographic_point(
        self, key: str, name: str, lat: float, lon: float
    ) -> None:
        """Update an existing geographic point."""
        if key in self.geographic_points:
            self.geographic_points[key] = {
                "name": name,
                "latitude": lat,
                "longitude": lon,
            }
            self.save()

    def remove_geographic_point(self, key: str) -> None:
        """Remove a geographic point by key."""
        if key in self.geographic_points:
            del self.geographic_points[key]
            self.save()

    def get_annotations(self, domain: str, image: str) -> list[dict[str, Any]]:
        """Get annotations for a specific domain and image."""
        return self.annotations.get(domain, {}).get(image, [])

    def set_annotations(
        self, domain: str, image: str, annotations: list[dict[str, Any]]
    ) -> None:
        """Set annotations for a specific domain and image."""
        if domain not in self.annotations:
            self.annotations[domain] = {}
        self.annotations[domain][image] = annotations
        self.save()

    def add_annotation(
        self, domain: str, image: str, annotation: dict[str, Any]
    ) -> None:
        """Add a single annotation."""
        annotations = self.get_annotations(domain, image)
        annotations.append(annotation)
        self.set_annotations(domain, image, annotations)

    def remove_annotation(self, domain: str, image: str, index: int) -> None:
        """Remove an annotation by index."""
        annotations = self.get_annotations(domain, image)
        if 0 <= index < len(annotations):
            annotations.pop(index)
            self.set_annotations(domain, image, annotations)

    def update_annotation(
        self, domain: str, image: str, index: int, annotation: dict[str, Any]
    ) -> None:
        """Update an annotation by index."""
        annotations = self.get_annotations(domain, image)
        if 0 <= index < len(annotations):
            annotations[index] = annotation
            self.set_annotations(domain, image, annotations)

    def get_all_annotations(self) -> list[dict[str, Any]]:
        """Return all annotations across all domains/images."""
        all_annotations = []
        for domain, images in self.annotations.items():
            for image, annotations in images.items():
                for idx, ann in enumerate(annotations):
                    all_annotations.append(
                        {
                            "domain": domain,
                            "image": image,
                            "index": idx,
                            **ann,
                        }
                    )
        return all_annotations

    def get_domains(self) -> list[str]:
        """Get list of available domains from the data directory."""
        domains = []
        if self.data_dir.exists():
            for item in self.data_dir.iterdir():
                if item.is_dir() and not item.name.startswith("."):
                    domains.append(item.name)
        return sorted(domains)

    def get_images(self, domain: str) -> list[str]:
        """Get list of images for a domain."""
        images = []
        domain_path = self.data_dir / domain
        if domain_path.exists():
            for ext in ["*.gif", "*.png", "*.jpg", "*.jpeg"]:
                images.extend([f.name for f in domain_path.glob(ext)])
        return sorted(images)


class App:
    def __init__(self, data_dir: Path, annotations_file: Path) -> None:
        self.dash = Dash(__name__, suppress_callback_exceptions=True)
        self.manager = AnnotationManager(annotations_file, data_dir)
        self.data_dir = data_dir

        self.annotation_tab = AnnotateImageTab(self)
        self.points_tab = GeographicPointsTab(self)
        self.management_tab = ManageAnnotationsTab(self)

        self.dash.layout = self.render_content()
        self.register_callbacks()

    def render_content(self) -> html.Div:
        return html.Div(
            [
                html.H1("WRF Image Annotation Tool", style={"textAlign": "center"}),
                dcc.Tabs(
                    id="main-tabs",
                    value="tab-annotate",
                    children=[
                        dcc.Tab(label="Annotate Images", value="tab-annotate"),
                        dcc.Tab(label="Geographic Points", value="tab-points"),
                        dcc.Tab(label="Manage Annotations", value="tab-manage"),
                    ],
                ),
                html.Div(id="tab-content", style={"padding": "20px"}),
                dcc.Store(id="annotation-store", data={"update": 0}),
                dcc.Store(id="points-store", data={"update": 0}),
                dcc.Store(id="selected-domain-store", data=None),
                dcc.Store(id="selected-image-store", data=None),
            ],
            style={"padding": "20px"},
        )

    def register_callbacks(self) -> None:
        self.dash.callback(
            Output("tab-content", "children"),
            Input("main-tabs", "value"),
        )(self.render_tab_content)

    def render_tab_content(self, tab: str) -> html.Div:
        """Render the content for the selected tab."""
        if tab == "tab-annotate":
            return self.annotation_tab.render_content()
        elif tab == "tab-points":
            return self.points_tab.render_content()
        elif tab == "tab-manage":
            return self.management_tab.render_content()
        return html.Div("Select a tab")


class AnnotateImageTab:
    """
    Tab 1: Annotate Images Callbacks
    """

    callback_data = {
        "update_image_dropdown": {
            "inputs": [Input("domain-dropdown", "value")],
            "output": [
                Output("image-dropdown", "options"),
                Output("image-dropdown", "value"),
            ],
            "prevent_initial_call": True,
        },
        "update_point_dropdown": {
            "inputs": [
                Input("points-store", "data"),
                Input("main-tabs", "value"),
            ],
            "output": Output("point-select-dropdown", "options"),
        },
        "show_selected_point_info": {
            "inputs": [Input("point-select-dropdown", "value")],
            "output": Output("selected-point-info", "children"),
        },
        "update_image": {
            "inputs": [
                Input("domain-dropdown", "value"),
                Input("image-dropdown", "value"),
                Input("annotation-store", "data"),
            ],
            "output": Output("image-graph", "figure"),
        },
        
        "handle_image_click": {
            "inputs": [Input("image-graph", "relayoutData")],
            "output": [
                Output("pixel-x-input", "value"),
                Output("pixel-y-input", "value"),
                Output("click-info", "children"),
            ],
        },
        "manage_annotations": {
            "inputs": [
                Input("add-button", "n_clicks"),
                Input({"type": "delete-annotation-btn", "index": ALL}, "n_clicks"),
                State("domain-dropdown", "value"),
                State("image-dropdown", "value"),
                State("pixel-x-input", "value"),
                State("pixel-y-input", "value"),
                State("point-select-dropdown", "value"),
                State("annotation-store", "data"),
            ],
            "output": [
                Output("annotation-store", "data"),
                Output("point-select-dropdown", "value"),
                Output("pixel-x-input", "value", allow_duplicate=True),
                Output("pixel-y-input", "value", allow_duplicate=True),
            ],
            "prevent_initial_call": True,
        },
        "update_annotations_list": {
            "inputs": [
                Input("domain-dropdown", "value"),
                Input("image-dropdown", "value"),
                Input("annotation-store", "data"),
            ],
            "output": Output("annotations-list", "children"),
        },
    }

    def __init__(self, app: App) -> None:
        self.app = app
        self._callbacks_registered = False

    def render_content(self) -> html.Div:
        """Create the Annotate Images tab content."""
        domains = self.app.manager.get_domains()
        initial_domain = domains[0] if domains else None
        initial_images = (
            self.app.manager.get_images(initial_domain) if initial_domain else []
        )

        content = html.Div(
            [
                html.Div(
                    [
                        html.Div(
                            [
                                html.Label("Domain:"),
                                dcc.Dropdown(
                                    id="domain-dropdown",
                                    options=[{"label": d, "value": d} for d in domains],
                                    value=initial_domain,
                                ),
                            ],
                            style={"width": "48%", "display": "inline-block"},
                        ),
                        html.Div(
                            [
                                html.Label("Image:"),
                                dcc.Dropdown(
                                    id="image-dropdown",
                                    options=[
                                        {"label": img, "value": img}
                                        for img in initial_images
                                    ],
                                    value=initial_images[0] if initial_images else None,
                                ),
                            ],
                            style={
                                "width": "48%",
                                "display": "inline-block",
                                "marginLeft": "4%",
                            },
                        ),
                    ],
                    style={"marginBottom": "20px"},
                ),
                html.Div(
                    [
                        html.Div(
                            [
                                html.H3("Image"),
                                dcc.Graph(
                                    id="image-graph",
                                    config={"displayModeBar": True},
                                    style={"height": "600px"},
                                ),
                            ],
                            style={
                                "width": "60%",
                                "display": "inline-block",
                                "verticalAlign": "top",
                            },
                        ),
                        html.Div(
                            [
                                html.H3("Add Annotation"),
                                html.Div(
                                    id="click-info", style={"marginBottom": "10px"}
                                ),
                                html.Div(
                                    [
                                        html.Label("Pixel X:"),
                                        dcc.Input(
                                            id="pixel-x-input",
                                            type="number",
                                            placeholder="Click image to set",
                                            style={
                                                "width": "100%",
                                                "marginBottom": "10px",
                                            },
                                            disabled=True,
                                        ),
                                        html.Label("Pixel Y:"),
                                        dcc.Input(
                                            id="pixel-y-input",
                                            type="number",
                                            placeholder="Click image to set",
                                            style={
                                                "width": "100%",
                                                "marginBottom": "10px",
                                            },
                                            disabled=True,
                                        ),
                                        html.Label("Geographic Point:"),
                                        dcc.Dropdown(
                                            id="point-select-dropdown",
                                            options=[],
                                            placeholder="Select a geographic point",
                                            style={"marginBottom": "10px"},
                                        ),
                                        html.Div(
                                            id="selected-point-info",
                                            style={
                                                "marginBottom": "10px",
                                                "color": "#666",
                                            },
                                        ),
                                        html.Button(
                                            "Add Annotation",
                                            id="add-button",
                                            n_clicks=0,
                                            style={"width": "100%"},
                                        ),
                                    ]
                                ),
                                html.H3("Annotations", style={"marginTop": "30px"}),
                                html.Div(id="annotations-list"),
                            ],
                            style={
                                "width": "35%",
                                "display": "inline-block",
                                "verticalAlign": "top",
                                "marginLeft": "5%",
                                "padding": "20px",
                            },
                        ),
                    ]
                ),
            ]
        )

        self.register_callbacks()
        return content

    def register_callbacks(self) -> None:
        if self._callbacks_registered:
            return

        for callback_fn_name, kwargs in self.callback_data.items():
            callback_fn = getattr(self, callback_fn_name)
            self.app.dash.callback(**kwargs)(callback_fn)

        self._callbacks_registered = True

    def update_image_dropdown(self, domain: str | None) -> tuple[list[dict], str | None]:
        """Update image dropdown when domain changes."""
        if domain is None:
            return [], None
        images = self.app.manager.get_images(domain)
        options = [{"label": img, "value": img} for img in images]
        value = images[0] if images else None
        return options, value

    def update_point_dropdown(self, _store: dict, tab: str) -> list[dict]:
        """Update geographic point dropdown options."""
        if tab != "tab-annotate":
            return no_update
        points = self.app.manager.get_geographic_points()
        return [
            {"label": f"{p['name']} ({key})", "value": key} for key, p in points.items()
        ]

    def show_selected_point_info(self, point_key: str | None) -> str:
        """Show info about the selected geographic point."""
        if not point_key:
            return ""
        points = self.app.manager.get_geographic_points()
        if point_key in points:
            p = points[point_key]
            return f"Lat: {p['latitude']}, Lon: {p['longitude']}"
        return ""

    def update_image(self, domain: str | None, image: str | None, _store: dict) -> go.Figure:
        """Update the image display with annotations."""
        fig = go.Figure()
        fig.update_layout(dragmode="drawrect")

        if domain and image:
            image_path = self.app.data_dir / domain / image
            if image_path.exists():
                img = Image.open(image_path)
                fig.add_layout_image(
                    dict(
                        source=img,
                        xref="x",
                        yref="y",
                        x=0,
                        y=0,
                        sizex=img.width,
                        sizey=img.height,
                        sizing="stretch",
                        layer="below",
                    )
                )

                annotations = self.app.manager.get_annotations(domain, image)
                points = self.app.manager.get_geographic_points()
                if annotations:
                    x_coords = [a["pixel_x"] for a in annotations]
                    y_coords = [a["pixel_y"] for a in annotations]
                    labels = []
                    for a in annotations:
                        point_key = a.get("point")
                        if point_key and point_key in points:
                            p = points[point_key]
                            label = (
                                f"{p['name']}<br>({p['latitude']}, {p['longitude']})"
                            )
                        else:
                            label = (
                                f"({a.get('latitude', '?')}, {a.get('longitude', '?')})"
                            )
                            if a.get("label"):
                                label += f"<br>{a['label']}"
                        labels.append(label)

                    fig.add_trace(
                        go.Scatter(
                            x=x_coords,
                            y=y_coords,
                            mode="markers+text",
                            marker=dict(size=12, color="red", symbol="x"),
                            text=labels,
                            textposition="top center",
                            hoverinfo="text",
                        )
                    )

                fig.update_xaxes(range=[0, img.width], showgrid=False, zeroline=False)
                fig.update_yaxes(
                    range=[img.height, 0],
                    showgrid=False,
                    zeroline=False,
                    scaleanchor="x",
                )
                fig.update_layout(
                    width=None,
                    height=600,
                    margin=dict(l=0, r=0, t=0, b=0),
                    xaxis_title="",
                    yaxis_title="",
                    hovermode="closest",
                )

        return fig

    def handle_image_click(
        self, 
        relayout_data: dict | None,
    ) -> tuple[int | None, int | None, str]:
        """Handle clicks on the image."""
        if relayout_data is None or "shapes" not in relayout_data:
            return None, None, "Click on the image to select a point"

        print(relayout_data)
        annotation_data = relayout_data["shapes"][-1]
        if annotation_data["type"] != "rect":
            return (
                None,
                None,
                f'Create rectangular annotation (not "{annotation_data["type"]}") to select a point',
            )

        x = int(annotation_data["x0"])
        y = int(annotation_data["y0"])
        return x, y, f"Selected point: ({x}, {y})"

    def manage_annotations(
        self,
        add_clicks: int,
        delete_clicks: list[int],
        domain: str | None,
        image: str | None,
        pixel_x: int | None,
        pixel_y: int | None,
        point_key: str | None,
        store: dict,
    ) -> tuple[dict, str | None, None, None]:
        """Add or delete annotations."""
        ctx = callback_context
        if not ctx.triggered or not domain or not image:
            return store, point_key, pixel_x, pixel_y

        trigger_id = ctx.triggered[0]["prop_id"]

        if "add-button" in trigger_id:
            if pixel_x is not None and pixel_y is not None and point_key:
                annotation = {
                    "pixel_x": pixel_x,
                    "pixel_y": pixel_y,
                    "point": point_key,
                }
                self.app.manager.add_annotation(domain, image, annotation)
                return {**store, "update": store.get("update", 0) + 1}, None, None, None

        elif "delete-annotation-btn" in trigger_id:
            trigger_dict = json.loads(trigger_id.split(".")[0])
            index = trigger_dict["index"]
            self.app.manager.remove_annotation(domain, image, index)
            return (
                {**store, "update": store.get("update", 0) + 1},
                point_key,
                pixel_x,
                pixel_y,
            )

        return store, point_key, pixel_x, pixel_y

    def update_annotations_list(
        self, domain: str | None, image: str | None, _store: dict
    ) -> html.Div:
        """Update the list of annotations."""
        if not domain or not image:
            return html.Div("Select a domain and image to view annotations.")

        annotations = self.app.manager.get_annotations(domain, image)
        points = self.app.manager.get_geographic_points()

        if not annotations:
            return html.Div(
                "No annotations yet. Click on the image and select a point to add one."
            )

        annotation_items = []
        for idx, ann in enumerate(annotations):
            point_key = ann.get("point")
            if point_key and point_key in points:
                p = points[point_key]
                label_text = f" - {p['name']}"
                coords_text = f"({p['latitude']}, {p['longitude']})"
            else:
                label_text = (
                    f" - {ann.get('label', 'Unknown')}" if ann.get("label") else ""
                )
                coords_text = (
                    f"({ann.get('latitude', '?')}, {ann.get('longitude', '?')})"
                )

            annotation_items.append(
                html.Div(
                    [
                        html.Div(
                            [
                                html.Strong(f"#{idx + 1}{label_text}"),
                                html.Br(),
                                f"Pixel: ({ann['pixel_x']}, {ann['pixel_y']})",
                                html.Br(),
                                f"Coords: {coords_text}",
                            ],
                            style={"display": "inline-block", "width": "70%"},
                        ),
                        html.Button(
                            "Delete",
                            id={"type": "delete-annotation-btn", "index": idx},
                            n_clicks=0,
                            style={
                                "display": "inline-block",
                                "float": "right",
                                "backgroundColor": "#ff4444",
                                "color": "white",
                                "border": "none",
                                "padding": "5px 10px",
                                "cursor": "pointer",
                            },
                        ),
                    ],
                    style={
                        "padding": "10px",
                        "marginBottom": "10px",
                        "border": "1px solid #ddd",
                        "borderRadius": "5px",
                    },
                )
            )

        return html.Div(annotation_items)


class GeographicPointsTab:
    """
    Tab 2: Geographic Points Callbacks
    """

    def __init__(self, app: App) -> None:
        self.app = app

    def render_content(self) -> html.Div:
        return html.Div(
            [
                html.Div(
                    [
                        html.Div(
                            [
                                dl.Map(
                                    center=[47.0, -122.0],
                                    zoom=7,
                                    children=[
                                        dl.TileLayer(),
                                        dl.LayerGroup(id="point-markers"),
                                    ],
                                    id="leaflet-map",
                                    style={"height": "600px", "width": "100%"},
                                ),
                            ],
                            style={
                                "width": "68%",
                                "display": "inline-block",
                                "verticalAlign": "top",
                            },
                        ),
                        html.Div(
                            [
                                html.H3("Add Point"),
                                html.Div(
                                    id="map-click-info",
                                    children="Click on the map to select a location",
                                    style={"marginBottom": "10px"},
                                ),
                                html.Label("Key (unique identifier):"),
                                dcc.Input(
                                    id="point-key-input",
                                    type="text",
                                    placeholder="e.g., seattle",
                                    style={"width": "100%", "marginBottom": "10px"},
                                ),
                                html.Label("Display Name:"),
                                dcc.Input(
                                    id="point-name-input",
                                    type="text",
                                    placeholder="e.g., Seattle, WA",
                                    style={"width": "100%", "marginBottom": "10px"},
                                ),
                                html.Label("Latitude:"),
                                dcc.Input(
                                    id="point-lat-input",
                                    type="number",
                                    placeholder="Click map to set",
                                    style={"width": "100%", "marginBottom": "10px"},
                                    disabled=True,
                                ),
                                html.Label("Longitude:"),
                                dcc.Input(
                                    id="point-lon-input",
                                    type="number",
                                    placeholder="Click map to set",
                                    style={"width": "100%", "marginBottom": "10px"},
                                    disabled=True,
                                ),
                                html.Button(
                                    "Add Point",
                                    id="add-point-btn",
                                    n_clicks=0,
                                    style={"width": "100%", "marginBottom": "20px"},
                                ),
                                html.H3("Existing Points"),
                                html.Div(id="points-list"),
                            ],
                            style={
                                "width": "28%",
                                "display": "inline-block",
                                "verticalAlign": "top",
                                "marginLeft": "4%",
                                "padding": "10px",
                            },
                        ),
                    ]
                ),
            ]
        )

    @callback(
        Output("point-lat-input", "value"),
        Output("point-lon-input", "value"),
        Output("map-click-info", "children"),
        Input("leaflet-map", "clickData"),
    )
    def handle_map_click(
        click_data: dict | None,
    ) -> tuple[float | None, float | None, str]:
        """Handle clicks on the leaflet map."""
        if click_data is None:
            return None, None, "Click on the map to select a location"

        lat = click_data["latlng"]["lat"]
        lon = click_data["latlng"]["lng"]
        return round(lat, 6), round(lon, 6), f"Selected: ({lat:.4f}, {lon:.4f})"

    @callback(
        Output("points-store", "data"),
        Output("point-key-input", "value"),
        Output("point-name-input", "value"),
        Output("point-lat-input", "value", allow_duplicate=True),
        Output("point-lon-input", "value", allow_duplicate=True),
        Input("add-point-btn", "n_clicks"),
        Input({"type": "delete-point-btn", "index": ALL}, "n_clicks"),
        State("point-key-input", "value"),
        State("point-name-input", "value"),
        State("point-lat-input", "value"),
        State("point-lon-input", "value"),
        State("points-store", "data"),
        prevent_initial_call=True,
    )
    def manage_geographic_points(
        add_clicks: int,
        delete_clicks: list[int],
        key: str | None,
        name: str | None,
        lat: float | None,
        lon: float | None,
        store: dict,
    ) -> tuple[dict, str, str, None, None]:
        """Add or delete geographic points."""
        ctx = callback_context
        if not ctx.triggered:
            return store, key or "", name or "", lat, lon

        trigger_id = ctx.triggered[0]["prop_id"]

        if "add-point-btn" in trigger_id:
            if key and name and lat is not None and lon is not None:
                manager.add_geographic_point(
                    key.strip().lower(), name.strip(), lat, lon
                )
                return (
                    {**store, "update": store.get("update", 0) + 1},
                    "",
                    "",
                    None,
                    None,
                )

        elif "delete-point-btn" in trigger_id:
            trigger_dict = json.loads(trigger_id.split(".")[0])
            point_key = trigger_dict["index"]
            manager.remove_geographic_point(point_key)
            return (
                {**store, "update": store.get("update", 0) + 1},
                key or "",
                name or "",
                lat,
                lon,
            )

        return store, key or "", name or "", lat, lon

    @callback(
        Output("point-markers", "children"),
        Input("points-store", "data"),
        Input("main-tabs", "value"),
    )
    def update_point_markers(_store: dict, tab: str) -> list:
        """Update markers on the leaflet map."""
        if tab != "tab-points":
            return no_update
        points = manager.get_geographic_points()
        markers = []
        for key, p in points.items():
            markers.append(
                dl.Marker(
                    position=[p["latitude"], p["longitude"]],
                    children=[
                        dl.Tooltip(f"{p['name']} ({key})"),
                        dl.Popup(
                            f"{p['name']}\nLat: {p['latitude']}, Lon: {p['longitude']}"
                        ),
                    ],
                )
            )
        return markers

    @callback(
        Output("points-list", "children"),
        Input("points-store", "data"),
        Input("main-tabs", "value"),
    )
    def update_points_list(_store: dict, tab: str) -> html.Div:
        """Update the list of geographic points."""
        if tab != "tab-points":
            return no_update
        points = manager.get_geographic_points()

        if not points:
            return html.Div(
                "No geographic points defined. Click on the map to add one."
            )

        point_items = []
        for key, p in points.items():
            point_items.append(
                html.Div(
                    [
                        html.Div(
                            [
                                html.Strong(p["name"]),
                                html.Br(),
                                f"Key: {key}",
                                html.Br(),
                                f"({p['latitude']}, {p['longitude']})",
                            ],
                            style={"display": "inline-block", "width": "70%"},
                        ),
                        html.Button(
                            "Delete",
                            id={"type": "delete-point-btn", "index": key},
                            n_clicks=0,
                            style={
                                "display": "inline-block",
                                "float": "right",
                                "backgroundColor": "#ff4444",
                                "color": "white",
                                "border": "none",
                                "padding": "5px 10px",
                                "cursor": "pointer",
                            },
                        ),
                    ],
                    style={
                        "padding": "10px",
                        "marginBottom": "10px",
                        "border": "1px solid #ddd",
                        "borderRadius": "5px",
                    },
                )
            )

        return html.Div(point_items)


class ManageAnnotationsTab:
    """
    Tab 3: Manage Annotations Callbacks
    """

    def __init__(self, app: App) -> None:
        self.app = app

    def render_content(self) -> html.Div:
        """Create the Manage Annotations tab content."""
        domains = self.app.manager.get_domains()
        return html.Div(
            [
                html.H3("Filter Annotations"),
                html.Div(
                    [
                        html.Div(
                            [
                                html.Label("Domain:"),
                                dcc.Dropdown(
                                    id="filter-domain",
                                    options=[{"label": "All", "value": ""}]
                                    + [{"label": d, "value": d} for d in domains],
                                    value="",
                                    placeholder="Filter by domain",
                                ),
                            ],
                            style={"width": "30%", "display": "inline-block"},
                        ),
                        html.Div(
                            [
                                html.Label("Image:"),
                                dcc.Dropdown(
                                    id="filter-image",
                                    options=[{"label": "All", "value": ""}],
                                    value="",
                                    placeholder="Filter by image",
                                ),
                            ],
                            style={
                                "width": "30%",
                                "display": "inline-block",
                                "marginLeft": "5%",
                            },
                        ),
                    ],
                    style={"marginBottom": "20px"},
                ),
                html.H3("All Annotations"),
                html.Div(id="all-annotations-list"),
            ]
        )

    @callback(
        Output("filter-image", "options"),
        Input("filter-domain", "value"),
    )
    def update_filter_image_options(domain: str | None) -> list[dict]:
        """Update image filter options based on selected domain."""
        options = [{"label": "All", "value": ""}]
        if domain:
            images = manager.get_images(domain)
            options.extend([{"label": img, "value": img} for img in images])
        return options

    @callback(
        Output("all-annotations-list", "children"),
        Input("filter-domain", "value"),
        Input("filter-image", "value"),
        Input("annotation-store", "data"),
        Input("main-tabs", "value"),
    )
    def update_all_annotations_list(
        filter_domain: str | None,
        filter_image: str | None,
        _store: dict,
        tab: str,
    ) -> html.Div:
        """Update the list of all annotations with filtering."""
        if tab != "tab-manage":
            return no_update

        all_annotations = manager.get_all_annotations()
        points = manager.get_geographic_points()

        if filter_domain:
            all_annotations = [
                a for a in all_annotations if a["domain"] == filter_domain
            ]
        if filter_image:
            all_annotations = [a for a in all_annotations if a["image"] == filter_image]

        if not all_annotations:
            return html.Div("No annotations found matching the current filters.")

        annotation_items = []
        for ann in all_annotations:
            point_key = ann.get("point")
            if point_key and point_key in points:
                p = points[point_key]
                point_text = f"{p['name']} ({point_key})"
                coords_text = f"({p['latitude']}, {p['longitude']})"
            else:
                point_text = ann.get("label", "Unknown")
                coords_text = (
                    f"({ann.get('latitude', '?')}, {ann.get('longitude', '?')})"
                )

            annotation_items.append(
                html.Div(
                    [
                        html.Div(
                            [
                                html.Strong(f"{ann['domain']} / {ann['image']}"),
                                html.Br(),
                                f"Point: {point_text}",
                                html.Br(),
                                f"Pixel: ({ann['pixel_x']}, {ann['pixel_y']})",
                                html.Br(),
                                f"Coords: {coords_text}",
                            ],
                            style={"display": "inline-block", "width": "80%"},
                        ),
                        html.Button(
                            "Delete",
                            id={
                                "type": "delete-all-annotation-btn",
                                "domain": ann["domain"],
                                "image": ann["image"],
                                "index": ann["index"],
                            },
                            n_clicks=0,
                            style={
                                "display": "inline-block",
                                "float": "right",
                                "backgroundColor": "#ff4444",
                                "color": "white",
                                "border": "none",
                                "padding": "5px 10px",
                                "cursor": "pointer",
                            },
                        ),
                    ],
                    style={
                        "padding": "10px",
                        "marginBottom": "10px",
                        "border": "1px solid #ddd",
                        "borderRadius": "5px",
                    },
                )
            )

        return html.Div(annotation_items)

    @callback(
        Output("annotation-store", "data", allow_duplicate=True),
        Input(
            {
                "type": "delete-all-annotation-btn",
                "domain": ALL,
                "image": ALL,
                "index": ALL,
            },
            "n_clicks",
        ),
        State("annotation-store", "data"),
        prevent_initial_call=True,
    )
    def delete_annotation_from_manage_tab(
        delete_clicks: list[int],
        store: dict,
    ) -> dict:
        """Delete annotation from the manage tab."""
        ctx = callback_context
        if not ctx.triggered:
            return store

        trigger_id = ctx.triggered[0]["prop_id"]
        if not any(delete_clicks):
            return store

        trigger_dict = json.loads(trigger_id.split(".")[0])
        domain = trigger_dict["domain"]
        image = trigger_dict["image"]
        index = trigger_dict["index"]

        manager.remove_annotation(domain, image, index)
        return {**store, "update": store.get("update", 0) + 1}


@click.command()
@click.option(
    "-d",
    "--data-dir",
    type=click.Path(path_type=Path, exists=True),
    default="data/georegistration",
    help="Directory containing domain subdirectories with images",
)
@click.option(
    "-o",
    "--output",
    "annotations_file",
    type=click.Path(path_type=Path),
    default="annotations.yaml",
    help="Output YAML file for annotations",
)
@click.option(
    "--port",
    type=int,
    default=8050,
    help="Port to run the Dash server on",
)
@click.option(
    "--no-browser",
    is_flag=True,
    help="Don't automatically open browser",
)
def cli(data_dir: Path, annotations_file: Path, port: int, no_browser: bool) -> None:
    """Launch the WRF image annotation tool."""
    app = App(data_dir, annotations_file)

    if not no_browser:
        Timer(1.5, lambda: webbrowser.open(f"http://127.0.0.1:{port}")).start()

    click.echo(f"Starting annotation tool on http://127.0.0.1:{port}")
    click.echo(f"Data directory: {data_dir}")
    click.echo(f"Annotations file: {annotations_file}")
    click.echo("Press Ctrl+C to stop")

    app.dash.run(debug=True, port=port, host="127.0.0.1")
