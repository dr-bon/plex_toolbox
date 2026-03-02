"""Script to automate naming TV show files for Plex, using TVDB as the source of truth for show/season/episode metadata."""

from __future__ import annotations  # Until Python 3.14
from enum import unique

import sys

import os
import re
import shutil
import unicodedata
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import typer
import httpx
from dotenv import load_dotenv
from rich import print
from rich.console import Console
from rich.table import Table

console = Console()

_TVDB_BASE = "https://api4.thetvdb.com/v4"

_VIDEO_EXTS = {".mkv", ".mp4", ".m4v", ".avi", ".mov"}

_PATTERNS_TV = [
    re.compile(r"(?i)\bS(?P<season>\d{1,2})E(?P<ep>\d{1,2})\b"),  # S01E02
    re.compile(r"(?i)\b(?P<season>\d{1,2})x(?P<ep>\d{2})\b"),  # 1x02
    re.compile(r"(?i)\bSeason[ ._-]?(?P<season>\d{1,2}).*?\bEp(?:isode)?[ ._-]?(?P<ep>\d{1,3})\b"),
]

_PATTERN_YEAR = re.compile(r"\b(19\d{2}|20\d{2})\b")


def _ensure_unique_path(p: Path) -> Path:
    if not p.exists():
        return p
    stem, suf = p.stem, p.suffix
    for i in range(2, 5000):
        candidate = p.with_name(f"{stem} ({i}){suf}")
        if not candidate.exists():
            return candidate
    raise RuntimeError(f"Too many collisions for {p}")

def infer_season_and_ep_numbers_from_filename(name: str) -> tuple[int, int] | None:
    for pat in _PATTERNS_TV:
        m = pat.search(name)
        if m:
            season = int(m.group("season"))
            ep = int(m.group("ep"))
            return season, ep
    return None

def list_video_files(folder: Path) -> list[Path]:
    files: list[Path] = []
    for p in sorted(folder.iterdir()):
        if p.is_file() and p.suffix.lower() in _VIDEO_EXTS:
            files.append(p)
    return files

def _normalize_title(title: str) -> str:
    return unicodedata.normalize("NFKC", title).strip()

def _prompt_int(prompt: str) -> int:
    while True:
        v = input(prompt)
        if not v.isdigit():
            print("Please enter a valid number.")
            continue
        return int(v)

def prompt_mode() -> str:
    print("\nModes:")
    print("  1) auto    = infer S/E and rename without asking per-file")
    print("  2) confirm = infer S/E and proposed name, ask Y/N per-file")
    print("  3) manual  = ask for season/episode for each file")
    while True:
        mode = _prompt_int("Choose mode (1/2/3): ")
        if mode not in (1, 2, 3):
            print("Please enter 1, 2, or 3.")
            continue
        break
    return {1: "auto", 2: "confirm", 3: "manual"}[int(mode)]

def _sanitize_tvdb_str(s: str) -> str:
    return re.sub(r'[<>:"/\\|?*\x00-\x1F]', "", s).strip()


def extract_english_show_title(obj: dict[str, Any]) -> str | None:
    translations = obj.get("translations") or {}
    eng = translations.get("eng")
    if eng and isinstance(eng, str) and eng.strip():
        return eng.strip()
    return None

def extract_year_from_show_query(text: str) -> int | None:
    m = _PATTERN_YEAR.search(text)
    return int(m.group(1)) if m else None

def select_show_from_hits(hits: list[dict[str, Any]]) -> dict[str, Any]:
    table = Table(title="TVDB Search Results (English-first)")
    table.add_column("#", justify="right")
    table.add_column("English Title")
    table.add_column("Default Title")
    table.add_column("Year", justify="right")
    table.add_column("TVDB ID", justify="right")
    for i, h in enumerate(hits, start=1):
        eng = extract_english_show_title(h) or ""
        default_name = str(h.get("name") or "")
        table.add_row(
            str(i),
            _normalize_title(eng) if eng else "-",
            _normalize_title(default_name) if default_name else "-",
            str(h.get("year") or ""),
            str(h.get("tvdb_id") or ""),
        )
    console.print(table)
    while True:
        idx = _prompt_int("Choose show number: ")
        if idx < 1 or idx > len(hits):
            print("Please enter a valid number.")
            continue
        break
    return hits[idx - 1]

@dataclass
class TVDBSeries:
    id: int
    air_year: int
    title: str
    localized_title: str | None
    raw: dict[str, Any]
    episodes: list[TVDBEpisode] = field(default_factory=list)

    @property
    def plex_show_folder(self) -> str:
        title = self.localized_title or self.title
        sanitized_title = _sanitize_tvdb_str(_normalize_title(title))
        return f"{sanitized_title} ({self.air_year}) {{tvdb-{self.id}}}"
    
    @property
    def seasons(self) -> dict[int, list[TVDBEpisode]]:
        season_nos = sorted(list({e.season_number for e in self.episodes}))
        return {season_no: [e for e in self.episodes if e.season_number == season_no] for season_no in season_nos}

    def plex_season_folder(self, season_no: int) -> str:
        return f"Season {season_no:02d}"
    
    def get_episode(self, season_no: int, episode_no: int) -> TVDBEpisode | None:
        return next((e for e in self.episodes if e.season_number == season_no and e.seasonalized_ep_number == episode_no))

