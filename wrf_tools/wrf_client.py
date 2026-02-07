from pathlib import Path
from typing import ClassVar
from attrs import define, field
import httpx
import click
from cattrs.preconf.pyyaml import make_converter


@define
class CodeConfig:
    name: str
    code: str


@define
class ForecastScheduleConfig:
    name: str
    hours: list[int]


@define
class LayerConfig:
    domain: str
    variable: str
    forecast_schedule: str
    maptype: str


@define
class WrfConfig:
    domain_codes: list[CodeConfig]
    maptype_codes: list[CodeConfig]
    variable_codes: list[CodeConfig]
    forecast_schedules: list[ForecastScheduleConfig]
    layers: list[LayerConfig]

    _domains: dict[str, str] = field(init=False, factory=dict)
    _maptypes: dict[str, str] = field(init=False, factory=dict)
    _variables: dict[str, str] = field(init=False, factory=dict)
    _schedules: dict[str, list[int]] = field(init=False, factory=dict)

    base_url: ClassVar[str] = "https://a.atmos.washington.edu/wrfrt/data/timeindep"

    def get_domain_code(self, domain_name: str) -> str:
        if not self._domains:
            self._domains = {conf.name: conf.code for conf in self.domain_codes}

        code = self._domains.get(domain_name)
        if code is None:
            raise ValueError(f"{domain_name} was not found")
        return code

    def get_maptype_code(self, maptype_name: str) -> str:
        if not self._maptypes:
            self._maptypes = {conf.name: conf.code for conf in self.maptype_codes}

        code = self._maptypes.get(maptype_name)
        if code is None:
            raise ValueError(f"{maptype_name} was not found")
        return code

    def get_variable_code(self, variable_name: str) -> str:
        if not self._variables:
            self._variables = {conf.name: conf.code for conf in self.variable_codes}

        code = self._variables.get(variable_name)
        if code is None:
            raise ValueError(f"{variable_name} was not found")
        return code

    def get_forecast_hours(self, schedule_name: str) -> list[int]:
        if not self._schedules:
            self._schedules = {
                conf.name: conf.hours for conf in self.forecast_schedules
            }

        code = self._schedules.get(schedule_name)
        if code is None:
            raise ValueError(f"{schedule_name} was not found")
        return code

    def build_url(
        self, domain: str, variable: str, hour: int, maptype: str | None = None
    ) -> str:
        domain_code = self.get_domain_code(domain)
        maptype_code = self.get_maptype_code(maptype) if maptype is not None else ""
        variable_code = self.get_variable_code(variable)
        return f"{self.base_url}/images_{domain_code}/{maptype_code}{variable_code}.{hour:02d}.0000.gif"

    @classmethod
    def load(cls, wrf_config: Path) -> "WrfConfig":
        converter = make_converter()
        return converter.loads(wrf_config.read_text(), cls)


@define
class WrfClient:
    _client: httpx.Client = field(factory=lambda: httpx.Client(timeout=60.0))

    def download_layer(
        self, layer: LayerConfig, wrf_config: WrfConfig, output_path: Path
    ) -> None:
        for fx_hour in wrf_config.get_forecast_hours(layer.forecast_schedule):
            gif_output_path = (
                output_path / layer.domain / layer.variable / f"hour{fx_hour:02d}.gif"
            )
            if gif_output_path.exists():
                continue

            gif_output_path.parent.mkdir(exist_ok=True, parents=True)
            image_url = wrf_config.build_url(
                layer.domain, layer.variable, fx_hour, layer.maptype
            )
            r = self._client.get(image_url)
            _ = r.raise_for_status()
            _ = gif_output_path.write_bytes(r.content)


@click.command()
@click.option("-c", "--config", required=True, type=click.Path(path_type=Path))
@click.option(
    "-o", "--output", "output_path", required=True, type=click.Path(path_type=Path)
)
def main(config: Path, output_path: Path) -> None:
    wrf_config = WrfConfig.load(config)
    wrf_client = WrfClient()
    for i, layer in enumerate(wrf_config.layers):
        click.echo(f"Downloading layer {i + 1} of {len(wrf_config.layers)}")
        wrf_client.download_layer(layer, wrf_config, output_path)


if __name__ == "__main__":
    main()
