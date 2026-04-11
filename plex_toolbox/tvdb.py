from __future__ import annotations  # Until Python 3.14

import re
import unicodedata
from dataclasses import dataclass, field
from pathlib import Path
from types import TracebackType
from typing import Any, ClassVar, Final

import httpx


@dataclass
class TVDBEpisode:
    """Dataclass representing a single episode of a series from TVDB."""

    id: int
    title: str
    absolute_ep_number: int
    seasonalized_ep_number: int
    season_number: int | None
    localized_title: str | None
    raw: dict[str, Any]

    def plex_episode_filename(self, show_title: str, air_year: int, extension: str) -> str:
        """Get the filename of this TVDBEpisode, optimized for Plex.

        Args:
            show_title (str): The title of the show.
            air_year (int): The year the show first aired.
            extension (str): The file extension (e.g., '.mkv', etc.).

        Returns:
            str: The filename of this TVDBEpisode, optimized for Plex.

        """
        title = self.localized_title or self.title
        sanitized_title = sanitize_for_filesystem(normalize_text_nfkc(title))
        return f"{show_title} ({air_year}) - s{self.season_number:02d}e{self.seasonalized_ep_number:02d} - {sanitized_title}{extension}"

    def plex_filepath(self, output_dirpath: Path, series_info: TVDBSeries, extension: str) -> Path:
        """Get the full, Plex-optimized filepath for this TVDBEpisode.

        Args:
            output_dirpath (Path): The output directory to write the file to.
            series_info (TVDBSeries): The TVDBSeries object representing this TVDBEpisode's parent series.
            extension (str): The file extension (e.g. '.mkv', etc.).

        Returns:
            Path: The full, Plex-optimized filepath for this TVDBEpisode.

        """
        show_folder = series_info.plex_show_folder_name
        season_folder = series_info.plex_season_folder_name(self.season_number)
        episode_filename = self.plex_episode_filename(series_info.localized_title or series_info.title, series_info.air_year, extension)
        plex_filepath = output_dirpath / show_folder / season_folder / episode_filename
        return plex_filepath


@dataclass
class TVDBSeries:
    """Dataclass representing a single series from TVDB."""

    id: int
    air_year: int
    title: str
    localized_title: str | None
    raw: dict[str, Any]
    episodes: list[TVDBEpisode] = field(default_factory=list)

    @property
    def plex_show_folder_name(self) -> str:
        """Get the name of this TVDBSeries show's folder for a Plex server.

        Returns:
            str: The name of this TVDBSeries show's folder for a Plex server.

        """
        title = self.localized_title or self.title
        sanitized_title = sanitize_for_filesystem(normalize_text_nfkc(title))
        return f"{sanitized_title} ({self.air_year}) {{tvdb-{self.id}}}"

    @property
    def seasons(self) -> dict[int, list[TVDBEpisode]]:
        """Get a mapping of season number to a list of the TVDBEpisodes within that season for this TVDBSeries.

        Returns:
            dict[int, list[TVDBEpisode]]: A mapping of season number to a list of the TVDBEpisodes within that season for this TVDBSeries.

        """
        season_numbers = sorted(list({e.season_number for e in self.episodes}))
        return {season_number: [e for e in self.episodes if e.season_number == season_number] for season_number in season_numbers}

    def plex_season_folder_name(self, season_number: int) -> str:
        """Get the name of a specific season Plex folder for this TVDBSeries.

        Args:
            season_number (int): The season number.

        Returns:
            str: The name of a specific season Plex folder for this TVDBSeries.

        """
        return f"Season {season_number:02d}"

    def get_episode(self, season_number: int, episode_number: int) -> TVDBEpisode | None:
        """Get the TVDBEpisode corresponding to the given season number and episode number (seasonalized) for this TVDBSeries, or None if not found.

        Args:
            season_number (int): The season number.
            episode_number (int): The (seasonalized) episode number.

        Returns:
            TVDBEpisode | None: The TVDBEpisode corresponding to the given season number and episode number (seasonalized) for this TVDBSeries, or None if not found.

        """
        return next((e for e in self.episodes if e.season_number == season_number and e.seasonalized_ep_number == episode_number), None)


