"""
Home Assistant component to feed the Upcoming Media Lovelace card with
Sonarr upcoming releases.

https://github.com/raman325/sensor.radarr_upcoming_media

https://github.com/custom-cards/upcoming-media-card

"""
from datetime import date, datetime, timedelta
import logging

from aiopyarr.exceptions import ArrException
from aiopyarr.models.host_configuration import PyArrHostConfiguration
from aiopyarr.sonarr_client import SonarrCalendar, SonarrClient, SonarrSeries
from homeassistant.components.sensor import PLATFORM_SCHEMA, SensorEntity
from homeassistant.const import CONF_API_KEY, CONF_HOST, CONF_PORT, CONF_SSL
from homeassistant.helpers.aiohttp_client import async_get_clientsession
import homeassistant.helpers.config_validation as cv
import voluptuous as vol

__version__ = "0.1.10"

_LOGGER = logging.getLogger(__name__)

CONF_DAYS = "days"
CONF_URLBASE = "urlbase"
CONF_MAX = "max"

PLATFORM_SCHEMA = PLATFORM_SCHEMA.extend(
    {
        vol.Required(CONF_API_KEY): cv.string,
        vol.Optional(CONF_DAYS, default=7): vol.Coerce(int),
        vol.Optional(CONF_HOST, default="localhost"): cv.string,
        vol.Optional(CONF_PORT, default=8989): cv.port,
        vol.Optional(CONF_SSL, default=False): cv.boolean,
        vol.Optional(CONF_URLBASE): cv.string,
        vol.Optional(CONF_MAX, default=5): vol.Coerce(int),
    }
)

FIRST_CARD = {
    "title_default": "$title",
    "line1_default": "$number - $episode",
    "line2_default": "$release",
    "line3_default": "$rating - $runtime",
    "line4_default": "$studio",
    "icon": "mdi:arrow-down-bold",
}


def setup_platform(hass, config, add_devices, discovery_info=None):
    add_devices([SonarrUpcomingMediaSensor(hass, config)], True)


class SonarrUpcomingMediaSensor(SensorEntity):
    def __init__(self, hass, conf):
        url_base = conf.get(CONF_URLBASE)
        if url_base:
            url_base = "{}/".format(url_base.strip("/"))
        self._host_config = PyArrHostConfiguration(
            api_token=conf[CONF_API_KEY],
            hostname=conf[CONF_HOST],
            port=conf[CONF_PORT],
            ssl=conf[CONF_SSL],
            base_api_path=url_base,
        )
        self.client = SonarrClient(
            self._host_config, session=async_get_clientsession(hass)
        )
        self.days = conf.get(CONF_DAYS)
        self.max_items = conf.get(CONF_MAX)

        self._attr_available = True
        self._attr_name = "Sonarr Upcoming Media"

    def _get_rating(self, series: SonarrSeries):
        """Return rating."""
        try:
            return "\N{BLACK STAR} " + str(series.ratings.value)
        except AttributeError:
            return ""

    async def async_update(self):
        start = datetime.combine(date.today(), datetime.min.time())
        end = start + timedelta(days=self.days)
        try:
            episodes = await self.client.async_get_calendar(start, end)
        except ArrException as err:
            if self._attr_available:
                _LOGGER.warning(err)
            self._attr_available = False
            return

        if isinstance(episodes, SonarrCalendar):
            episodes = [episodes]

        episodes = [episode for episode in episodes if hasattr(episode, "series")][
            : self.max_items
        ]
        self._attr_available = True
        self._attr_native_value = len(episodes)
        self._attr_extra_state_attributes = {"data": [FIRST_CARD]}

        for episode in episodes:
            series_list = await self.client.async_get_series(episode.seriesId)
            if isinstance(series_list, list):
                series = next(series for series in series_list)
            else:
                series = series_list

            episode_data = {
                "airdate": datetime.date(episode.airDateUtc).isoformat(),
                "release": "$day, $date $time",
                "flag": episode.attributes.get("hasFile", False),
                "title": series.attributes.get("title", ""),
                "runtime": series.attributes.get("runtime", ""),
                "episode": episode.attributes.get("title", ""),
                "number": "",
                "rating": self._get_rating(series),
                "studio": series.attributes.get("network", ""),
                "genres": ", ".join(series.attributes.get("genres", [])),
                "poster": "",
                "fanart": "",
            }
            if hasattr(episode, "seasonNumber") and hasattr(episode, "episodeNumber"):
                episode_data["number"] = "S{:02d}E{:02d}".format(
                    episode.seasonNumber, episode.episodeNumber
                )

            if hasattr(series, "images"):
                episode_data["poster"] = next(
                    (
                        image.remoteUrl
                        for image in series.images
                        if image.coverType == "poster"
                    ),
                    "",
                )
                episode_data["fanart"] = next(
                    (
                        image.remoteUrl
                        for image in series.images
                        if image.coverType == "fanart"
                    ),
                    "",
                )
            self._attr_extra_state_attributes["data"].append(episode_data)
