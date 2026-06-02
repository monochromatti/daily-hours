"""CLI tool to show work hours per day."""

import argparse
import json
import os
import sys
from collections import defaultdict
from contextlib import contextmanager
from datetime import date, datetime, timedelta
from pathlib import Path

try:
    import fcntl
except ImportError:  # pragma: no cover - Unix-only in normal use
    fcntl = None

from rich.console import Console, ConsoleOptions, RenderResult
from rich.measure import Measurement
from rich.segment import Segment
from rich.style import Style
from rich.table import Table
from rich.text import Text

HOURS_PER_DAY = 24.0
WORKING_DAY_START = 6.0
WORKING_DAY_END = 17.0
TIMELINE_WIDTH = 48
TIMELINE_TICK_HOURS = 6
TIMELINE_LABEL_HOURS = (0, 6, 12, 18, 24)

FULL_BLOCK = "█"
PARTIAL_BLOCKS = [" ", "▏", "▎", "▍", "▌", "▋", "▊", "▉"]
STATE_ON = "on"
STATE_OFF = "off"
VALID_STATES = {STATE_ON, STATE_OFF}


def get_week_start(d: date) -> date:
    return d - timedelta(days=d.weekday())


def get_state_dir() -> Path:
    return Path(os.environ.get("XDG_STATE_HOME", Path.home() / ".local" / "state")) / "daily-hours"


def get_event_log_path() -> Path:
    return get_state_dir() / "work-events.jsonl"


def get_lock_path() -> Path:
    return get_state_dir() / "work-events.lock"


@contextmanager
def event_log_lock():
    state_dir = get_state_dir()
    state_dir.mkdir(parents=True, exist_ok=True)
    with get_lock_path().open("a") as lock_file:
        if fcntl is not None:
            fcntl.flock(lock_file, fcntl.LOCK_EX)
        try:
            yield
        finally:
            if fcntl is not None:
                fcntl.flock(lock_file, fcntl.LOCK_UN)


def parse_iso_datetime(raw: str) -> datetime:
    value = datetime.fromisoformat(raw)
    if value.tzinfo is None:
        raise ValueError("timestamp must include timezone offset")
    return value


def now_local() -> datetime:
    return datetime.now().astimezone()


def read_events(path: Path | None = None) -> list[dict[str, str]]:
    event_log = path or get_event_log_path()
    if not event_log.exists():
        return []

    events = []
    with event_log.open() as handle:
        for line_number, line in enumerate(handle, start=1):
            line = line.strip()
            if not line:
                continue
            try:
                event = json.loads(line)
                ts = event["ts"]
                state = event["state"]
                if state not in VALID_STATES:
                    raise ValueError(f"invalid state: {state}")
                parse_iso_datetime(ts)
            except (KeyError, json.JSONDecodeError, ValueError) as error:
                raise ValueError(f"invalid event on line {line_number}: {error}") from error
            events.append(event)
    return events


def current_state(events: list[dict[str, str]] | None = None) -> str:
    event_list = read_events() if events is None else events
    if not event_list:
        return STATE_OFF
    return event_list[-1]["state"]


def append_event(state: str, source: str, timestamp: datetime) -> None:
    event = {"ts": timestamp.isoformat(timespec="seconds"), "state": state}
    if source:
        event["source"] = source
    with get_event_log_path().open("a") as handle:
        handle.write(json.dumps(event, separators=(",", ":")) + "\n")
        handle.flush()
        os.fsync(handle.fileno())


def set_work_state(state: str, source: str, timestamp: datetime) -> bool:
    with event_log_lock():
        events = read_events()
        if current_state(events) == state:
            return False
        append_event(state, source, timestamp)
        return True


def toggle_work_state(source: str, timestamp: datetime) -> str:
    with event_log_lock():
        events = read_events()
        new_state = STATE_OFF if current_state(events) == STATE_ON else STATE_ON
        append_event(new_state, source, timestamp)
        return new_state


