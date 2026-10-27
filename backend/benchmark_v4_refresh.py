"""Local, no-I/O replay of the importer on fictional confirmation/daily records."""
import argparse
import json
from copy import deepcopy
from statistics import median
from time import perf_counter

from scripts.benchmark_source_sync import source_records
from .seed import seed
from .sources import import_sources


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--projects', type=int, default=319)
    parser.add_argument('--dailies-per-project', type=int, default=28)
    parser.add_argument('--samples', type=int, default=5)
    args = parser.parse_args()
    if min(args.projects, args.samples) < 1 or args.dailies_per_project < 0:
        parser.error('counts must be positive; dailies-per-project may be zero')
    records = source_records(args.projects, args.dailies_per_project)
    workspace = seed(True)
    import_sources(workspace, records)
    samples = []
    for _ in range(args.samples):
        state = deepcopy(workspace)
        started = perf_counter()
        stats = import_sources(state, records)
        samples.append(round((perf_counter() - started) * 1000, 2))
        assert stats['daily_imported'] == args.projects * args.dailies_per_project
    print(json.dumps({'projects': args.projects, 'dailies': args.projects * args.dailies_per_project,
                      'median_ms': median(samples), 'samples': samples}))


if __name__ == '__main__': main()
