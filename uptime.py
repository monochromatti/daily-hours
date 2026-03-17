"""CLI tool to show uptime hours per day on NixOS/systemd systems."""

import argparse
import re
import subprocess
import sys
from collections import defaultdict
from datetime import date, datetime, timedelta, timezone

from rich.console import Console, ConsoleOptions, RenderResult
from rich.measure import Measurement
from rich.segment import Segment
from rich.style import Style
from rich.table import Table
from rich.text import Text

HOURS_PER_DAY = 24.0
TIMELINE_WIDTH = 48
TIMELINE_TICK_HOURS = 6
TIMELINE_LABEL_HOURS = (0, 6, 12, 18, 24)

FULL_BLOCK = "█"
PARTIAL_BLOCKS = [" ", "▏", "▎", "▍", "▌", "▋", "▊", "▉"]
JOURNAL_TIMESTAMP_RE = re.compile(r"(\d{4}-\d{2}-\d{2}\s+\d{2}:\d{2}:\d{2}\s+\S+)")

TZ_ABBREVIATIONS = {
    "UTC": timezone.utc,
    "CET": timezone(timedelta(hours=1)),
    "CEST": timezone(timedelta(hours=2)),
}


def get_week_start(d: date) -> date:
    return d - timedelta(days=d.weekday())


def parse_journal_timestamp(raw_timestamp: str) -> datetime | None:
    try:
        day, clock, tz_name = raw_timestamp.split()
        tz_info = TZ_ABBREVIATIONS.get(tz_name, timezone.utc)
        return datetime.strptime(f"{day} {clock}", "%Y-%m-%d %H:%M:%S").replace(
            tzinfo=tz_info
        )
    except ValueError:
        return None


def parse_boot_line(line: str) -> tuple[datetime, datetime] | None:
    timestamps = JOURNAL_TIMESTAMP_RE.findall(line)
    if len(timestamps) != 2:
        return None

    start = parse_journal_timestamp(timestamps[0])
    end = parse_journal_timestamp(timestamps[1])
    if start is None or end is None:
        return None
    return start, end


def get_boot_sessions() -> list[tuple[datetime, datetime]]:
    result = subprocess.run(
        ["journalctl", "--list-boots", "--no-pager"],
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        print("Error: Could not read boot logs", file=sys.stderr)
        sys.exit(1)

    sessions = []
    for line in result.stdout.splitlines()[1:]:
        parsed = parse_boot_line(line)
        if parsed is not None:
            sessions.append(parsed)
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


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Show uptime hours per day")
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


def main() -> None:
    args = parse_args()
    sessions = get_boot_sessions()
    if not sessions:
        print("No boot sessions found.")
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
    table.add_column("Hours", justify="right", style="magenta")

    for day in display_days:
        spans = sorted(filtered.get(day, []))
        table.add_row(
            f"{day.strftime('%a')} {day.isoformat()}",
            MultiBar(HOURS_PER_DAY, spans, width=TIMELINE_WIDTH),
            f"{calculate_total_hours(spans) - args.subtract:.2f}",
        )

    Console().print(table)


if __name__ == "__main__":
    main()
