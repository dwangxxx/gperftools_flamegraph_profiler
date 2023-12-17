# Use gperftools cpu profiler to profile code and convert the profiler result to flamegraph

```Bash
git clone --recursive git@github.com:dwangxxx/gperftools_flamegraph_profiler.git
```

## 1. Install gperftools

```Bash
git clone https://github.com/gperftools/gperftools.git
sudo apt-get install libunwind8-dev
cd gperftools
./autogen.sh
./configure
make -j8
sudo make install
ldconfig
```

## 2. Compile code and run to generate profiler result

```Bash
g++ gperf_test.cc -o gperf_test -lprofiler
# use you own LD_PRELOAD path
LD_PRELOAD=/usr/local/lib/libprofiler.so.0 CPUPROFILE=./profiler.prof ./gperf_test
```

## 3. Generate the flamegraph result

```Bash
python3 gperf2flamegraph.py gperf_test profiler.prof --svg-output ./profiler.svg --text-output ./profiler.txt
```

Note: FlameGraph is from https://github.com/brendangregg/FlameGraph
