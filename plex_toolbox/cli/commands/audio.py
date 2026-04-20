from __future__ import annotations

from pathlib import Path

import typer
from pydub import AudioSegment
from pydub.silence import split_on_silence

audio_app = typer.Typer(help="Audio processing tools.", no_args_is_help=True)


@audio_app.command("split")
def split_cmd(
    input_file: Path = typer.Argument(..., exists=True, readable=True),
    output_dir: Path = typer.Option("tracks", help="Directory for split tracks"),
    min_silence_len: int = typer.Option(1000, help="Minimum silence length (ms)"),
    silence_thresh: int = typer.Option(-40, help="Silence threshold (dBFS)"),
    keep_silence: int = typer.Option(200, help="Silence to keep around chunks (ms)"),
    format: str = typer.Option(
        "m4a",
        "--format",
        "-f",
        help="Output format: m4a or mp3",
        case_sensitive=False,
    ),
):
    """
    Split an audio file into multiple tracks based on silence.
    Supports .m4a (AAC) and .mp3 output.
    """
    format = format.lower()
    if format not in ("m4a", "mp3"):
        typer.echo("Error: --format must be 'm4a' or 'mp3'")
        raise typer.Exit(code=1)

    typer.echo(f"Loading audio: {input_file}")
    audio = AudioSegment.from_file(input_file)

    output_dir.mkdir(parents=True, exist_ok=True)

    typer.echo("Detecting silence...")
    chunks = split_on_silence(
        audio,
        min_silence_len=min_silence_len,
        silence_thresh=silence_thresh,
        keep_silence=keep_silence,
    )

    typer.echo(f"Detected {len(chunks)} tracks")

    # Map format → ffmpeg export format
    export_format = "mp4" if format == "m4a" else "mp3"

    for i, chunk in enumerate(chunks, start=1):
        out_path = output_dir / f"track_{i:03d}.{format}"
        chunk.export(out_path, format=export_format)
        typer.echo(f"Saved {out_path}")

    typer.echo("Done.")
