"""Command line entry point: `data-factory` (or `python -m data_factory`).

Examples:
    data-factory run                          # both datasets, every stage: empty database -> full
    data-factory run --dataset olist          # only the Olist dataset
    data-factory run --stages fetch           # only one stage
    data-factory run --stages load            # only load the published outputs into PostgreSQL
    data-factory run --since-last-run         # only records newer than the previous run
    data-factory check-config                 # validate the configuration and stop
    data-factory check-db                     # connect to the database and print its version
"""
from __future__ import annotations

import argparse
import logging
from pathlib import Path

from data_factory import olist_pipeline, pipeline
from data_factory.config import load_config
from data_factory.db import database, safe_url, server_version
from data_factory.exceptions import ExitCode, FactoryError

log = logging.getLogger("data_factory")

DEFAULT_CONFIG = Path("factory.toml")
LOG_FORMAT = "%(asctime)s %(levelname)-7s %(name)s: %(message)s"


DATASETS = ("nyc311", "olist")


def _stage_order(dataset: str) -> tuple[str, ...]:
    return pipeline.STAGE_NAMES if dataset == "nyc311" else olist_pipeline.STAGE_NAMES


def _stage_list(text: str) -> list[str]:
    """Parse 'fetch,clean' into stage names; each dataset later runs the ones it has, in its order."""
    requested = [name.strip() for name in text.split(",") if name.strip()]
    known = set(pipeline.STAGE_NAMES) | set(olist_pipeline.STAGE_NAMES)
    unknown = [name for name in requested if name not in known]
    if not requested or unknown:
        raise argparse.ArgumentTypeError(
            f"unknown stage(s) {unknown}; nyc311: {list(pipeline.STAGE_NAMES)}, "
            f"olist: {list(olist_pipeline.STAGE_NAMES)}")
    return requested


def _run_dataset(dataset: str, config, args) -> None:
    stages = [name for name in _stage_order(dataset) if args.stages is None or name in args.stages]
    if not stages:
        return
    log.info("dataset %s: stages %s", dataset, stages)
    if dataset == "nyc311":
        pipeline.run(pipeline.RunContext(config=config, since_last_run=args.since_last_run), stages)
    else:
        olist_pipeline.run(pipeline.RunContext(config=config), stages)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="data-factory",
                                     description="Build a clean NYC 311 dataset from the live API.")
    parser.add_argument("--config", type=Path, default=DEFAULT_CONFIG,
                        help=f"configuration file (default: {DEFAULT_CONFIG})")
    parser.add_argument("-v", "--verbose", action="store_true", help="show debug messages")
    commands = parser.add_subparsers(dest="command", required=True)

    run = commands.add_parser("run", help="run the factory (all stages by default)")
    run.add_argument("--dataset", choices=("all",) + DATASETS, default="all",
                     help="which dataset to build (default: all, nyc311 then olist)")
    run.add_argument("--stages", type=_stage_list, default=None,
                     help=f"comma-separated subset; nyc311: {','.join(pipeline.STAGE_NAMES)}; "
                          f"olist: {','.join(olist_pipeline.STAGE_NAMES)}")
    run.add_argument("--since-last-run", action="store_true",
                     help="fetch only records created after the previous run")

    commands.add_parser("check-config", help="load and validate the configuration, then stop")
    commands.add_parser("check-db", help="connect to the database and print the server version")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    logging.basicConfig(level=logging.DEBUG if args.verbose else logging.INFO, format=LOG_FORMAT)
    try:
        config = load_config(args.config)
        if args.command == "check-config":
            log.info("configuration is valid: %s", config.path)
            return ExitCode.OK
        if args.command == "check-db":
            with database(config.database) as engine:
                log.info("connected to %s (url from %s): %s", safe_url(config.database.url),
                         config.database.source, server_version(engine))
            return ExitCode.OK
        for dataset in (DATASETS if args.dataset == "all" else (args.dataset,)):
            _run_dataset(dataset, config, args)
        return ExitCode.OK
    except FactoryError as error:
        log.error("%s: %s", type(error).__name__, error)
        return error.exit_code
    except Exception:  # a bug: show the full traceback
        log.exception("unexpected error")
        return ExitCode.UNEXPECTED
