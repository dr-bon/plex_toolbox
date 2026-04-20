from __future__ import annotations

from pathlib import Path

import typer
from rich.console import Console
from yt_dlp import YoutubeDL

youtube_app = typer.Typer(help="Plex YouTube tools.", no_args_is_help=True)

console = Console()


@youtube_app.command("dl", help="Download YouTube video/audio with optional subtitles.")
def download_cmd(
    url: str = typer.Argument(..., help="YouTube URL"),
    out_dir: Path = typer.Option("./downloads", help="Output directory"),
    audio_only: bool = typer.Option(False, help="Download audio only (m4a)"),
    subtitles: str = typer.Option(None, help='Subtitle languages, e.g. "en,es"'),
    auto_subs: bool = typer.Option(False, help="Include auto-generated subtitles"),
    srt: bool = typer.Option(False, help="Convert subtitles to .srt"),
):
    """
    Download from YouTube with support for:
    - audio-only
    - video
    - subtitles (manual + auto)
    """
    out_dir = out_dir.expanduser().resolve()
    out_dir.mkdir(parents=True, exist_ok=True)

    outtmpl = str(out_dir / "%(title)s [%(id)s].%(ext)s")

    ydl_opts = {
        "outtmpl": outtmpl,
        "noplaylist": True,
        "quiet": False,
        "no_warnings": False,
    }

    # Audio-only mode
    if audio_only:
        ydl_opts.update(
            {
                "format": "bestaudio",
                "extract_audio": True,
                "audio_format": "m4a",
                "audio_quality": 0,
                "postprocessors": [
                    {
                        "key": "FFmpegExtractAudio",
                        "preferredcodec": "m4a",
                        "preferredquality": "0",
                    }
                ],
            }
        )
    else:
        # Prefer MP4 video if available
        ydl_opts["format"] = "bv*+ba/best"

    # Subtitles
    if subtitles:
        langs = [x.strip() for x in subtitles.split(",") if x.strip()]
        ydl_opts["writesubtitles"] = True
        ydl_opts["subtitleslangs"] = langs
        ydl_opts["subtitlesformat"] = "best"

    if auto_subs:
        ydl_opts["writeautomaticsub"] = True

    if srt:
        ydl_opts["postprocessors"] = [{"key": "FFmpegSubtitlesConvertor", "format": "srt"}]

    try:
        with YoutubeDL(ydl_opts) as ydl:
            ydl.download([url])
    except Exception as e:
        typer.echo(f"Download failed: {e}")
        raise typer.Exit(code=1)

    typer.echo("Download complete.")
