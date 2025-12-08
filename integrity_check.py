import os
import sys
import argparse
import re
import io
import contextlib
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple

MAX_ERRORS = 100
CBCL_SUFFIXES = (".cbcl", ".cbcl.gz", ".cbcl.bgzf", ".cbcl.bgz")
FLAT_BCL_SUFFIXES = (".bcl", ".bcl.gz", ".bcl.bgzf", ".bcl.bgz")


class TeeStream:
    def __init__(self, primary, buffer):
        self.primary = primary
        self.buffer = buffer

    def write(self, data: str):
        self.primary.write(data)
        self.buffer.write(data)

    def flush(self):
        self.primary.flush()
        self.buffer.flush()


@dataclass
class LaneLayout:
    name: str
    filters: List[str]
    layout: str
    cbcl_files: List[str] = field(default_factory=list)
    flat_cycles: Dict[int, str] = field(default_factory=dict)
    flat_suffix: str = ".bcl"


class RunVerifier:
    """Wraps run verification to share counters, helpers, and messaging."""

    def __init__(self, run_folder_path: str):
        self.run_folder_path = os.path.abspath(run_folder_path)
        self.base_calls_dir = os.path.join(self.run_folder_path, "Data", "Intensities", "BaseCalls")
        self.files_checked = 0
        self.files_missing = 0

    # ---- Core workflow ----

    def verify(self):
        self._ensure_runinfo_present()
        run_params = self._get_run_parameters()
        lanes = self._discover_layout()

        tasks = [
            ('R1', run_params['R1']),
            ('I1', run_params['I1']),
            ('I2', run_params['I2']),
            ('R2', run_params['R2']),
        ]
        # Reads are processed sequentially so cycle numbers keep increasing across read segments.

        print("\nStarting file verification...")
        self._check_run_level_artifacts()

        if self._abort_if_limit():
            lanes = []

        for lane_layout in lanes:
            if self._abort_if_limit():
                break
            self._verify_lane(lane_layout, tasks)

        self._print_summary()

    # ---- Helpers: filesystem guards ----

    def _ensure_runinfo_present(self):
        """Confirm RunInfo.xml exists and is non-empty before continuing."""
        run_info_path = os.path.join(self.run_folder_path, "RunInfo.xml")
        if not os.path.exists(run_info_path):
            print(f"Error: RunInfo.xml not found in {self.run_folder_path}", file=sys.stderr)
            sys.exit(1)

        try:
            if os.path.getsize(run_info_path) == 0:
                print(f"Error: RunInfo.xml is empty in {self.run_folder_path}", file=sys.stderr)
                sys.exit(1)
        except OSError as e:
            print(f"Error: Unable to access RunInfo.xml at {run_info_path}: {e}", file=sys.stderr)
            sys.exit(1)

    def _get_run_parameters(self) -> Dict[str, int]:
        """Parse RunParameters.xml to get cycle counts for each read."""
        xml_path = os.path.join(self.run_folder_path, "RunParameters.xml")
        if not os.path.exists(xml_path):
            print(f"Error: RunParameters.xml not found in {self.run_folder_path}", file=sys.stderr)
            sys.exit(1)

        print(f"Parsing {xml_path}...")

        try:
            tree = ET.parse(xml_path)
            root = tree.getroot()

            def parse_int(text: Optional[str]) -> int:
                if text is None:
                    return 0
                text = text.strip()
                if not text:
                    return 0
                try:
                    return int(text)
                except ValueError:
                    return 0

            def get_cycles(paths: List[str]) -> int:
                for path in paths:
                    node = root.find(path)
                    if node is not None:
                        value = parse_int(node.text)
                        if value:
                            return value
                return 0

            def parse_reads_block() -> Dict[str, int]:
                reads_elem = root.find("Reads")
                parsed = {'R1': 0, 'I1': 0, 'I2': 0, 'R2': 0}
                if reads_elem is None:
                    return parsed

                for read_elem in reads_elem.findall("Read"):
                    num_cycles = parse_int(
                        read_elem.get("NumCycles") or read_elem.findtext("NumCycles")
                    )
                    if num_cycles <= 0:
                        continue

                    is_index_attr = read_elem.get("IsIndexedRead") or read_elem.findtext("IsIndexedRead")
                    is_index = str(is_index_attr).strip().lower() in {"y", "yes", "true", "1"}
                    if is_index:
                        if parsed['I1'] == 0:
                            parsed['I1'] = num_cycles
                        elif parsed['I2'] == 0:
                            parsed['I2'] = num_cycles
                    else:
                        if parsed['R1'] == 0:
                            parsed['R1'] = num_cycles
                        elif parsed['R2'] == 0:
                            parsed['R2'] = num_cycles
                return parsed

            run_params = {
                'R1': get_cycles(['Read1NumberOfCycles', 'Setup/Read1']),
                'I1': get_cycles(['IndexRead1NumberOfCycles', 'Setup/Index1Read']),
                'I2': get_cycles(['IndexRead2NumberOfCycles', 'Setup/Index2Read']),
                'R2': get_cycles(['Read2NumberOfCycles', 'Setup/Read2']),
            }

            if any(value == 0 for value in run_params.values()):
                # Older instrument setups sometimes only populate the <Reads> block, so fall back to it.
                fallback_reads = parse_reads_block()
                for key in run_params:
                    if run_params[key] == 0 and fallback_reads.get(key, 0):
                        run_params[key] = fallback_reads[key]

            print(f" - Found Read 1: {run_params['R1']} cycles")
            print(f" - Found Index 1: {run_params['I1']} cycles")
            print(f" - Found Index 2: {run_params['I2']} cycles")
            print(f" - Found Read 2: {run_params['R2']} cycles")

            if run_params['R1'] == 0:
                print("Warning: Could not parse Read1NumberOfCycles. Assuming 0.", file=sys.stderr)

            return run_params

        except ET.ParseError as e:
            print(f"Error: Failed to parse RunParameters.xml: {e}", file=sys.stderr)
            sys.exit(1)

    def _discover_layout(self) -> List[LaneLayout]:
        """
        Discover lanes and expected file layout by scanning the filesystem.
        Returns a LaneLayout for each lane.
        """
        if not os.path.isdir(self.base_calls_dir):
            print(f"Error: BaseCalls directory not found at {self.base_calls_dir}", file=sys.stderr)
            sys.exit(1)

        try:
            lanes = sorted(
                d for d in os.listdir(self.base_calls_dir)
                if d.startswith('L')
                and d[1:].isdigit()
                and os.path.isdir(os.path.join(self.base_calls_dir, d))
            )
        except OSError as e:
            print(f"Error: Could not list lanes in {self.base_calls_dir}: {e}", file=sys.stderr)
            sys.exit(1)

        if not lanes:
            print(f"Error: No Lane directories (e.g., L001) found in {self.base_calls_dir}", file=sys.stderr)
            sys.exit(1)

        print(f" - Discovered Lanes: {', '.join(lanes)}")

        cycle_pattern = re.compile(r"^C(\d+)\.")
        flat_bcl_pattern = re.compile(r"^(\d+)\.bcl", re.IGNORECASE)
        lane_tiles_map: Optional[Dict[str, List[str]]] = None
        # RunInfo parsing is deferred until we actually need it so we can tailor how the tile
        # information is used (e.g., validation-only for CBCL layouts).

        lane_layouts: List[LaneLayout] = []

        for lane in lanes:
            lane_dir = os.path.join(self.base_calls_dir, lane)
            try:
                entries = os.listdir(lane_dir)
            except OSError as e:
                print(f"Error: Could not inspect lane directory {lane_dir}: {e}", file=sys.stderr)
                sys.exit(1)

            filter_files = sorted([f for f in entries if f.endswith(".filter")])
            if filter_files:
                print(f"   Lane {lane}: {len(filter_files)} .filter files discovered (e.g., {filter_files[0]})")
            else:
                print(f"   Lane {lane}: no .filter files detected - filter verification will be skipped for this lane.")

            cycle_dirs: List[Tuple[int, str]] = []
            for entry in entries:
                match = cycle_pattern.match(entry)
                if match and os.path.isdir(os.path.join(lane_dir, entry)):
                    cycle_dirs.append((int(match.group(1)), entry))
            cycle_dirs.sort(key=lambda item: (item[0], item[1]))

            flat_cycle_map: Dict[int, str] = {}
            flat_suffix_hint = None
            flat_candidates = sorted(
                f for f in entries
                if any(f.endswith(suffix) for suffix in FLAT_BCL_SUFFIXES) and not f.endswith(".bci")
            )
            # Flat BCL layouts keep all cycles in one directory; filenames encode the cycle number.
            for candidate in flat_candidates:
                match = flat_bcl_pattern.match(candidate)
                if not match:
                    continue
                cycle_num = int(match.group(1))
                flat_cycle_map[cycle_num] = candidate
                if flat_suffix_hint is None:
                    suffix_start = len(match.group(1))
                    flat_suffix_hint = candidate[suffix_start:]

            if not cycle_dirs and flat_cycle_map:
                example_cycle = min(flat_cycle_map)
                example_file = flat_cycle_map[example_cycle]
                print(f"   Lane {lane}: {len(flat_cycle_map)} flat .bcl files discovered (e.g., {example_file})")
                lane_layouts.append(
                    LaneLayout(
                        name=lane,
                        filters=filter_files,
                        layout="flat",
                        flat_cycles=flat_cycle_map,
                        flat_suffix=flat_suffix_hint or ".bcl",
                    )
                )
                continue

            if not cycle_dirs:
                print(f"Error: No cycle directories (C*.1) found in {lane_dir}", file=sys.stderr)
                sys.exit(1)

            cbcl_files: List[str] = []
            cbcl_cycle_hint = None

            for _, cycle_name in cycle_dirs:
                cycle_dir_path = os.path.join(lane_dir, cycle_name)
                try:
                    cycle_entries = os.listdir(cycle_dir_path)
                except OSError as e:
                    print(f"Error: Could not read files in {cycle_dir_path}: {e}", file=sys.stderr)
                    sys.exit(1)

                discovered_cbcls = sorted(
                    f for f in cycle_entries
                    if any(f.endswith(suffix) for suffix in CBCL_SUFFIXES)
                )
                # The first populated cycle directory tells us which CBCL tiles to expect everywhere.
                if discovered_cbcls:
                    cbcl_files = discovered_cbcls
                    cbcl_cycle_hint = cycle_name
                    break

            if cbcl_files:
                print(f"   Lane {lane}: {len(cbcl_files)} .cbcl files discovered in {cbcl_cycle_hint} (e.g., {cbcl_files[0]})")
            else:
                if lane_tiles_map is None:
                    lane_tiles_map = self._load_tiles_from_runinfo(
                        lanes, require_tile_filenames=False
                    )
                lane_tiles = lane_tiles_map.get(lane, [])
                if not lane_tiles:
                    print(f"Error: Unable to determine expected .cbcl files for {lane}", file=sys.stderr)
                    sys.exit(1)

                cbcl_files = [f"{lane}_1.cbcl", f"{lane}_2.cbcl"]
                print(
                    f"   Lane {lane}: no .cbcl files discovered; assuming surface-level naming"
                    f" (e.g., {cbcl_files[0]}) based on RunInfo.xml validation"
                )

            lane_layouts.append(
                LaneLayout(
                    name=lane,
                    filters=filter_files,
                    layout="cycle_dirs",
                    cbcl_files=cbcl_files,
                )
            )

        return lane_layouts

    # ---- Helpers: parsing RunInfo ----

    @staticmethod
    def _parse_lane_number(lane_name: str) -> int:
        digits = ''.join(ch for ch in lane_name if ch.isdigit())
        return int(digits) if digits else -1

    @staticmethod
    def _infer_lane_from_tile_id(tile_id: str, lane_map: Dict[int, str]) -> Optional[str]:
        parts = tile_id.split('_')
        for part in parts:
            digits = ''.join(ch for ch in part if ch.isdigit())
            if not digits:
                continue
            lane_number = int(digits)
            if lane_number in lane_map:
                return lane_map[lane_number]
        return None

    def _load_tiles_from_runinfo(
        self, lanes: List[str], require_tile_filenames: bool = True
    ) -> Dict[str, List[str]]:
        """Parse RunInfo.xml and build a mapping of lane name -> list of tile ids.

        When require_tile_filenames is False we only validate that tiles exist for each lane
        and return placeholder entries instead of actual tile identifiers.
        """
        run_info_path = os.path.join(self.run_folder_path, "RunInfo.xml")
        try:
            tree = ET.parse(run_info_path)
            root = tree.getroot()
        except ET.ParseError as e:
            print(f"Error: Failed to parse RunInfo.xml: {e}", file=sys.stderr)
            sys.exit(1)
        except OSError as e:
            print(f"Error: Unable to read RunInfo.xml at {run_info_path}: {e}", file=sys.stderr)
            sys.exit(1)

        tile_nodes = root.findall(".//Tiles/Tile")
        if not tile_nodes:
            print("Error: No <Tile> entries found in RunInfo.xml", file=sys.stderr)
            sys.exit(1)

        lane_number_map = {}
        for lane in lanes:
            number = self._parse_lane_number(lane)
            if number > 0:
                lane_number_map[number] = lane

        lane_tiles: Dict[str, List[str]] = {lane: [] for lane in lanes}
        global_tiles: List[str] = []
        # Some RunInfo files omit lane prefixes; treat such tiles as belonging to every lane.

        for tile_node in tile_nodes:
            if tile_node.text is None:
                continue
            tile_id = tile_node.text.strip()
            if not tile_id:
                continue
            lane_name = self._infer_lane_from_tile_id(tile_id, lane_number_map)
            if lane_name:
                lane_tiles[lane_name].append(tile_id)
            else:
                global_tiles.append(tile_id)
                # Tile lacks explicit lane reference; keep it for later replication.

        if not any(lane_tiles.values()) and not global_tiles:
            print("Error: Unable to determine tile assignments from RunInfo.xml", file=sys.stderr)
            sys.exit(1)

        if global_tiles:
            for lane in lanes:
                lane_tiles[lane].extend(global_tiles)

        for lane in lanes:
            if not lane_tiles[lane]:
                print(f"Error: No tile entries mapped to lane {lane} in RunInfo.xml", file=sys.stderr)
                sys.exit(1)
            lane_tiles[lane].sort()
            if not require_tile_filenames:
                lane_tiles[lane] = ["RunInfoTilesValidated"]

        return lane_tiles

    # ---- Helpers: verification ----

    def _check_run_level_artifacts(self):
        copy_complete_path = os.path.join(self.run_folder_path, "CopyComplete.txt")
        self._increment_checked()
        if not os.path.isfile(copy_complete_path):
            print("  MISSING: CopyComplete.txt in the run root.")
            self._record_missing()
        else:
            try:
                os.path.getsize(copy_complete_path)
            except OSError as e:
                print(f"  ERROR accessing {copy_complete_path}: {e}")
                self._record_missing()
            else:
                print("  Completion flag detected: CopyComplete.txt")

        rta_complete_path = os.path.join(self.run_folder_path, "RTAComplete.txt")
        self._increment_checked()
        if os.path.isfile(rta_complete_path):
            try:
                if os.path.getsize(rta_complete_path) == 0:
                    print(f"  Warning: RTAComplete.txt is empty at {rta_complete_path}")
            except OSError as e:
                print(f"  ERROR accessing {rta_complete_path}: {e}")
                self._record_missing()
        else:
            print("  Note: RTAComplete.txt not present.")

        interop_dir = os.path.join(self.run_folder_path, "InterOp")
        self._increment_checked()
        if not os.path.isdir(interop_dir):
            print(f"  MISSING: InterOp directory at {interop_dir}")
            self._record_missing()
        else:
            try:
                interop_entries = os.listdir(interop_dir)
            except OSError as e:
                print(f"  ERROR accessing InterOp directory at {interop_dir}: {e}")
                self._record_missing()
                interop_entries = []

            bin_files = [
                f for f in interop_entries
                if f.lower().endswith(".bin") and os.path.isfile(os.path.join(interop_dir, f))
            ]
            self._increment_checked()
            if not bin_files:
                print(f"  MISSING: no .bin files found in {interop_dir}")
                self._record_missing()
            else:
                non_empty_found = False
                example_file = None
                for bin_file in bin_files:
                    bin_path = os.path.join(interop_dir, bin_file)
                    try:
                        if os.path.getsize(bin_path) > 0:
                            non_empty_found = True
                            example_file = bin_file
                            break
                    except OSError as e:
                        print(f"  ERROR accessing {bin_path}: {e}")
                        self._record_missing()
                if non_empty_found:
                    print(f"  InterOp verified: found non-empty {example_file}")
                else:
                    print(f"  EMPTY: all InterOp .bin files are zero bytes in {interop_dir}")
                    self._record_missing()

        logs_dir = os.path.join(self.run_folder_path, "Logs")
        self._increment_checked()
        if not os.path.isdir(logs_dir):
            print(f"  MISSING: Logs directory at {logs_dir}")
            self._record_missing()
        else:
            print(f"  Logs directory present: {logs_dir}")

    def _verify_lane(self, lane_layout: LaneLayout, tasks: List[Tuple[str, int]]):
        print(f"Verifying Lane: {lane_layout.name}")
        base_calls_lane_dir = os.path.join(self.base_calls_dir, lane_layout.name)

        if self._abort_if_limit():
            return

        if lane_layout.filters:
            for filter_file in lane_layout.filters:
                file_path = os.path.join(base_calls_lane_dir, filter_file)
                self._increment_checked()
                if not os.path.exists(file_path):
                    print(f"  MISSING: {file_path}")
                    self._record_missing()
                    if self._abort_if_limit():
                        return
        else:
            print("  Note: skipping .filter verification (no files detected for this lane).")

        if lane_layout.layout == "cycle_dirs":
            self._verify_cbcl_layout(base_calls_lane_dir, lane_layout.cbcl_files, tasks)
        elif lane_layout.layout == "flat":
            self._verify_flat_layout(base_calls_lane_dir, lane_layout, tasks)
        else:
            print(f"Error: Unknown layout type '{lane_layout.layout}' for {lane_layout.name}", file=sys.stderr)
            sys.exit(1)

    def _verify_cbcl_layout(self, lane_dir: str, cbcl_files: List[str], tasks: List[Tuple[str, int]]):
        total_cycles_so_far = 0
        for _, num_cycles in tasks:
            if num_cycles == 0:
                continue

            for c in range(1, num_cycles + 1):
                cycle_num = total_cycles_so_far + c
                cycle_folder_name = f"C{cycle_num}.1"
                cycle_path = os.path.join(lane_dir, cycle_folder_name)
                if not os.path.isdir(cycle_path):
                    print(f"  MISSING: expected cycle directory {cycle_path}")
                    missing_count = len(cbcl_files)
                    self._record_missing(missing_count)
                    self._increment_checked(missing_count)
                    continue
                # Each cycle directory should contain the same CBCL set; check every tile file.

                for cbcl_name in cbcl_files:
                    file_path = os.path.join(cycle_path, cbcl_name)
                    self._increment_checked()

                    if not os.path.exists(file_path):
                        if cbcl_name == cbcl_files[0]:
                            print(f"  MISSING (examples): {file_path}")
                        self._record_missing()
                        continue

                    try:
                        if os.path.getsize(file_path) == 0:
                            print(f"  EMPTY (0 bytes): {file_path}")
                            self._record_missing()
                    except OSError as e:
                        print(f"  ERROR accessing {file_path}: {e}")
                        self._record_missing()
                    if self._abort_if_limit():
                        return

                if self._abort_if_limit():
                    return

            total_cycles_so_far += num_cycles
            if self._abort_if_limit():
                return

    def _verify_flat_layout(self, lane_dir: str, lane_layout: LaneLayout, tasks: List[Tuple[str, int]]):
        total_cycles_expected = sum(num for _, num in tasks if num > 0)
        if total_cycles_expected == 0:
            cycle_numbers = sorted(lane_layout.flat_cycles.keys())
        else:
            cycle_numbers = list(range(1, total_cycles_expected + 1))
        # When cycle counts are known we expect a contiguous numbering; otherwise rely on discovery.

        for cycle_num in cycle_numbers:
            expected_name = lane_layout.flat_cycles.get(cycle_num)
            if expected_name is None:
                file_hint = f"{cycle_num:04d}{lane_layout.flat_suffix}"
                file_path = os.path.join(lane_dir, file_hint)
                self._increment_checked()
                print(f"  MISSING: {file_path}")
                self._record_missing()
            else:
                file_path = os.path.join(lane_dir, expected_name)
                self._increment_checked()
                if not os.path.exists(file_path):
                    print(f"  MISSING: {file_path}")
                    self._record_missing()
                    continue
                try:
                    if os.path.getsize(file_path) == 0:
                        print(f"  EMPTY (0 bytes): {file_path}")
                        self._record_missing()
                except OSError as e:
                    print(f"  ERROR accessing {file_path}: {e}")
                    self._record_missing()

            if self._abort_if_limit():
                return

        if not self._abort_if_limit() and total_cycles_expected:
            extra_cycles = sorted(
                cycle for cycle in lane_layout.flat_cycles.keys() if cycle > total_cycles_expected
            )
            if extra_cycles:
                print(
                    f"  Note: detected {len(extra_cycles)} additional cycle files beyond expected "
                    f"(e.g., {extra_cycles[0]:04d}{lane_layout.flat_suffix})."
                )

    # ---- Helpers: counters and summary ----

    def _increment_checked(self, count: int = 1):
        self.files_checked += count

    def _record_missing(self, count: int = 1):
        self.files_missing += count

    def _abort_if_limit(self) -> bool:
        if self.files_missing >= MAX_ERRORS:
            print(f"Too many errors detected ({MAX_ERRORS}+). Aborting detailed check.")
            return True
        return False

    def _print_summary(self):
        print("\n--- Verification Summary ---")
        print(f"Total files checked: {self.files_checked}")
        print(f"Total files missing: {self.files_missing}")

        if self.files_missing == 0:
            print("\nSUCCESS: The run appears to be complete.")
        else:
            print(f"\nERROR: {self.files_missing} expected files are missing.")


