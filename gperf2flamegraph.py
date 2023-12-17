#!/usr/bin/env python3

"""
Convert gperftools cpu profiler result to flamegraph.
"""

import argparse
import collections
import logging
import typing as tp
import struct
import dataclasses
from pathlib import Path

from utils import SymbolResolver, FlamegraphData


@dataclasses.dataclass
class Stacktrace:
    sample_count: int
    pcs: tp.Tuple[int]
    symbols: tp.Optional[tp.List[str]] = None

@dataclasses.dataclass
class ProfilerResult:
    sampling_period_in_us: int
    proc_mapped_objects: str
    stacktraces: tp.List[Stacktrace]

_UNKNOWN_SYMBOL = '???'

def _parse_profiler_result(filepath: Path):
    f = filepath.open('rb')

    def read_slots(n):
        # 64 bit slots
        return struct.unpack('Q' * n, f.read(8 * n))
    
    header_count, header_slots, version, sampling_period_in_us, padding = read_slots(5)
    assert(
        header_count == 0 and header_slots == 3 and version == 0 and padding == 0
    ), 'Invalid header, this profiler result is not valid'

    result = ProfilerResult(
        sampling_period_in_us=sampling_period_in_us,
        proc_mapped_objects='',
        stacktraces=[],
    )

    # reader profiler records and binary trailer
    while True:
        sample_count, num_pcs = read_slots(2)
        pcs = read_slots(num_pcs)

        if sample_count == 0:
            assert num_pcs == 1, 'Invalid trailer'
            break

        result.stacktraces.append(
            Stacktrace(
                sample_count=sample_count,
                pcs=pcs,
            )
        )

    result.proc_mapped_objects = f.read().decode()

    return result


class Gperf2Flamegraph:
    symbol_resolver: tp.Optional[SymbolResolver]

    def __init__(self, executable_path: Path, profile_result_path: Path, **symbol_resolver_kwargs):
        self.symbol_resolver = None

        self._executable_path = executable_path
        self._profile_result_path = profile_result_path
        self._symbol_resolver_kwargs = symbol_resolver_kwargs

    def process(self, *, simplify_symbol: bool = False, annotate_libname: bool = False, to_microsecond: bool = False) -> FlamegraphData:
        profiler_result = _parse_profiler_result(self._profile_result_path)
        if self.symbol_resolver is None:
            self.symbol_resolver = SymbolResolver(
                self._executable_path, profiler_result.proc_mapped_objects, **self._symbol_resolver_kwargs
            )

        # resolve symbols in profiler_result.stacktraces
        all_pcs: tp.Set[int] = set(
            pc for stacktrace in profiler_result.stacktraces for pc in stacktrace.pcs
        )

        pcs_to_symbols = self.symbol_resolver.resolve_symbols_batch(
            all_pcs, simplify_symbol=simplify_symbol, annotate_libname=annotate_libname
        )
        for stacktrace in profiler_result.stacktraces:
            stacktrace.symbols = []
            for pc in stacktrace.pcs:
                stacktrace.symbols.append(pcs_to_symbols.get(pc, _UNKNOWN_SYMBOL))

        # collect stacks
        stacks: tp.DefaultDict[str, int] = collections.defaultdict(lambda: 0)
        for stacktrace in profiler_result.stacktraces:
            if not stacktrace.symbols:
                continue

            # reverse the cpu profiler call stack to set the outer funtion in the first place.
            symbols = stacktrace.symbols[::-1]
            while (
                len(symbols) > 1
                and symbols[-1] == _UNKNOWN_SYMBOL
            ):
                symbols.pop()
            stacks[';'.join(symbols)] += (
                stacktrace.sample_count * profiler_result.sampling_period_in_us
                if to_microsecond else stacktrace.sample_count
            )

        return FlamegraphData(
            stacks, default_flamegraph_args=['--countname', 'us'] if to_microsecond else []
        )

if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('exe', help='Path to the executable binary.')
    parser.add_argument('prof', help='Path to the cpu profiler result')

    parser.add_argument('--svg-output', default=None, help='The output .svg path.')
    parser.add_argument('--text-output', default=None, help='The output .txt path.')

    parser.add_argument(
        '--simplify-symbol',
        action='store_true',
        help='Simplify symbols, remove template args and function args'
    )

    parser.add_argument(
        '--executable-only',
        action='store_true',
        help='Only resolve the executable binary.'
    )

    parser.add_argument(
        '--annotate-libname',
        action='store_true',
        help='Append "[libname.so]" to final symbols.'
    )

    parser.add_argument(
        '--to-microsecond',
        action='store_true',
        help='Use microsecond as the result unit.'
    )

    args = parser.parse_args()

    proc = Gperf2Flamegraph(Path(args.exe), Path(args.prof), executable_only=args.executable_only)
    res = proc.process(
        simplify_symbol=args.simplify_symbol,
        annotate_libname=args.annotate_libname,
        to_microsecond=args.to_microsecond,
    )

    if args.text_output:
        res.write_text_output(Path(args.text_output))
    if args.svg_output:
        res.write_svg_ouput(Path(args.svg_output))
