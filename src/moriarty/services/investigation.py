from __future__ import annotations

from concurrent.futures import Future, ThreadPoolExecutor, TimeoutError
from time import monotonic

from moriarty.domain.models import (
    InvestigationQuery,
    InvestigationResult,
    InvestigationStatus,
    ProviderOutput,
    ProviderResult,
    ProviderStatus,
)
from moriarty.domain.providers import InvestigationProvider


class InvestigationPipeline:
    """Runs isolated providers and combines their results deterministically."""

    def __init__(
        self,
        providers: tuple[InvestigationProvider, ...],
        timeout_seconds: float = 10.0,
    ) -> None:
        if not providers:
            raise ValueError("At least one provider is required.")
        if timeout_seconds <= 0:
            raise ValueError("Provider timeout must be greater than zero.")
        names = [provider.name for provider in providers]
        if len(names) != len(set(names)):
            raise ValueError("Provider names must be unique.")
        self._providers = providers
        self._timeout_seconds = timeout_seconds

    def investigate(self, query: InvestigationQuery) -> InvestigationResult:
        started = monotonic()
        executor = ThreadPoolExecutor(
            max_workers=len(self._providers), thread_name_prefix="moriarty-provider"
        )
        futures: list[tuple[InvestigationProvider, Future[ProviderOutput], float]] = []
        for provider in self._providers:
            provider_started = monotonic()
            futures.append(
                (provider, executor.submit(provider.investigate, query), provider_started)
            )

        results: list[ProviderResult] = []
        try:
            for provider, future, provider_started in futures:
                deadline = started + self._timeout_seconds
                remaining = max(0.0, deadline - monotonic())
                try:
                    output = future.result(timeout=remaining)
                    results.append(
                        ProviderResult(
                            provider=provider.name,
                            status=ProviderStatus.SUCCESS,
                            duration_ms=_elapsed_ms(provider_started),
                            data=output.data,
                            evidence=output.evidence,
                        )
                    )
                except TimeoutError:
                    if future.done():
                        exc = future.exception()
                        results.append(
                            ProviderResult(
                                provider=provider.name,
                                status=ProviderStatus.ERROR,
                                duration_ms=_elapsed_ms(provider_started),
                                error=str(exc) or type(exc).__name__,
                            )
                        )
                    else:
                        future.cancel()
                        results.append(
                            ProviderResult(
                                provider=provider.name,
                                status=ProviderStatus.TIMEOUT,
                                duration_ms=_elapsed_ms(provider_started),
                                error=f"Provider exceeded {self._timeout_seconds:g}s timeout.",
                            )
                        )
                except Exception as exc:
                    results.append(
                        ProviderResult(
                            provider=provider.name,
                            status=ProviderStatus.ERROR,
                            duration_ms=_elapsed_ms(provider_started),
                            error=str(exc) or type(exc).__name__,
                        )
                    )
        finally:
            executor.shutdown(wait=False, cancel_futures=True)

        success_count = sum(
            result.status is ProviderStatus.SUCCESS for result in results
        )
        if success_count == len(results):
            status = InvestigationStatus.SUCCESS
        elif success_count:
            status = InvestigationStatus.PARTIAL
        else:
            status = InvestigationStatus.FAILED
        return InvestigationResult(query=query, status=status, providers=tuple(results))


def _elapsed_ms(started: float) -> int:
    return max(0, round((monotonic() - started) * 1000))
