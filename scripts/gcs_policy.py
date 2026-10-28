"""Read, compare, publish and roll back a generation-guarded GCS policy."""

import difflib
from pathlib import Path
from typing import Annotated
from urllib.parse import urlsplit

import typer
import yaml
from admin_common import (
    generation_file,
    load_policy,
    protected_write,
    report,
    validate_capabilities,
)

from g_utils.config import Settings
from g_utils.policy.models import parse_policy
from g_utils.storage import GCSStore

app = typer.Typer(no_args_is_help=True, pretty_exceptions_show_locals=False)


def target():
    uri = urlsplit(Settings().policy_uri)
    if uri.scheme != "gs" or not uri.netloc or not uri.path.strip("/"):
        raise typer.BadParameter("Set POLICY_URI=gs://bucket/object")
    return GCSStore(uri.netloc), uri.path.lstrip("/")


@app.command()
def validate(file: Annotated[Path, typer.Option()]):
    load_policy(file)
    report({"valid": True})


@app.command()
def pull(file: Annotated[Path, typer.Option()]):
    store, key = target()
    obj = store.read(key)
    parse_policy(obj.data)
    protected_write(file, obj.data)
    protected_write(generation_file(file), str(obj.generation).encode())
    report({"generation": obj.generation, "file": str(file)})


@app.command()
def diff(file: Annotated[Path, typer.Option()]):
    load_policy(file)
    store, key = target()
    old = yaml.safe_dump(parse_policy(store.read(key).data).model_dump(), sort_keys=True)
    new = yaml.safe_dump(load_policy(file).model_dump(), sort_keys=True)
    typer.echo(
        "".join(difflib.unified_diff(old.splitlines(True), new.splitlines(True), "GCS", "local"))
    )


@app.command()
def publish(
    file: Annotated[Path, typer.Option()],
    create: bool = False,
    expected_generation: int | None = None,
):
    load_policy(file)
    if create:
        generation = 0
    elif expected_generation is not None:
        generation = expected_generation
    elif generation_file(file).exists():
        generation = int(generation_file(file).read_text())
    else:
        raise typer.BadParameter("Pull first, provide --expected-generation, or use --create")
    store, key = target()
    new = store.put(key, file.read_bytes(), generation)
    protected_write(generation_file(file), str(new).encode(), replace=True)
    report({"published_generation": new})


@app.command()
def history():
    store, key = target()
    report(
        [
            {"generation": int(blob.generation), "updated": str(blob.updated)}
            for blob in store.bucket.list_blobs(prefix=key, versions=True)
            if blob.name == key
        ]
    )


@app.command()
def rollback(
    generation: Annotated[int, typer.Option()],
    expected_generation: Annotated[int, typer.Option()],
    yes: bool = False,
):
    store, key = target()
    data = store.bucket.blob(key, generation=generation).download_as_bytes()
    policy = parse_policy(data)
    validate_capabilities(policy)
    current = store.read(key)
    typer.echo(
        "".join(
            difflib.unified_diff(
                current.data.decode().splitlines(True),
                data.decode().splitlines(True),
                "current",
                "rollback",
            )
        )
    )
    if not yes:
        typer.confirm("Publish this rollback as a new policy generation?", abort=True)
    report({"published_generation": store.put(key, data, expected_generation)})


if __name__ == "__main__":
    app()
