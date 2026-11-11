#!/usr/bin/env python3
"""Download the INEC polling-unit directory from the public CVR locator.

INEC publishes no bulk export: https://cvr.inecnigeria.org/pu only offers a
cascading State -> LGA -> Registration Area -> Polling Unit lookup. This script
walks those same public endpoints and resolves each unit's coordinates from the
locator's map redirect.

It is deliberately polite and restartable:

* every successful response is cached under ``--cache`` (reruns are free),
* requests are throttled to ``--rate`` per second across all workers,
* transient failures are retried with exponential backoff,
* rows are appended to the output CSV, so an interrupted run resumes where it
  stopped.

The output columns match POST /api/admin/import-polling-units.

Only run this if you have INEC's permission to collect their directory. The
script sets an ordinary browser User-Agent because the site's CDN rejects
default Python clients; it does not bypass authentication or paywalls.
"""

from __future__ import annotations

import argparse
import concurrent.futures
import csv
import hashlib
import json
import os
import re
import sys
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import date
from pathlib import Path

BASE = "https://cvr.inecnigeria.org"
LOCATOR = f"{BASE}/pu"
USER_AGENT = (
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/131.0 Safari/537.36"
)
HEADERS = {
    "User-Agent": USER_AGENT,
    "Accept": "application/json, text/javascript, */*; q=0.01",
    "Accept-Language": "en-NG,en;q=0.9",
    "X-Requested-With": "XMLHttpRequest",
    "Referer": LOCATOR,
}
COLUMNS = [
    "state",
    "lga",
    "ward",
    "name",
    "code",
    "latitude",
    "longitude",
    "accessibility",
    "source",
    "source_url",
    "verified_at",
]
SOURCE = "INEC Polling Unit Locator"

# The locator's dropdown values are internal ids (alphabetical, FCT = 15),
# while the option text carries INEC's official state code ("25" -> "24 - LAGOS").
# Verified against live responses: internal 25 -> Lagos, internal 15 -> FCT.
STATE_NAME_OVERRIDES = {"FCT": "Federal Capital Territory"}


class Client:
    def __init__(self, cache_dir: Path, rate: float, retries: int = 8) -> None:
        self.cache_dir = cache_dir
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        self.min_interval = 1.0 / rate if rate > 0 else 0.0
        self.retries = retries
        self._lock = threading.Lock()
        self._last = 0.0
        self._local = threading.local()
        self.requests = 0
        self.cache_hits = 0

    def _opener(self) -> urllib.request.OpenerDirector:
        opener = getattr(self._local, "opener", None)
        if opener is None:
            # Do not follow redirects: the map target in Location holds the
            # coordinates we need.
            class NoRedirect(urllib.request.HTTPRedirectHandler):
                def redirect_request(self, req, fp, code, msg, headers, newurl):
                    return None

            opener = urllib.request.build_opener(NoRedirect)
            self._local.opener = opener
        return opener

    def _throttle(self) -> None:
        if self.min_interval <= 0:
            return
        with self._lock:
            wait = self._last + self.min_interval - time.monotonic()
            if wait > 0:
                time.sleep(wait)
            self._last = time.monotonic()

    def _cache_path(self, key: str) -> Path:
        digest = hashlib.sha256(key.encode()).hexdigest()[:40]
        return self.cache_dir / f"{digest}.json"

    def request(self, method: str, url: str, data: dict[str, str] | None = None):
        key = method + " " + url + " " + json.dumps(data, sort_keys=True)
        path = self._cache_path(key)
        if path.exists():
            self.cache_hits += 1
            with path.open(encoding="utf-8") as fh:
                cached = json.load(fh)
            return cached["status"], cached["headers"], cached["body"]

        body = urllib.parse.urlencode(data).encode() if data else None
        headers = dict(HEADERS)
        if method == "POST":
            # The locator's POST endpoint 404s when it sees the AJAX header that
            # the PublicApi JSON endpoints expect.
            headers.pop("X-Requested-With", None)
            headers["Accept"] = "text/html,application/xhtml+xml"
        last_error: Exception | None = None
        for attempt in range(self.retries):
            self._throttle()
            request = urllib.request.Request(
                url, data=body, headers=headers, method=method
            )
            try:
                with self._opener().open(request, timeout=30) as response:
                    status, headers = response.status, dict(response.headers)
                    text = response.read().decode("utf-8", "replace")
            except urllib.error.HTTPError as exc:
                status, headers = exc.code, dict(exc.headers or {})
                text = exc.read().decode("utf-8", "replace")
            except (urllib.error.URLError, TimeoutError, OSError) as exc:
                last_error = exc
                time.sleep(min(2**attempt, 60))
                continue

            self.requests += 1
            if status in (200, 302):
                payload = {"status": status, "headers": headers, "body": text}
                tmp = path.with_suffix(".tmp")
                with tmp.open("w", encoding="utf-8") as fh:
                    json.dump(payload, fh)
                os.replace(tmp, path)
                return status, headers, text
            if status in (403, 429, 500, 502, 503, 504):
                last_error = RuntimeError(f"HTTP {status} for {url}")
                time.sleep(min(2**attempt, 60))
                continue
            raise RuntimeError(f"HTTP {status} for {url}: {text[:200]}")

        raise RuntimeError(f"Giving up on {url}: {last_error}")

    def get_json(self, path: str, params: dict[str, str] | None = None):
        url = BASE + path
        if params:
            url += "?" + urllib.parse.urlencode(params)
        status, _, text = self.request("GET", url)
        if status != 200:
            raise RuntimeError(f"HTTP {status} for {url}")
        return json.loads(text)


