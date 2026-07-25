"""Command-line entry point for reshare-control."""

from __future__ import print_function

import argparse
import json
import sys

from .config import (
    DEFAULT_CONFIG_DIR,
    ConfigError,
    load_config,
    mask_for_log,
    mask_username,
    save_config,
)
from .enforce import EnforcementError, enable_account, stop_account
from .parse import validate_userstats_body
from .poller import run_cycle
from .state import StateError, StateStore
from .webif import AUTH_FAILED, OK, OTHER_HTTP, TRANSPORT_ERROR, CurlFetcher


EXIT_SUCCESS = 0
EXIT_FAILURE = 1
EXIT_AUTH_FAILED = 2
EXIT_TRANSPORT_ERROR = 3
EXIT_UNPARSEABLE = 4


class CommandDeferred(NotImplementedError):
    pass


def build_parser():
    parser = argparse.ArgumentParser(prog="reshare-control")
    parser.add_argument("--config-dir", default=DEFAULT_CONFIG_DIR,
                        help="configuration directory (default: %(default)s)")
    parser.add_argument("--json", action="store_true", dest="json_output",
                        help="emit JSON output where supported")
    subparsers = parser.add_subparsers(dest="command")

    run = subparsers.add_parser("run", help="run one poll cycle")
    run.add_argument("--dry-run", action="store_true", help="evaluate without writing or enforcing")
    run.add_argument("--json", action="store_true", dest="command_json_output",
                     help="emit JSON output")

    status = subparsers.add_parser("status", help="print current persisted state")
    status.add_argument("--json", action="store_true", dest="command_json_output",
                        help="emit JSON output")

    test = subparsers.add_parser("test", help="validate WebIF connectivity")
    test.add_argument("--json", action="store_true", dest="command_json_output",
                      help="emit JSON output")

    for command in ("disable-user", "enable-user", "exempt-user", "unexempt-user"):
        item = subparsers.add_parser(command, help="%s (implemented in later user stories)" % command)
        item.add_argument("name")

    return parser


def main(argv=None):
    parser = build_parser()
    args = parser.parse_args(argv)
    if not args.command:
        parser.print_help(sys.stderr)
        return EXIT_FAILURE
    if getattr(args, "command_json_output", False):
        args.json_output = True
    try:
        return dispatch(args)
    except (ConfigError, StateError, EnforcementError, IOError, OSError) as exc:
        _error(args, str(exc))
        return EXIT_FAILURE
    except CommandDeferred as exc:
        _error(args, str(exc))
        return EXIT_FAILURE


def dispatch(args):
    table = {
        "run": command_run,
        "status": command_status,
        "test": command_test,
        "disable-user": command_disable_user,
        "enable-user": command_enable_user,
        "exempt-user": command_exempt_user,
        "unexempt-user": command_unexempt_user,
    }
    handler = table.get(args.command)
    if handler is None:
        raise CommandDeferred("unknown command: %s" % args.command)
    config = load_config(args.config_dir)
    return handler(args, config)


def command_run(args, config):
    store = StateStore(args.config_dir)
    result = run_cycle(config, store, dry_run=getattr(args, "dry_run", False))
    if getattr(args, "json_output", False):
        print(json.dumps(result.to_dict(), sort_keys=True))
    else:
        for user in result.users:
            print("%s  %s  %s  %s" % (
                mask_username(user.name),
                _format_ecm(user.ecm_per_min),
                user.state.status,
                user.state.consecutive_strikes,
            ))
    return EXIT_SUCCESS


def command_status(args, config):
    store = StateStore(args.config_dir)
    state = store.load()
    if getattr(args, "json_output", False):
        print(json.dumps(state.to_dict(), sort_keys=True))
        return EXIT_SUCCESS
    for name, user_state in sorted(state.users.items()):
        print("%s  %s  %s  %s" % (
            mask_username(name),
            _format_ecm(user_state.last_observed_ecm_min),
            user_state.status,
            user_state.consecutive_strikes,
        ))
    return EXIT_SUCCESS


