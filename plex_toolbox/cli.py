from __future__ import annotations

import typer
from rich import print
from pathlib import Path
import os
import shutil
from dotenv import load_dotenv
from plex_toolbox.scripts.tv_file_namer import TvdbClient, extract_year_from_show_query, select_show_from_hits, prompt_mode, list_video_files, infer_season_and_ep_numbers_from_filename

app = typer.Typer(
    name="plex-toolbox",
    help="A collection of tools for managing Plex media libraries.",
    no_args_is_help=True,
)

# Subcommand groups (optional but clean)
youtube_app = typer.Typer(help="YouTube download tools.")
tv_app = typer.Typer(help="TV file tools.")
manifest_app = typer.Typer(help="Manifest file management tools.")

app.add_typer(youtube_app, name="yt")
app.add_typer(tv_app, name="tv")
app.add_typer(manifest_app, name="man")



# ---------------------------------------------------
# nametv command
# ---------------------------------------------------

@tv_app.command("name-files", help="Use the TVDB API to automatically batch-rename TV episode files for Plex.")
def name_tv_files(
    input_dir: Path = typer.Argument(..., help="Input directory containing TV show video file(s)."),
    output_dir: Path = typer.Option("./TV", help="Output directory to place renamed file(s) in."),
    season_type: str = typer.Option("official", help="TVDB season type."),
    localization_lang: str = typer.Option("eng", help="The language to localize textual data to."),
    dry_run: bool = typer.Option(
        True,
        "--dry-run/--no-dry-run",
        help="Preview changes without moving files",
    ),
) -> None:
    # First, we load the TVDB API key from the environment
    load_dotenv()
    tvdb_api_key = os.getenv("TVDB_API_KEY")
    if not tvdb_api_key:
        raise ValueError("TVDB_API_KEY not found in environment variables.")
    with TvdbClient(api_key=tvdb_api_key) as client:
        client.login()
        show_query = typer.prompt("TV show name (you can include the year to improve search relevance)", type=str)
        year_hint = extract_year_from_show_query(show_query)
        tvdb_hits = client.search_series(show_query, year=year_hint)
        if not tvdb_hits:
            print(f"[red]No TVDB results for:[/] {show_query}")
            raise typer.Exit(code=1)
        selected_series_data = select_show_from_hits(tvdb_hits)
        series_info = client.get_series_info(selected_series_data)
        # Then prompt the user for the mode they want to use for renaming (auto, confirm, manual)
        mode = prompt_mode()
        files = list_video_files(input_dir)
        if not files:
            print(f"[yellow]No video files found in[/] {input_dir}")
            typer.Exit(code=1)
        print(f"\nSelected: [bold]{series_info.plex_show_folder}[/bold] (TVDB {series_info.id})")
        print(f"Found {len(files)} files in {input_dir}")
        print(f"Destination root: {output_dir}")
        print(f"Season type: {season_type}")
        print(f"Dry run: {dry_run}\n")
        # TODO: This is slow
        client.populate_series_episodes(series_info, season_type=season_type, localization_lang=localization_lang)
        # For each file, rename according to the selected mode
        for f in files:
            season_ep: tuple[int, int] | None = None
            # If auto/confirm mode, try to infer season/episode from the filename; if we can't, skip (auto) or ask (confirm)
            if mode in ("auto", "confirm"):
                season_ep = infer_season_and_ep_numbers_from_filename(f.name)
                if not season_ep:
                    print(f"[yellow]Could not infer S/E from filename:[/] {f.name}")
                    if mode == "auto":
                        continue
            # If the mode is manual, or if we're in confirm mode and couldn't infer S/E, prompt the user for season/episode numbers
            if mode == "manual" or (mode == "confirm" and not season_ep):
                sea_no = typer.prompt(f"{f.name} - season #", type=int)
                ep_no = typer.prompt(f"{f.name} - episode #", type=int)
                season_ep = (sea_no, ep_no)
            assert season_ep is not None
            # Get the episode ID from our index
            sea_no, ep_no = season_ep
            tvdb_episode = series_info.get_episode(sea_no, ep_no)
            if not tvdb_episode:
                print(f"[yellow]No episode found for[/] {series_info.plex_show_folder} s{sea_no:02d}e{ep_no:02d} (season_type={season_type})")
                # In confirm/manual modes, you might want to keep going; in auto mode, we just skip.
                continue
            # Get the episode title (English-first) from the TVDB API, and construct the new filename and destination path
            if tvdb_episode.localized_title is None:
                tvdb_episode.localized_title = client.get_localized_episode_title(tvdb_episode.id, language=localization_lang)
            dest = tvdb_episode.plex_filepath(output_dir, series_info, f.suffix.lower())
            # Confirm if in confirm mode
            if mode == "confirm":
                print(f"[cyan]Proposed[/] {f.name} -> {dest}")
                ok = typer.confirm("Rename/move this file?", default=True)
                if not ok:
                    continue
            # Show dry run, or actually move the file if not a dry run
            if dry_run:
                print(f"[cyan]DRY RUN[/] {f} -> {dest}")
            else:
                dest.parent.mkdir(parents=True, exist_ok=True)
                shutil.move(str(f), str(dest))
                print(f"[green]MOVED[/] {f} -> {dest}")
        # Done
        print("\n[bold green]Done.[/bold green]")

if __name__ == "__main__":
    app()