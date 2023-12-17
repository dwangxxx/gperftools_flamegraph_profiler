#!/usr/bin/env python3

import bisect
import dataclasses
import os
from pathlib import Path
import re
import subprocess
import typing as tp

def _remove_matching_brackets(s: str, begin='(', end=')') -> str:
    result = ''
    depth = 0
    for c in s:
        if c == begin:
            depth == 1
            continue
        if c == end:
            depth -= 1
            continue
        if depth == 0:
            result += c
    
    return result

def _cleanup_symbol(s):
    s = _remove_matching_brackets(s, '(', ')')
    s = _remove_matching_brackets(s, '[', ']')
    s = _remove_matching_brackets(s, '<', '>')
    s = s.strip(':')

    return s

class Symbol:
    """
    This class represents single symbol(function) in the process
    """

    address: int
    symbol: str
    _cleaned_symbol: tp.Optional[str]

    def __init__(self, address: int, symbol: str):
        self.address = address
        self.symbol = symbol
        self._cleaned_symbol = None

    def simplified_symbol(self) -> str:
        if self._cleaned_symbol is None:
            self._cleaned_symbol = _cleanup_symbol(self.symbol)
        return self._cleaned_symbol


# Use readelf to get the start virtual memory address of the specific object before linked.
def _find_object_start_vma_before_linked(filepath: Path) -> int:
    proc_res = subprocess.run(
        ['readelf', '-W', '-S', filepath.absolute()], text=True, check=True, capture_output=True
    )
    m = re.search(r'\.text\s+PROGBITS\s+([0-9a0-f]+)\s+([0-9a-f]+)', proc_res.stdout)
    if m:
        return int(m.group(1), 16) - int(m.group(2), 16)
    
    return 0

# Use nm to get the virtual address and function symbols of the specific object before linked.
def _find_object_all_symbols_sorted(filepath: Path) -> tp.List[Symbol]:
    proc_output= ''
    # fallback to dynamic symbols (for libraries)
    for extra_args in ([], ['-D']):
        proc_res = subprocess.run(
            [
                'nm',
                '-C',
                '-n',
                '--defined-only',
                '--no-recurse-limit',
                *extra_args,
                filepath.absolute(),
            ],
            text=True,
            check=True,
            capture_output=True
        )
        if proc_res.stdout.strip():
            proc_output = proc_res.stdout
            break
    
    result = []
    for line in proc_output.splitlines():
        fields = line.rstrip().split(None, 2)
        symbol = fields[2]
        result.append(Symbol(int(fields[0], 16), symbol))
    result = sorted(result, key=lambda x: x.address)

    return result


class SymbolResolver:
    @dataclasses.dataclass
    class MappedObject:
        start_address: int
        end_address: int
        offset: int
        obj_path: Path
        is_executable: bool

        all_symbols_sorted: tp.List[Symbol]
        all_addrs_sorted: tp.List[int]
        obj_start_vma: int

    _objects: tp.List[MappedObject]

    def __init__(self, executable: Path, proc_mapped_objects: str, *, executable_only: bool) -> None:
        self._objects = []

        # Text list of mapped objects of cpu profiler result.
        # start_address-end_address rwxp offset dev:dev inode filepath
        for line in proc_mapped_objects.strip().splitlines():
            if line.startswith('build='):
                continue

            fields = line.strip().split()
            # start_address and end_address
            addr_fileds = fields[0].split('-', 1)
            # must be executable(x)
            if len(fields) != 6 or 'x' not in fields[1]:
                continue

            obj_path = Path(fields[5])
            is_executable = obj_path.name == executable.name
            if is_executable:
                obj_path = executable
            # only parse the binary file, not include the related dynamic libraries.
            if executable_only and not is_executable:
                continue
            if not obj_path.exists() or not os.access(obj_path.absolute(), os.R_OK):
                continue

            all_symbols_sorted = _find_object_all_symbols_sorted(obj_path)

            # every mapped object has its specific address and symbos information.
            self._objects.append(
                self.MappedObject(
                    start_address=int(addr_fileds[0], 16),
                    end_address=int(addr_fileds[1], 16),
                    offset=int(fields[2], 16),
                    obj_path=obj_path,
                    is_executable=is_executable,
                    all_symbols_sorted=all_symbols_sorted,
                    all_addrs_sorted=[symbol.address for symbol in all_symbols_sorted],
                    obj_start_vma=_find_object_start_vma_before_linked(obj_path),
                )
            )

    # pcs: call stack program counter.
    def resolve_symbols_batch(self, pcs: set[int], *, simplify_symbol: bool = False, annotate_libname: bool = False) -> tp.Dict[int, str]:
        result: tp.Dict[int, str] = {}
        for obj in self._objects:
            for pc in pcs:
                if not obj.start_address <= pc < obj.end_address:
                    continue
                addr_before_linked = pc - obj.start_address + obj.offset+ obj.obj_start_vma
                idx = bisect.bisect_right(obj.all_addrs_sorted, addr_before_linked) - 1
                if 0 <= idx < len(obj.all_symbols_sorted):
                    sym = obj.all_symbols_sorted[idx]
                    sym_str = sym.simplified_symbol() if simplify_symbol else sym.symbol
                    if annotate_libname and not obj.is_executable:
                        sym_str += f' [{obj.obj_path.name}]'
                    result[pc] = sym_str
        
        return result
    

class FlamegraphData:
    """
    This class represents the data for flamegraph visualization.
    """
    
    def __init__(self, stacks: tp.Dict[str, int], *, default_flamegraph_args: tp.List[str] = []) -> None:
        self._default_flamegraph_args = default_flamegraph_args
        self._data = '\n'.join(f'{s} {c}' for s, c in stacks.items()) + '\n'

    def write_text_output(self, filepath: Path):
        filepath.write_text(self._data)

    def write_svg_ouput(self, filepath: Path, flamegraph_args: tp.List[str] = []):
        subprocess.run(
            ['./FlameGraph/flamegraph.pl', *self._default_flamegraph_args, *flamegraph_args],
            input=self._data,
            stdout=filepath.open('w'),
            text=True,
            check=True
        )
        