@dataclass
class TVDBEpisode:
    id: int
    title: str
    absolute_ep_number: int
    seasonalized_ep_number: int
    season_number: int | None
    localized_title: str | None
    raw: dict[str, Any]

    def plex_episode_name(self, show_title: str, air_year: int, extension: str) -> str:
        title = self.localized_title or self.title
        sanitized_title = _sanitize_tvdb_str(_normalize_title(title))
        return f"{show_title} ({air_year}) - s{self.season_number:02d}e{self.seasonalized_ep_number:02d} - {sanitized_title}{extension}"

    def plex_filepath(self, output_filepath: Path, series_info: TVDBSeries, extension: str) -> Path:
        show_folder = series_info.plex_show_folder
        season_folder = series_info.plex_season_folder(self.season_number)
        episode_filename = self.plex_episode_name(series_info.localized_title or series_info.title, series_info.air_year, extension)
        plex_filepath = output_filepath / show_folder / season_folder / episode_filename
        unique_plex_filepath = _ensure_unique_path(plex_filepath)
        return unique_plex_filepath

@dataclass
class TvdbClient:
    api_key: str
    token: str | None = None

    # Keep a single http client to reuse connections
    _client: httpx.Client | None = None

    def __enter__(self) -> "TvdbClient":
        self._client = httpx.Client(timeout=30)
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        if self._client:
            self._client.close()
        self._client = None

    def _headers(self) -> dict[str, str]:
        h = {
            "Accept": "application/json",
            "Accept-Language": "eng",  # English-first at the transport level
        }
        if self.token:
            h["Authorization"] = f"Bearer {self.token}"
        return h

    def _get(self, url: str, *, params: dict[str, str] | None = None) -> httpx.Response:
        if not self._client:
            raise RuntimeError("TvdbClient must be used as a context manager.")
        return self._client.get(url, params=params, headers=self._headers())

    def _post(self, url: str, *, json: dict[str, Any]) -> httpx.Response:
        if not self._client:
            raise RuntimeError("TvdbClient must be used as a context manager.")
        return self._client.post(url, json=json, headers=self._headers())

    def login(self) -> None:
        r = self._post(f"{_TVDB_BASE}/login", json={"apikey": self.api_key})
        r.raise_for_status()
        self.token = r.json()["data"]["token"]

    def search_series(self, query: str, year: int | None = None) -> list[dict[str, Any]]:
        params: dict[str, str] = {"q": query, "type": "series"}
        if year:
            params["year"] = str(year)
        r = self._get(f"{_TVDB_BASE}/search", params=params)
        r.raise_for_status()
        return r.json().get("data") or []

    def get_series_info(self, series_data: dict[str, Any], translation: str = "eng") -> TVDBSeries:
        series_id = series_data.get("tvdb_id")
        if series_id is None or not isinstance(series_id, str) or not series_id.isdigit():
            raise ValueError()
        series_id = int(series_id)
        title = series_data.get("name", "")
        translations = series_data.get("translations", {})
        localized_title = _sanitize_tvdb_str(_normalize_title(translations.get(translation)))
        resp = self._get(f"{_TVDB_BASE}/series/{series_id}/extended")
        resp.raise_for_status()
        raw_data = resp.json()["data"]
        air_year = raw_data.get("firstAired", "")
        if air_year is None or not isinstance(air_year, str) or not air_year[:4].isdigit():
            raise ValueError()
        air_year = int(air_year[:4])
        return TVDBSeries(
            id=series_id,
            air_year=air_year,
            title=title,
            localized_title=localized_title,
            raw=raw_data
        )

    def series_episodes_by_season_type(
        self,
        series_id: int,
        season_type: str = "official",
        page: int = 0,
    ) -> dict[str, Any]:
        # Returns JSON with data + links.pagination (varies), so we return the full payload.
        params = {"page": str(page)}
        r = self._get(f"{_TVDB_BASE}/series/{series_id}/episodes/{season_type}", params=params)
        r.raise_for_status()
        return r.json()

    def populate_series_episodes(
        self,
        series_info: TVDBSeries,
        season_type: str = "official",
        localization_lang: str = "eng"
    ) -> None:
        series_episodes: list[TVDBEpisode] = []
        page = 0
        while True:
            payload = self.series_episodes_by_season_type(series_info.id, season_type=season_type, page=page)
            items = payload.get("data", {})
            for ep in items.get("episodes", []):
                ep_id = ep.get("id")
                ep_title = ep.get("name")
                absolute_ep_number = ep.get("absoluteNumber")
                seasonalized_ep_number = ep.get("number")
                season_number = ep.get("seasonNumber")
                # localized_title = self.get_localized_episode_title(ep_id, localization_lang)
                raw = ep
                series_episodes.append(TVDBEpisode(id=ep_id, title=ep_title, absolute_ep_number=absolute_ep_number, seasonalized_ep_number=seasonalized_ep_number, season_number=season_number, localized_title=None, raw=raw))
            links = payload.get("links") or {}
            next_page = links.get("next")
            # TVDB uses 0-based pages; if next is null/None, we're done.
            if next_page is None:
                break
            page = int(next_page)
        series_info.episodes = series_episodes

    def episode_by_id(self, episode_id: int) -> dict[str, Any]:
        r = self._get(f"{_TVDB_BASE}/episodes/{episode_id}")
        r.raise_for_status()
        return r.json().get("data") or {}

    def episode_translation(self, episode_id: int, language: str = "eng") -> dict[str, Any] | None:
        r = self._get(f"{_TVDB_BASE}/episodes/{episode_id}/translations/{language}")
        if r.status_code == 404:
            return None
        r.raise_for_status()
        return r.json().get("data") or None

    def get_localized_episode_title(self, episode_id: int, language: str = "eng") -> str | None:
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
