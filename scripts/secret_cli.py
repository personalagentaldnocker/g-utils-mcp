"""Secret payload input is hidden; metadata output never includes values."""

import getpass
from typing import Annotated

import typer
from admin_common import cloud, report

app = typer.Typer(no_args_is_help=True, pretty_exceptions_show_locals=False)


@app.command()
def write(ref: Annotated[str, typer.Option()]):
    _, _, store = cloud()
    value = getpass.getpass("Secret value (hidden): ")
    if not value:
        raise typer.BadParameter("Empty secret rejected")
    store.add(ref, value.encode())
    report({"version_added": True})


@app.command()
def versions(ref: Annotated[str, typer.Option()]):
    _, _, store = cloud()
    parent = store.validate(ref)
    report(
        [
            {"name": v.name, "state": v.state.name}
            for v in store.client.list_secret_versions(parent=parent)
        ]
    )


if __name__ == "__main__":
    app()
