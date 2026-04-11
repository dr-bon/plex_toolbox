from __future__ import annotations  # Until Python 3.14

import typer

from plex_toolbox.cli.commands.tv import tv_app

app = typer.Typer(name="ptb", help="A collection of tools for managing Plex media libraries.", no_args_is_help=True)

# TODO: manifest app
app.add_typer(tv_app, name="tv")
# TODO: youtube app

if __name__ == "__main__":
    app()
