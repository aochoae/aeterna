# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Alberto Ochoa

"""Non-blocking baseline benchmarks; results are informational before 1.0."""

from __future__ import annotations

import asyncio
import time

import pyperf
from aeterna.config import ConfigurationBuilder
from aeterna.di import ServiceCollection, ServiceLifetime, ServiceProvider


class Leaf:
    """Minimal service used as a dependency in the benchmark graph."""

    pass


class Root:
    """Service with one dependency used for resolution benchmarks."""

    def __init__(self, leaf: Leaf):
        """Create a benchmark root service.

        :param leaf: Singleton dependency resolved before constructing the root service.
        """
        self.leaf = leaf


def create_provider() -> ServiceProvider:
    """Build the provider used by the transient-resolution benchmark.

    :return: The service provider.
    :rtype: ServiceProvider
    """
    services = ServiceCollection()
    services.add_type(Leaf, lifetime=ServiceLifetime.SINGLETON)
    services.add_type(Root)
    return services.build_provider()


def create_configuration_builder() -> ConfigurationBuilder:
    """Build a configuration pipeline containing 100 providers.

    :return: This configuration builder.
    :rtype: ConfigurationBuilder
    """
    builder = ConfigurationBuilder()
    for index in range(100):
        builder.add_mapping({"services": {str(index): {"enabled": True}}})
    return builder


def benchmark_transient_resolution(loops: int) -> float:
    """Measure repeated transient service resolution in seconds.

    :param loops: Number of transient ``Root`` resolutions to perform.
    :return: The elapsed duration in seconds.
    :rtype: float
    """

    async def measure() -> float:
        """Run one timed transient-resolution benchmark measurement.

        :return: The elapsed duration in seconds.
        :rtype: float
        """
        provider = create_provider()
        start = time.perf_counter()
        try:
            for _ in range(loops):
                await provider.get(Root)
        finally:
            duration = time.perf_counter() - start
            await provider.close()
        return duration

    return asyncio.run(measure())


def benchmark_configuration_merge(loops: int) -> float:
    """Measure merging independently built configuration pipelines in seconds.

    :param loops: Number of independently built 100-provider pipelines to merge.
    :return: The elapsed duration in seconds.
    :rtype: float
    """

    async def measure() -> float:
        """Run one timed configuration-merge benchmark measurement.

        :return: The elapsed duration in seconds.
        :rtype: float
        """
        builders = [create_configuration_builder() for _ in range(loops)]
        start = time.perf_counter()
        for builder in builders:
            await builder.build()
        return time.perf_counter() - start

    return asyncio.run(measure())


if __name__ == "__main__":
    runner = pyperf.Runner()
    runner.bench_time_func("transient_resolution", benchmark_transient_resolution)
    runner.bench_time_func("configuration_merge_100_providers", benchmark_configuration_merge)