def command_test(args, config):
    fetcher = CurlFetcher(config.base_url(), auth=config.auth(),
                          timeout_s=config.request_timeout_s)
    result = fetcher.get("/oscamapi.json?part=userstats")
    if result.status == AUTH_FAILED:
        _test_output(args, False, "authentication failed", EXIT_AUTH_FAILED,
                     config=config, fetch=result)
        return EXIT_AUTH_FAILED
    if result.status == TRANSPORT_ERROR:
        _test_output(args, False, "transport error", EXIT_TRANSPORT_ERROR,
                     config=config, fetch=result)
        return EXIT_TRANSPORT_ERROR
    if result.status == OTHER_HTTP:
        _test_output(args, False, "unexpected HTTP response", EXIT_UNPARSEABLE,
                     config=config, fetch=result)
        return EXIT_UNPARSEABLE
    if result.status != OK:
        _test_output(args, False, "unusable WebIF response", EXIT_UNPARSEABLE,
                     config=config, fetch=result)
        return EXIT_UNPARSEABLE

    validation = validate_userstats_body(result.body)
    if validation.has_usable_active_ecm:
        _test_output(args, True, "validated WebIF userstats", EXIT_SUCCESS,
                     config=config, fetch=result, validation=validation)
        return EXIT_SUCCESS
    _test_output(args, False, "reachable but no usable ECM/min stats",
                 EXIT_UNPARSEABLE, config=config, fetch=result,
                 validation=validation)
    return EXIT_UNPARSEABLE


def command_disable_user(args, config):
    store = StateStore(args.config_dir)
    with store.locked():
        state = store.load()
        user_state = state.get_user(args.name) or UserStrikeState()
        stop_account(
            config,
            args.config_dir,
            args.name,
            user_state,
            user_state.last_observed_ecm_min,
        )
        state.set_user(args.name, user_state)
        store.save(state)
    _command_user_output(args, "disabled", args.name)
    return EXIT_SUCCESS


def command_enable_user(args, config):
    store = StateStore(args.config_dir)
    enable_account(config, args.config_dir, args.name, store)
    _command_user_output(args, "enabled", args.name)
    return EXIT_SUCCESS


def command_exempt_user(args, config):
    if args.name not in config.exempt_users:
        config.exempt_users.append(args.name)
        save_config(config, args.config_dir)
    _command_user_output(args, "exempted", args.name)
    return EXIT_SUCCESS


def command_unexempt_user(args, config):
    if args.name in config.exempt_users:
        config.exempt_users = [name for name in config.exempt_users if name != args.name]
        save_config(config, args.config_dir)
    _command_user_output(args, "unexempted", args.name)
    return EXIT_SUCCESS


def _error(args, message):
    if getattr(args, "json_output", False):
        print(json.dumps({"ok": False, "error": message}), file=sys.stderr)
    else:
        print("error: %s" % message, file=sys.stderr)


def _test_output(args, ok, message, exit_code, config=None, fetch=None,
                 validation=None):
    if getattr(args, "json_output", False):
        payload = {
            "ok": ok,
            "message": message,
            "exit_code": exit_code,
        }
        if fetch is not None:
            payload["status"] = fetch.status
            payload["http_status"] = fetch.http_status
            payload["curl_exit"] = fetch.curl_exit
        if validation is not None:
            payload["validation"] = validation.to_dict()
        print(json.dumps(payload, sort_keys=True))
        return
    if ok:
        print(message)
        return
    details = ""
    if fetch is not None and fetch.http_status is not None:
        details = " (HTTP %s)" % fetch.http_status
    if fetch is not None and fetch.curl_exit is not None:
        details = " (curl exit %s)" % fetch.curl_exit
    if config is not None and config.webif_user:
        details += " for user %s" % mask_for_log({"webif_user": config.webif_user})["webif_user"]
    print("%s%s" % (message, details), file=sys.stderr)


def _format_ecm(value):
    if value is None:
        return "NO_READING"
    if str(value) == "NO_READING":
        return "NO_READING"
    return value


def _command_user_output(args, action, name):
    if getattr(args, "json_output", False):
        print(json.dumps({"ok": True, "action": action, "user": name}, sort_keys=True))
    else:
        print("%s %s" % (action, mask_username(name)))


def print_config_summary(config, json_output=False):
    data = config.to_dict()
    data["webif_pass"] = "***"
    if json_output:
        print(json.dumps(data, sort_keys=True))
    else:
        print(json.dumps(mask_for_log(data), sort_keys=True))


if __name__ == "__main__":
    sys.exit(main())