def events_to_sessions(events: list[dict[str, str]], end_open_at: datetime) -> list[tuple[datetime, datetime]]:
    sessions = []
    active_start = None
    for event in sorted(events, key=lambda item: parse_iso_datetime(item["ts"])):
        ts = parse_iso_datetime(event["ts"])
        state = event["state"]
        if state == STATE_ON:
            if active_start is None:
                active_start = ts
            continue
        if active_start is not None and ts > active_start:
            sessions.append((active_start, ts))
            active_start = None
    if active_start is not None and end_open_at > active_start:
        sessions.append((active_start, end_open_at))
    return sessions


def to_hour_fraction(dt: datetime) -> float:
    return dt.hour + dt.minute / 60 + dt.second / 3600


def iter_daily_spans(
    start: datetime, end: datetime
) -> list[tuple[date, tuple[float, float]]]:
    spans = []
    current = start

    while current.date() < end.date():
        midnight = datetime.combine(
            current.date() + timedelta(days=1),
            datetime.min.time(),
            tzinfo=current.tzinfo,
        )
        spans.append((current.date(), (to_hour_fraction(current), HOURS_PER_DAY)))
        current = midnight

    spans.append((current.date(), (to_hour_fraction(current), to_hour_fraction(end))))
    return spans


def calculate_daily_spans(
    sessions: list[tuple[datetime, datetime]],
) -> dict[date, list[tuple[float, float]]]:
    daily_spans = defaultdict(list)
    for start, end in sessions:
        if end <= start:
            continue
        for day, span in iter_daily_spans(start, end):
            daily_spans[day].append(span)
    return daily_spans


def calculate_total_hours(spans: list[tuple[float, float]]) -> float:
    return sum(end - start for start, end in spans)


def calculate_window_hours(
    spans: list[tuple[float, float]], start_hour: float, end_hour: float
) -> float:
    return sum(
        max(0.0, min(end, end_hour) - max(start, start_hour)) for start, end in spans
    )


class MultiBar:
    def __init__(
        self,
        size: float,
        spans: list[tuple[float, float]],
        width: int = TIMELINE_WIDTH,
        color: str = "green",
        bgcolor: str = "grey23",
        tick_color: str = "grey27",
        tick_hours: int = TIMELINE_TICK_HOURS,
    ) -> None:
        self.size = size
        self.spans = spans
        self.width = width
        self.tick_hours = tick_hours
        self.on_style = Style(color=color, bgcolor=bgcolor)
        self.off_style = Style(bgcolor=bgcolor)
        self.tick_style = Style(color=tick_color, bgcolor=bgcolor)

    def _tick_cells(self, width: int) -> set[int]:
        return {
            min(width - 1, int(hour / self.size * width))
            for hour in range(0, int(self.size), self.tick_hours)
        }

    def _build_coverage(self, total_eighths: int) -> list[bool]:
        coverage = [False] * total_eighths
        for start, end in self.spans:
            start_clamped = max(0.0, min(self.size, start))
            end_clamped = max(0.0, min(self.size, end))
            if end_clamped <= start_clamped:
                continue

            start_eighth = int(start_clamped / self.size * total_eighths)
            end_eighth = int(end_clamped / self.size * total_eighths)
            if end_eighth <= start_eighth:
                end_eighth = min(total_eighths, start_eighth + 1)

            for index in range(start_eighth, end_eighth):
                coverage[index] = True
        return coverage

    def _cell(self, filled: int, is_tick: bool) -> tuple[str, Style]:
        if filled == 0:
            return ("│", self.tick_style) if is_tick else (" ", self.off_style)
        if filled == 8:
            return FULL_BLOCK, self.on_style
        return PARTIAL_BLOCKS[filled], self.on_style

    def __rich_console__(
        self, console: Console, options: ConsoleOptions
    ) -> RenderResult:
        width = min(self.width, options.max_width)
        if width <= 0:
            yield Segment.line()
            return

        coverage = self._build_coverage(width * 8)
        tick_cells = self._tick_cells(width)
        cells = []

        for cell_index in range(width):
            start = cell_index * 8
            filled = sum(1 for on in coverage[start : start + 8] if on)
            cells.append(self._cell(filled, cell_index in tick_cells))

        current_text = [cells[0][0]]
        current_style = cells[0][1]
        for char, style in cells[1:]:
            if style == current_style:
                current_text.append(char)
                continue
            yield Segment("".join(current_text), current_style)
            current_text = [char]
            current_style = style

        yield Segment("".join(current_text), current_style)
        yield Segment.line()

    def __rich_measure__(
        self, console: Console, options: ConsoleOptions
    ) -> Measurement:
        return Measurement(self.width, self.width)