def verify_run_completeness(run_folder_path: str):
    RunVerifier(run_folder_path).verify()


# --- This block makes the script runnable directly ---
if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Verify Illumina run completeness by checking for all expected files."
    )
    parser.add_argument(
        "run_folder",
        help="Path to the run folder to check (e.g., /media/data1/share/251107_A01229_0623_BHVJN5DRX5)"
    )

    args = parser.parse_args()

    if not os.path.isdir(args.run_folder):
        print(f"Error: Provided path is not a directory: {args.run_folder}", file=sys.stderr)
        sys.exit(1)

    output_buffer = io.StringIO()
    tee_out = TeeStream(sys.stdout, output_buffer)
    tee_err = TeeStream(sys.stderr, output_buffer)
    exit_code = 0

    try:
        with contextlib.redirect_stdout(tee_out), contextlib.redirect_stderr(tee_err):
            verify_run_completeness(args.run_folder)
    except SystemExit as exc:
        exit_code = exc.code if isinstance(exc.code, int) else 1
    finally:
        flag_path = os.path.join(args.run_folder, "filecheck.txt")
        try:
            with open(flag_path, "w") as flag_file:
                flag_file.write(output_buffer.getvalue())
        except OSError as e:
            print(f"Error: Unable to write flag file at {flag_path}: {e}", file=sys.stderr)
            sys.exit(1)

    if exit_code:
        sys.exit(exit_code)
