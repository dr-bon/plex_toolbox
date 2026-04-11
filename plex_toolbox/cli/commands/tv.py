from __future__ import annotations  # Until Python 3.14

import os
import shutil
from pathlib import Path
from typing import Any, Literal

import typer
from dotenv import load_dotenv
from rich.console import Console
from rich.prompt import Prompt
from rich.table import Table

from plex_toolbox.tvdb import TVDBClient, extract_localized_show_title, normalize_text_nfkc
from plex_toolbox.utilities.constants import VIDEO_EXTENSIONS
from plex_toolbox.utilities.regex import REGEX_PATTERN_YEAR, REGEX_PATTERNS_TV

tv_app = typer.Typer(help="Plex TV tools.", no_args_is_help=True)

console = Console()


def _prompt_for_series_from_hits(series_hits: list[dict[str, Any]]) -> dict[str, Any]:
    table = Table(title="TVDB Search Results")
    table.add_column("#")
    table.add_column("Localized Title")
    table.add_column("Original Title")
    table.add_column("Year")
    table.add_column("TVDB ID")
    for i, series_data in enumerate(series_hits, start=1):
        localized_title = extract_localized_show_title(series_data) or ""
        original_title = str(series_data.get("name", ""))
        table.add_row(
            str(i),
            normalize_text_nfkc(localized_title) if localized_title else "-",
            normalize_text_nfkc(original_title) if original_title else "-",
            str(series_data.get("year") or ""),
            str(series_data.get("tvdb_id") or ""),
        )
    console.print(table)
    num_hits = len(series_hits)
    while True:
        selected_idx = Prompt.ask("Choose a show number:", choices=[i for i in range(num_hits, start=1)], show_choices=False)
        if not selected_idx or not selected_idx.isdigit() or int(selected_idx) < 1 or int(selected_idx) > num_hits:
            console.print("Please enter a valid number from the table.")
            continue
        return series_hits[int(selected_idx) - 1]


def _prompt_for_mode() -> Literal["auto", "confirm", "manual"]:
    table = Table("Operation Modes")
    table.add_column("#")
    table.add_column("Mode")
    table.add_column("Description")
    table.add_row("1", "Auto", "Infer season/episode and rename without asking per-file")
    table.add_row("2", "Confirm", "Infer season/episode and proposed name, ask Y/N per-file")
    table.add_row("3", "Manual", "Ask for season/episode for each file")
    while True:
        mode = Prompt.ask("Choose a mode:", choices=["1", "2", "3"])
        if not mode or not mode.isdigit() or int(mode) not in (1, 2, 3):
            console.print("Please enter a valid choice.")
            continue
        return {1: "auto", 2: "confirm", 3: "manual"}[int(mode)]


def _list_video_files_to_rename(folder: Path) -> list[Path]:
    files: list[Path] = []
    for p in sorted(folder.iterdir()):
        if p.is_file() and p.suffix.lower() in VIDEO_EXTENSIONS:
            files.append(p)
    return files


def _infer_season_and_ep_numbers_from_filename(name: str) -> tuple[int, int] | None:
    for pat in REGEX_PATTERNS_TV:
        m = pat.search(name)
        if m:
            season = int(m.group("season"))
            ep = int(m.group("ep"))
            return season, ep
    return None


def _prompt_season_number(episode_filename: str) -> int:
    while True:
        sno = Prompt.ask(f"{episode_filename} - Season #:")
        if not sno or not sno.isdigit():
            console.print("Please enter a valid number.")
            continue
        return int(sno)


def _prompt_episode_number(episode_filename: str) -> int:
    while True:
        eno = Prompt.ask(f"{episode_filename} - Episode #:")
        if not eno or not eno.isdigit():
            console.print("Please enter a valid number.")
            continue
        return int(eno)