@dataclass
class TVDBClient:
    """HTTPX client to access the TVDB API."""

    BASE_URL: ClassVar[Final[str]] = "https://api4.thetvdb.com/v4"

    api_key: str
    token: str | None = None
    preferred_lang: str = "eng"

    _client: httpx.Client | None = None

    def __enter__(self) -> TVDBClient:
        """Handler for when you utilize TVDBClient as a context manager, e.g.: with TVDBClient...


        Returns:
            TVDBClient: The client.

        """
        self._client = httpx.Client(timeout=30)
        return self

    def __exit__(self, exc_type: type[BaseException] | None, exc: BaseException | None, tb: TracebackType | None) -> None:
        """Handler for when TVDBClient is used as a context manager and it goes out of scope.

        Args:
            exc_type (type[BaseException] | None): The exception type, if any.
            exc (BaseException | None): The exception, if any.
            tb (TracebackType | None): The traceback type, if any.

        """
        if self._client:
            self._client.close()
        self._client = None

    def get_episode_by_id(self, episode_id: int) -> dict[str, Any]:
        """Get raw TVDB data about an episode by the episode's ID.

        Args:
            episode_id (int): The ID of the episode.

        Returns:
            dict[str, Any]: Raw TVDB data about the episode with the given ID.

        """
        res = self._get(f"{self.BASE_URL}/episodes/{episode_id}")
        res.raise_for_status()
        return res.json().get("data", {})

    def get_episode_translation(self, episode_id: int, language: str = "eng") -> dict[str, Any] | None:
        """Get the raw translation data of an episode with the given ID.

        Args:
            episode_id (int): The ID of the episode.
            language (str, optional): The language to get translation data for. Defaults to "eng".

        Returns:
            dict[str, Any] | None: The raw translation data of an episode with the given ID.

        """
        res = self._get(f"{self.BASE_URL}/episodes/{episode_id}/translations/{language}")
        if res.status_code == 404:
            return None
        res.raise_for_status()
        return res.json().get("data")

    def get_localized_episode_title(self, episode_id: int, language: str = "eng") -> str | None:
        """Get the localized episode title for the episode with the given ID.

        Args:
            episode_id (int): The ID of the episode.
            language (str, optional): The language to get the localized title for. Defaults to "eng".

        Returns:
            str | None: The localized title, or None if it could not be found.

        """
        # 1) translation endpoint (explicit English)
        trans = self.episode_translation(episode_id, language)
        if trans:
            name = trans.get("name")
            if isinstance(name, str) and name.strip():
                return name.strip()
        # 2) fallback to episode details
        ep = self.episode_by_id(episode_id)
        for key in ("name", "episodeName"):
            val = ep.get(key)
            if isinstance(val, str) and val.strip():
                return val.strip()
        return None

    def get_series_info(self, series_data: dict[str, Any], translation: str = "eng") -> TVDBSeries:
        """Get all standard and extended info about a series on TVDB.

        Args:
            series_data (dict[str, Any]): The raw series data from TVDBClient.search_series(...).
            translation (str, optional): The language translation data to get. Defaults to "eng".

        Raises:
            TypeError: If the series ID is an invalid type.
            TypeError: If the air year is an invalid type.

        Returns:
            TVDBSeries: The standard and extended info about a TVDB series.

        """
        series_id = series_data.get("tvdb_id")
        if series_id is None or not isinstance(series_id, str) or not series_id.is_digit():
            raise TypeError(f"TVDB series id was unexpected type '{type(series_id)}'. Expected digit str.")
        series_id = int(series_id)
        title = series_data.get("name", "")
        translations = series_data.get("translations", {})
        localized_title = sanitize_for_filesystem(normalize_text_nfkc(translations.get(translation)))
        res = self._get(f"{self.BASE_URL}/series/{series_id}/extended")
        res.raise_for_status()
        raw_data = res.json().get("data", {})
        air_year = raw_data.get("firstAired", "")
        if air_year is None or not isinstance(air_year, str) or not air_year[:4].isdigit():
            raise TypeError(f"TVDB series air year was unexpected type '{type(air_year)}'. Expected digit str.")
        air_year = int(air_year[:4])
        return TVDBSeries(id=series_id, air_year=air_year, title=title, localized_title=localized_title, raw=raw_data)

    def login(self) -> None:
        """Log in to the TVDB API."""
        res = self._post(f"{self.BASE_URL}/login", json={"apikey": self.api_key})
        res.raise_for_status()
        self.token = res.json().get("data", {}).get("token")

    def populate_series_episodes(self, series_info: TVDBSeries, season_type: str = "official") -> None:
        """Populate the given series_info object's .episodes field.

        Args:
            series_info (TVDBSeries): The TVDBSeries to populate episodes for.
            season_type (str, optional): The season type. Defaults to "official".

        """
        series_episodes: list[TVDBEpisode] = []
        page = 0
        while True:
            payload = self._get_series_episodes_by_season_type(series_info.id, season_type=season_type, page=page)
            items = payload.get("data", {})
            for ep in items.get("episodes", []):
                ep_id = ep.get("id")
                ep_title = ep.get("name")
                absolute_ep_number = ep.get("absoluteNumber")
                seasonalized_ep_number = ep.get("number")
                season_number = ep.get("seasonNumber")
                # localized_title = self.get_localized_episode_title(ep_id, localization_lang)
                raw = ep
                series_episodes.append(
                    TVDBEpisode(
                        id=ep_id,
                        title=ep_title,
                        absolute_ep_number=absolute_ep_number,
                        seasonalized_ep_number=seasonalized_ep_number,
                        season_number=season_number,
                        localized_title=None,
                        raw=raw,
                    )
                )
            links = payload.get("links") or {}
            next_page = links.get("next")
            # TVDB uses 0-based pages; if next is null/None, we're done.
            if next_page is None:
                break
            page = int(next_page)
        series_info.episodes = series_episodes

    def search_for_series(self, query: str, year: int | None = None) -> list[dict[str, Any]]:
        """Search for a specific series on TVDB.

        Args:
            query (str): The name of the series.
            year (int | None, optional): The year the series first aired, if applicable. Defaults to None.

        Returns:
            list[dict[str, Any]]: The list of hits from TVDB for the search query.

        """
        params = {"q": query, "type": "series"}
        if year:
            params["year"] = str(year)
        res = self._get(f"{self.BASE_URL}/search", params=params)
        res.raise_for_status()
        return res.json().get("data") or []

    @property
    def _headers(self) -> dict[str, str]:
        hdrs = {
            "Accept": "application/json",
            "Accept-Language": self.preferred_lang,
        }
        if self.token:
            hdrs["Authorization"] = f"Bearer {self.token}"
        return hdrs

    def _get(self, url: str, *, params: dict[str, str] | None = None) -> httpx.Response:
        if not self._client:
            raise RuntimeError("TVDBClient must be used as a context manager.")
        return self._client.get(url, params=params, headers=self._headers)

    def _get_series_episodes_by_season_type(self, series_id: int, season_type: str = "official", page: int = 0) -> dict[str, Any]:
        params = {"page": str(page)}
        res = self._get(f"{self.BASE_URL}/series/{series_id}/episodes/{season_type}", params=params)
        res.raise_for_status()
        return res.json()

    def _post(self, url: str, *, json: dict[str, Any]) -> httpx.Response:
        if not self._client:
            raise RuntimeError("TVDBClient must be used as a context manager.")
        return self._client.post(url, json=json, headers=self._headers)


def normalize_text_nfkc(title: str) -> str:
    return unicodedata.normalize("NFKC", title).strip()


def sanitize_for_filesystem(s: str) -> str:
    return re.sub(r'[<>:"/\\|?*\x00-\x1F]', "", s).strip()


def extract_localized_show_title(series_data: dict[str, Any], lang: str = "eng") -> str | None:
    translations = series_data.get("translations", {})
    localized = translations.get(lang)
    if localized and isinstance(localized, str) and localized.strip():
        return localized.strip()
    return None