def options(payload) -> list[tuple[str, str]]:
    """Turn the locator's [{ "0": "--SELECT--", "<id>": "<label>", ... }] into pairs."""
    if not isinstance(payload, list) or not payload:
        return []
    first = payload[0]
    return [(key, value) for key, value in first.items() if key not in ("0", "selected")]


def strip_prefix(label: str) -> tuple[str, str]:
    """'01 - AGEGE' -> ('01', 'AGEGE')."""
    match = re.match(r"\s*(\d+)\s*-\s*(.+)", label)
    if not match:
        return "", label.strip()
    return match.group(1), match.group(2).strip()


def tidy(name: str) -> str:
    return re.sub(r"\s+", " ", name).strip().title()


def states(client: Client) -> list[tuple[int, int, str]]:
    """Return (internal_id, official_code, name) for every state."""
    _, _, html = client.request("GET", LOCATOR)
    block = re.search(r'id="SearchStateId".*?</select>', html, re.S)
    if not block:
        raise RuntimeError("Could not find the state list on the locator page")
    found = re.findall(r'<option value="(\d+)">([^<]+)</option>', block.group(0))
    result = []
    for internal, label in found:
        official, name = strip_prefix(label.replace("&amp;", "&"))
        if not official:
            continue
        name = tidy(name)
        name = STATE_NAME_OVERRIDES.get(name.upper(), name)
        result.append((int(internal), int(official), name))
    if len(result) < 36:
        raise RuntimeError(f"Expected at least 36 states, parsed {len(result)}")
    return result


def lgas(client: Client, internal_id: int) -> list[tuple[str, str]]:
    return options(
        client.get_json(
            "/PublicApi/lgas/1/Search",
            {"data[Search][state_id]": str(internal_id)},
        )
    )


def wards(client: Client, lga_id: str) -> list[tuple[str, str]]:
    return options(
        client.get_json(
            "/PublicApi/wards/1/Search",
            {"data[Search][local_government_id]": lga_id},
        )
    )


def polling_units(client: Client, ward_id: str) -> list[tuple[str, str]]:
    return options(
        client.get_json(
            "/PublicApi/pus/1/Search",
            {"data[Search][registration_area_id]": ward_id},
        )
    )


def coordinates(
    client: Client, internal_state: int, lga_id: str, ward_id: str, pu_id: str
) -> tuple[str, str]:
    status, headers, _ = client.request(
        "POST",
        f"{BASE}/pu_locator/index",
        {
            "data[Search][state_id]": str(internal_state),
            "data[Search][local_government_id]": lga_id,
            "data[Search][registration_area_id]": ward_id,
            "data[Search][polling_unit_id]": pu_id,
        },
    )
    location = headers.get("Location") or headers.get("location") or ""
    if status != 302 or not location:
        return "", ""
    match = re.search(r"[?&]q=(-?\d+(?:\.\d+)?),(-?\d+(?:\.\d+)?)", location)
    if not match:
        return "", ""
    return match.group(1), match.group(2)


def load_done(path: Path) -> set[str]:
    if not path.exists():
        return set()
    with path.open(newline="", encoding="utf-8") as fh:
        return {row["code"] for row in csv.DictReader(fh) if row.get("code")}