@tv_app.command("name-files", help="Use the TVDB API to automatically batch-rename TV episode files for Plex.")
def name_files_cmd(
    ctx: typer.Context,
    input_dir: Path = typer.Argument(..., exists=True, dir_okay=True, file_okay=False, help="Input directory containing TV show video file(s) to rename."),
    output_dir: Path = typer.Option(default="./TV", exists=False, dir_okay=True, file_okay=False, help="Output directory to place renamed file(s) in."),
    season_type: str = typer.Option("official", help="The TVDB season type (e.g., the organizational scheme for episodes)."),
    localization_lang: str = typer.Option("eng", help="The language to localize textual data to."),
    dry_run: bool = typer.Option(False, "--dry-run/--no-dry-run", help="Preview changes without actually moving/renaming any files."),
) -> None:
    load_dotenv()
    tvdb_api_key = os.getenv("TVDB_API_KEY")
    if not tvdb_api_key:
        console.print("[bold red]Unable to locate TVDB_API_KEY in environment variables.[/bold red]")
        raise typer.Exit(code=1)
    with TVDBClient(api_key=tvdb_api_key) as client:
        with console.status("Logging into TVDB API"):
            client.login()
        show_query = Prompt.ask("Enter a TV show name (include the year it first aired to refine search)")
        pm = REGEX_PATTERN_YEAR.search(show_query)
        air_year = int(pm.group(1)) if pm else None
        if air_year is not None:
            console.print(f"[green]Detected air year: {air_year}[/green]")
        with console.status("Searching for TV series on TVDB"):
            tvdb_hits = client.search_for_series(show_query, year=air_year)
        if not tvdb_hits:
            console.print(f"[red]No TVDB results for:[/red] {show_query}")
            raise typer.Exit(code=1)
        selected_series_data = _prompt_for_series_from_hits(tvdb_hits)
        while console.status("Fetching series info"):
            series_info = client.get_series_info(selected_series_data)
        mode = _prompt_for_mode()
        files = _list_video_files_to_rename(input_dir)
        if not files:
            console.print(f"[red]No video files found in:[/red] {input_dir}")
            raise typer.Exit(code=1)
        console.print(f"Selected [bold]{series_info.plex_show_folder_name}[/bold] (TVDB {series_info.id})")
        console.print(f"Found {len(files)} video files in: {input_dir}")
        console.print(f"Destination directory: {output_dir}")
        console.print(f"Season type: {season_type}")
        console.print(f"Dry run: {dry_run}")
        console.print("")
        with console.status("Populating series episode data from TVDB"):
            client.populate_series_episodes(series_info, season_type=season_type, localization_lang=localization_lang)
        for f in files:
            season_ep: tuple[int, int] | None = None
            if mode in ("auto", "confirm"):
                season_ep = _infer_season_and_ep_numbers_from_filename(f.name)
                if not season_ep:
                    console.print(f"[bold yellow]Unable to infer season/episode from filename:[/bold yellow] {f.name}")
                    if mode == "auto":
                        continue
            if mode == "manual" or (mode == "confirm" and not season_ep):
                s_no = _prompt_season_number(f.name)
                e_no = _prompt_episode_number(f.name)
                season_ep = (s_no, e_no)
            if season_ep is None:
                console.print(f"[bold red]Unable to determine season/episode number for:[/bold red] {f.name}")
                raise typer.Exit(code=1)
            season_number, episode_number = season_ep
            with console.status("Fetching TVDB episode"):
                tvdb_episode = series_info.get_episode(season_number, episode_number)
            if not tvdb_episode:
                console.print(
                    f"[yellow]Episode could not be found for[/yellow] {series_info.plex_show_folder_name} s{season_number:02d}e{episode_number:02d} (season_type={season_type})"
                )
                continue
            if tvdb_episode.localized_title is None:
                with console.status("Fetching localized episode title"):
                    tvdb_episode.localized_title = client.get_localized_episode_title(tvdb_episode.id, localization_lang)
            dest = tvdb_episode.plex_filepath(output_dir, series_info, f.suffix.lower())
            if mode == "confirm":
                console.print(f"[cyan]Proposed[/cyan] [bold]{f.name} -> {dest}[/bold]")
                ok = typer.confirm("Rename/move this file?", default=False)
                if not ok:
                    continue
            if dry_run:
                console.print(f"[cyan]DRY RUN[/cyan] {f} -> {dest}")
            else:
                dest.parent.mkdir(parents=True, exist_ok=True)
                shutil.move(str(f), str(dest))
                console.print(f"[green]MOVED[/green] {f} -> {dest}")
        console.print("\n[bold green]Done.[/bold green]")
