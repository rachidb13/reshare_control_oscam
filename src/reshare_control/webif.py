"""Fake-able OSCAM WebIF boundary backed by curl."""

import subprocess


OK = "OK"
AUTH_FAILED = "AUTH_FAILED"
TRANSPORT_ERROR = "TRANSPORT_ERROR"
OTHER_HTTP = "OTHER_HTTP"

TRANSPORT_EXIT_CODES = set([6, 7, 28])


class FetchResult(object):
    def __init__(self, status, body="", http_status=None, error="", curl_exit=None):
        self.status = status
        self.body = body
        self.http_status = http_status
        self.error = error
        self.curl_exit = curl_exit

    @property
    def ok(self):
        return self.status == OK


class Fetcher(object):
    """Interface for WebIF fetchers; tests can replace this with a fake."""

    def get(self, path):
        raise NotImplementedError


class CurlFetcher(Fetcher):
    def __init__(self, base_url, auth=None, timeout_s=5, runner=None):
        self.base_url = base_url.rstrip("/")
        self.auth = auth or ("", "")
        self.timeout_s = int(timeout_s)
        self.runner = runner or subprocess.Popen

    def build_command(self, path):
        url = self.base_url + _normalize_path(path)
        command = [
            "curl",
            "--silent",
            "--show-error",
            "--anyauth",
            "--max-time",
            str(self.timeout_s),
            "--write-out",
            "\n%{http_code}",
        ]
        user, password = self.auth
        if user or password:
            command.extend(["-u", "%s:%s" % (user, password)])
        command.append(url)
        return command

    def get(self, path):
        command = self.build_command(path)
        try:
            proc = self.runner(command, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
            stdout, stderr = proc.communicate()
        except OSError as exc:
            return FetchResult(TRANSPORT_ERROR, error=str(exc))
        if not isinstance(stdout, str):
            stdout = stdout.decode("utf-8", "replace")
        if not isinstance(stderr, str):
            stderr = stderr.decode("utf-8", "replace")
        if proc.returncode != 0:
            return FetchResult(TRANSPORT_ERROR, error=stderr.strip(), curl_exit=proc.returncode)
        body, http_status = _split_body_and_status(stdout)
        if http_status == 200:
            return FetchResult(OK, body=body, http_status=http_status)
        if http_status in (401, 403):
            return FetchResult(AUTH_FAILED, body=body, http_status=http_status, error=stderr.strip())
        return FetchResult(OTHER_HTTP, body=body, http_status=http_status, error=stderr.strip())


def reinit(fetcher_or_base_url, auth=None, timeout_s=5):
    if hasattr(fetcher_or_base_url, "get"):
        fetcher = fetcher_or_base_url
    else:
        fetcher = CurlFetcher(fetcher_or_base_url, auth=auth, timeout_s=timeout_s)
    return fetcher.get("/userconfig.html?action=reinit")


def _normalize_path(path):
    return path if path.startswith("/") else "/" + path


def _split_body_and_status(output):
    if "\n" not in output:
        return output, None
    body, status_text = output.rsplit("\n", 1)
    try:
        return body, int(status_text.strip())
    except ValueError:
        return output, None