def verify_mapping(client: Client) -> None:
    """Fail loudly if INEC reshuffles its internal state ids."""
    lagos = lgas(client, 25)
    fct = lgas(client, 15)
    if not lagos or "AGEGE" not in lagos[0][1].upper():
        raise RuntimeError(
            "State id mapping looks wrong: internal 25 did not return Lagos (Agege). "
            "Re-check how states() reads the dropdown."
        )
    if not fct or "ABAJI" not in fct[0][1].upper():
        raise RuntimeError(
            "State id mapping looks wrong: internal 15 did not return FCT (Abaji). "
            "Re-check how states() reads the dropdown."
        )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", default="data/polling_units.inec.csv")
    parser.add_argument("--cache", default=".cache/inec")
    parser.add_argument(
        "--rate", type=float, default=5.0, help="requests per second (default 5)"
    )
    parser.add_argument("--workers", type=int, default=4)
    parser.add_argument(
        "--states",
        default="",
        help="comma-separated state names or official codes (default: all)",
    )
    parser.add_argument(
        "--limit", type=int, default=0, help="stop after N polling units (0 = all)"
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="enumerate units without fetching coordinates",
    )
    parser.add_argument(
        "--verified-at", default=date.today().isoformat(), help="CSV verified_at value"
    )
    args = parser.parse_args()

    client = Client(Path(args.cache), args.rate)
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)

    all_states = states(client)
    verify_mapping(client)
    if args.states:
        wanted = {part.strip().casefold() for part in args.states.split(",") if part.strip()}
        selected = [
            (internal, official, name)
            for internal, official, name in all_states
            if str(official) in wanted or name.casefold() in wanted
        ]
        if not selected:
            print(f"No state matched {args.states!r}", file=sys.stderr)
            return 2
    else:
        selected = all_states

    done = load_done(out)
    new_file = not out.exists()
    handle = out.open("a", newline="", encoding="utf-8")
    writer = csv.writer(handle)
    if new_file:
        writer.writerow(COLUMNS)
        handle.flush()
    write_lock = threading.Lock()

    total_written = 0
    skipped = 0
    started = time.monotonic()

    def process(task):
        (internal, official, state_name, lga_id, lga_num, lga_name, ward_id,
         ward_num, ward_name, pu_id, pu_label) = task
        pu_num, pu_name = strip_prefix(pu_label)
        if not pu_num:
            return None
        code = f"{official:02d}/{int(lga_num):02d}/{int(ward_num):02d}/{int(pu_num):03d}"
        if code in done:
            return "skip"
        lat, lon = ("", "")
        if not args.dry_run:
            lat, lon = coordinates(client, internal, lga_id, ward_id, pu_id)
        return [state_name, lga_name, ward_name, tidy(pu_name), code, lat, lon,
                "unknown", SOURCE, LOCATOR, args.verified_at]

    for internal, official, state_name in selected:
        state_lgas = lgas(client, internal)
        print(f"[{state_name}] {len(state_lgas)} LGAs", file=sys.stderr)
        for lga_id, lga_label in state_lgas:
            lga_num, lga_name = strip_prefix(lga_label)
            if not lga_num:
                print(f"  skipping LGA without code: {lga_label}", file=sys.stderr)
                continue
            lga_name = tidy(lga_name)
            state_wards = wards(client, lga_id)
            for ward_id, ward_label in state_wards:
                ward_num, ward_name = strip_prefix(ward_label)
                if not ward_num:
                    print(f"  skipping ward without code: {ward_label}", file=sys.stderr)
                    continue
                ward_name = tidy(ward_name)
                units = polling_units(client, ward_id)
                if args.limit:
                    remaining = args.limit - total_written
                    if remaining <= 0:
                        break
                    units = units[:remaining]
                tasks = [
                    (internal, official, state_name, lga_id, lga_num, lga_name,
                     ward_id, ward_num, ward_name, pu_id, pu_label)
                    for pu_id, pu_label in units
                ]
                if not tasks:
                    continue
                with concurrent.futures.ThreadPoolExecutor(args.workers) as pool:
                    for row in pool.map(process, tasks):
                        if row is None:
                            continue
                        if row == "skip":
                            skipped += 1
                            continue
                        with write_lock:
                            writer.writerow(row)
                            handle.flush()
                            total_written += 1
                elapsed = time.monotonic() - started
                rate = total_written / elapsed if elapsed else 0
                print(
                    f"  {state_name}/{lga_name}/{ward_name}: {total_written} units "
                    f"({rate:.1f}/s, {client.requests} requests, "
                    f"{client.cache_hits} cached)",
                    file=sys.stderr,
                )
                if args.limit and total_written >= args.limit:
                    break
            if args.limit and total_written >= args.limit:
                break
        if args.limit and total_written >= args.limit:
            break

    handle.close()
    print(
        f"Wrote {total_written} rows to {out} "
        f"({skipped} already present, {client.requests} live requests, "
        f"{client.cache_hits} cached)",
        file=sys.stderr,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