def build_timeline_labels(width: int = TIMELINE_WIDTH) -> Text:
    labels = [" "] * width
    for hour in TIMELINE_LABEL_HOURS:
        tick_pos = min(width - 1, int(hour / HOURS_PER_DAY * width))
        label = str(hour)
        start = max(0, min(width - len(label), tick_pos - (len(label) - 1)))
        for index, char in enumerate(label):
            labels[start + index] = char
    return Text("".join(labels), style="grey58")


def add_work_command_args(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("action", choices=["on", "off", "toggle", "status"])
    parser.add_argument(
        "--source",
        default="cli",
        help="Caller label persisted with new events (default: cli)",
    )
    parser.add_argument(
        "--at",
        type=parse_iso_datetime,
        default=None,
        help="Timestamp for new event, with timezone offset",
    )


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Show work hours per day")
    subparsers = parser.add_subparsers(dest="command")

    work_parser = subparsers.add_parser("work", help="Control work time tracking")
    add_work_command_args(work_parser)

    parser.add_argument(
        "--weeks",
        "-w",
        type=int,
        default=1,
        help="Number of weeks to show (default: 1, current week)",
    )
    parser.add_argument(
        "--subtract",
        "-s",
        type=float,
        default=0,
        help="Subtract this number from all hours",
    )
    return parser.parse_args()


def handle_work_command(args: argparse.Namespace) -> None:
    timestamp = args.at or now_local()
    try:
        if args.action == "status":
            print(current_state())
        elif args.action == "on":
            set_work_state(STATE_ON, args.source, timestamp)
            print(STATE_ON)
        elif args.action == "off":
            set_work_state(STATE_OFF, args.source, timestamp)
            print(STATE_OFF)
        elif args.action == "toggle":
            print(toggle_work_state(args.source, timestamp))
    except ValueError as error:
        print(f"Error: {error}", file=sys.stderr)
        sys.exit(1)


def main() -> None:
    args = parse_args()
    if args.command == "work":
        handle_work_command(args)
        return

    try:
        sessions = events_to_sessions(read_events(), now_local())
    except ValueError as error:
        print(f"Error: {error}", file=sys.stderr)
        sys.exit(1)
    if not sessions:
        print("No work events found.")
        return

    today = date.today()
    cutoff = get_week_start(today) - timedelta(weeks=args.weeks - 1)
    daily_spans = calculate_daily_spans(sessions)
    filtered = {day: spans for day, spans in daily_spans.items() if day >= cutoff}
    if not filtered:
        print("No uptime data for the selected period.")
        return

    display_days = [
        cutoff + timedelta(days=offset) for offset in range((today - cutoff).days + 1)
    ]

    table = Table(show_header=True, header_style="bold")
    table.add_column("Day", style="cyan", no_wrap=True)
    table.add_column(header=build_timeline_labels())
    table.add_column("Working hours", justify="right", style="magenta")
    table.add_column("Total hours", justify="right", style="magenta")

    for day in display_days:
        spans = sorted(filtered.get(day, []))
        working_hours = (
            calculate_window_hours(spans, WORKING_DAY_START, WORKING_DAY_END)
            - args.subtract
        )
        total_hours = calculate_total_hours(spans) - args.subtract

        table.add_row(
            f"{day.strftime('%a')} {day.isoformat()}",
            MultiBar(HOURS_PER_DAY, spans, width=TIMELINE_WIDTH),
            f"{working_hours:.2f}",
            f"{total_hours:.2f}",
        )

    Console().print(table)


if __name__ == "__main__":
    main()
